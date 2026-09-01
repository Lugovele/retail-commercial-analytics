from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, cast

import polars as pl
import pytest

from retail_analytics.history import PeriodGrain, SourceLedgerEntry, source_artifact_id
from retail_analytics.mart import (
    ComparisonMode,
    CoverageStatus,
    DashboardMartQueryService,
    DashboardMetricQueryRequest,
    MartBuildMetadata,
    MartBuildStatus,
    MetricProvenanceTrace,
    MetricQueryResult,
    PeriodMode,
    PrivateLabelScope,
    RangeAggregationStrategy,
    build_product_store_metric_facts,
    write_mart_metric_facts,
    write_product_store_metric_facts,
)
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA
from retail_analytics.mart.query import (
    _read_product_store_rollup_facts_from_sql,
    _roll_up_product_store_facts,
)


def test_single_period_query_returns_multiple_metrics_with_lineage(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(_request(PeriodMode.SINGLE_PERIOD, date(2025, 1, 1), date(2025, 1, 1)))

    assert response.coverage_status == CoverageStatus.COMPLETE
    assert {result.metric_concept for result in response.metric_results} == {
        "revenue",
        "retailer_margin_pct",
        "weighted_shelf_price_vat",
        "distribution",
    }
    assert response.metric_definition_lineage
    assert response.private_label_scope == PrivateLabelScope.INCLUDE
    assert response.request_scope["private_label_scope"] == "INCLUDE"
    provenance = response.metric_results[0].provenance
    assert provenance is not None
    assert provenance.payload["current_analytical_scope"]["private_label_scope"] == "INCLUDE"
    assert provenance.payload["metric"]["metric_definition_id"]
    assert provenance.payload["value"]["range_aggregation_strategy"]
    assert provenance.payload["run_lineage"]["mart_build_id"] == "build_a"
    assert provenance.payload["run_lineage"]["source_revision_ids"] == ("revision_a",)
    assert provenance.payload["source_evidence"]["status"] == "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS"
    assert "source_row_ids" in provenance.payload["missing_fields"]


def test_lineage_can_be_omitted(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.SINGLE_PERIOD,
            date(2025, 1, 1),
            date(2025, 1, 1),
            include_lineage=False,
        )
    )

    assert response.metric_definition_lineage == ()
    assert all(result.lineage is None for result in response.metric_results)
    provenance_payloads = [_require_provenance(result).payload for result in response.metric_results]
    assert all("metric_definition_id" in payload["missing_fields"] for payload in provenance_payloads)


def test_date_range_sums_additive_metrics(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("revenue",),
        )
    )

    revenue = response.metric_results[0]
    assert revenue.value == 400.0
    assert response.available_periods == (date(2025, 1, 1), date(2025, 2, 1), date(2025, 4, 1))
    assert response.missing_periods == (date(2025, 3, 1),)
    assert response.coverage_status == CoverageStatus.PARTIAL


def test_ratio_of_sums_does_not_average_percentages(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("retailer_margin_pct",),
        )
    )

    result = response.metric_results[0]
    assert result.value == pytest.approx(100.0 / 400.0)
    assert result.value != pytest.approx((0.25 + 0.5 + 0.125) / 3)


def test_weighted_ratio_uses_components(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("weighted_shelf_price_vat",),
        )
    )

    assert response.metric_results[0].value == pytest.approx(810.0 / 80.0)


def test_share_recomputes_from_declared_scope(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(include_share=True), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("category_revenue_share",),
        )
    )

    assert response.metric_results[0].value == pytest.approx(400.0 / 1000.0)
    assert response.metric_results[0].share_scope == "network"


def test_distribution_and_velocity_are_period_only_for_range(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(include_velocity=True), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("distribution", "velocity"),
        )
    )

    assert {result.value for result in response.metric_results} == {None}
    assert {"range_aggregation_period_only"} <= {item.issue_code for item in response.limitations}
    assert all(result.period_values for result in response.metric_results)


def test_no_fake_zero_for_missing_month(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("revenue",),
        )
    )

    assert response.metric_results[0].value == 400.0
    assert date(2025, 3, 1) not in {
        period_value.period_start for period_value in response.metric_results[0].period_values
    }


def test_metric_specific_sparse_periods_get_limitations(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = _facts().filter(
        ~((pl.col("metric_concept") == "retailer_margin_pct") & (pl.col("period_start") == date(2025, 2, 1)))
    )
    write_mart_metric_facts(facts, path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("revenue", "retailer_margin_pct"),
        )
    )

    assert response.coverage_status == CoverageStatus.PARTIAL
    assert "metric_partial_coverage" in {item.issue_code for item in response.limitations}


def test_additive_null_value_does_not_become_zero(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = _facts().with_columns(
        pl.when((pl.col("metric_concept") == "revenue") & (pl.col("period_start") == date(2025, 2, 1)))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("value"))
        .alias("value")
    )
    write_mart_metric_facts(facts, path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("revenue",),
        )
    )

    assert response.metric_results[0].value is None
    assert "additive_value_missing" in {item.issue_code for item in response.limitations}


def test_query_filters_do_not_mix_retailer_source_grain_or_build(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(pl.concat([_facts(), _facts(retailer_id="retailer_b", build_id="build_b")]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(), _build("build_b", "retailer_b")))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("revenue",),
        )
    )

    assert response.mart_build_id == "build_a"
    assert response.metric_results[0].value == 400.0


def test_query_rejects_multiple_matching_builds_without_selector(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(pl.concat([_facts(), _facts(build_id="build_c")]), path)
    service = DashboardMartQueryService(
        path,
        mart_builds=(_build(), _build("build_c", status=MartBuildStatus.APPROVED)),
    )

    with pytest.raises(ValueError, match="Multiple approved mart builds"):
        service.query(_request(PeriodMode.SINGLE_PERIOD, date(2025, 1, 1), date(2025, 1, 1)))


def test_active_revision_guard_rejects_inactive_build_revision(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = DashboardMartQueryService(
        path,
        mart_builds=(_build(),),
        source_ledger=(_ledger("revision_inactive", active=True),),
    )

    with pytest.raises(ValueError, match="inactive source revisions"):
        service.query(_request(PeriodMode.SINGLE_PERIOD, date(2025, 1, 1), date(2025, 1, 1)))


def test_source_revision_ambiguity_in_facts_is_rejected(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    duplicate_revision = _facts(build_id="build_a").with_columns(
        pl.lit("revision_b").alias("source_revision_id"),
        pl.lit("analysis_b").alias("analysis_run_id"),
    )
    write_mart_metric_facts(pl.concat([_facts(), duplicate_revision]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    with pytest.raises(ValueError, match="Multiple source revisions"):
        service.query(_request(PeriodMode.SINGLE_PERIOD, date(2025, 1, 1), date(2025, 1, 1)))


def test_duplicate_analysis_outputs_are_rejected(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    duplicate_analysis = _facts(build_id="build_a").with_columns(pl.lit("analysis_b").alias("analysis_run_id"))
    write_mart_metric_facts(pl.concat([_facts(), duplicate_analysis]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    with pytest.raises(ValueError, match="Duplicate mart fact contributors"):
        service.query(_request(PeriodMode.SINGLE_PERIOD, date(2025, 1, 1), date(2025, 1, 1)))


def test_partial_active_revision_map_is_enforced_per_period(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    active_for_jan_only = _ledger("revision_a", active=True, active_periods=("2025-01",))
    service = DashboardMartQueryService(
        path,
        mart_builds=(_build(),),
        source_ledger=(active_for_jan_only,),
    )

    with pytest.raises(ValueError, match="inactive source revisions for active periods"):
        service.query(
            _request(
                PeriodMode.DATE_RANGE,
                date(2025, 1, 1),
                date(2025, 4, 1),
                metric_concepts=("revenue",),
            )
        )


def test_same_concept_different_definition_stays_separate(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    changed_definition = _facts(metric_suffix="v2").with_columns(
        pl.lit("v2").alias("metric_definition_version"),
        pl.lit("hash_b").alias("metric_config_hash"),
    )
    write_mart_metric_facts(pl.concat([_facts(), changed_definition]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("revenue",),
        )
    )

    assert len(response.metric_results) == 2
    assert {result.lineage.metric_definition_version for result in response.metric_results if result.lineage} == {
        "v1",
        "v2",
    }


def test_yoy_comparison_uses_same_calendar_month(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(pl.concat([_facts(periods=(date(2025, 1, 1),)), _facts(periods=(date(2026, 1, 1),))]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        _request(
            PeriodMode.SINGLE_PERIOD,
            date(2026, 1, 1),
            date(2026, 1, 1),
            metric_concepts=("revenue",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert response.comparisons[0].comparison_period_start == date(2025, 1, 1)
    assert response.comparisons[0].quality_status == "HIGH"
    assert response.comparisons[0].private_label_scope == PrivateLabelScope.INCLUDE


def test_comparison_works_when_lineage_is_omitted(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(pl.concat([_facts(periods=(date(2025, 1, 1),)), _facts(periods=(date(2026, 1, 1),))]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        _request(
            PeriodMode.SINGLE_PERIOD,
            date(2026, 1, 1),
            date(2026, 1, 1),
            metric_concepts=("revenue",),
            include_lineage=False,
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert response.comparisons[0].comparison_period_start == date(2025, 1, 1)


def test_comparison_scope_rejects_duplicate_contributors(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    base = pl.concat([_facts(periods=(date(2025, 1, 1),)), _facts(periods=(date(2026, 1, 1),))])
    duplicate_base_period = _facts(periods=(date(2025, 1, 1),)).with_columns(
        pl.lit("analysis_b").alias("analysis_run_id")
    )
    write_mart_metric_facts(pl.concat([base, duplicate_base_period]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    with pytest.raises(ValueError, match="Duplicate mart fact contributors"):
        service.query(
            _request(
                PeriodMode.SINGLE_PERIOD,
                date(2026, 1, 1),
                date(2026, 1, 1),
                metric_concepts=("revenue",),
                comparison_mode=ComparisonMode.YOY,
            )
        )


def test_mom_requires_contiguous_previous_month(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(periods=(date(2025, 1, 1), date(2025, 3, 1))), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2025, 3, 31)),))

    response = service.query(
        _request(
            PeriodMode.SINGLE_PERIOD,
            date(2025, 3, 1),
            date(2025, 3, 1),
            metric_concepts=("revenue",),
            comparison_mode=ComparisonMode.MOM,
        )
    )

    assert response.comparisons == ()
    assert "comparison_period_missing" in {item.issue_code for item in response.limitations}


def test_previous_available_allows_gap_with_metadata(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(periods=(date(2025, 1, 1), date(2025, 4, 1))), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2025, 4, 30)),))

    response = service.query(
        _request(
            PeriodMode.SINGLE_PERIOD,
            date(2025, 4, 1),
            date(2025, 4, 1),
            metric_concepts=("revenue",),
            comparison_mode=ComparisonMode.PREVIOUS_AVAILABLE,
        )
    )

    assert response.comparisons[0].comparison_period_start == date(2025, 1, 1)
    assert response.comparisons[0].gap_periods == 3
    assert response.comparisons[0].quality_status == "MEDIUM"


def test_range_comparison_returns_limitation(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.DATE_RANGE,
            date(2025, 1, 1),
            date(2025, 4, 1),
            metric_concepts=("revenue",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert "range_comparison_unsupported" in {item.issue_code for item in response.limitations}


def test_private_label_scope_filters_materialized_facts(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    include = _facts()
    exclude = _facts(private_label_scope=PrivateLabelScope.EXCLUDE).with_columns(
        pl.when(pl.col("metric_concept") == "revenue")
        .then(pl.lit(60.0))
        .otherwise(pl.col("value"))
        .alias("value")
    )
    only = _facts(private_label_scope=PrivateLabelScope.ONLY).with_columns(
        pl.when(pl.col("metric_concept") == "revenue")
        .then(pl.lit(40.0))
        .otherwise(pl.col("value"))
        .alias("value")
    )
    write_mart_metric_facts(pl.concat([include, exclude, only]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.SINGLE_PERIOD,
            date(2025, 1, 1),
            date(2025, 1, 1),
            metric_concepts=("revenue",),
            private_label_scope=PrivateLabelScope.EXCLUDE,
        )
    )

    assert response.private_label_scope == PrivateLabelScope.EXCLUDE
    assert response.metric_results[0].value == 60.0


def test_private_label_scope_applies_to_comparison_periods(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    include = pl.concat([_facts(periods=(date(2025, 1, 1),)), _facts(periods=(date(2026, 1, 1),))])
    exclude = pl.concat(
        [
            _facts(periods=(date(2025, 1, 1),), private_label_scope=PrivateLabelScope.EXCLUDE),
            _facts(periods=(date(2026, 1, 1),), private_label_scope=PrivateLabelScope.EXCLUDE),
        ]
    ).with_columns(
        pl.when((pl.col("metric_concept") == "revenue") & (pl.col("period_start") == date(2025, 1, 1)))
        .then(pl.lit(60.0))
        .when((pl.col("metric_concept") == "revenue") & (pl.col("period_start") == date(2026, 1, 1)))
        .then(pl.lit(90.0))
        .otherwise(pl.col("value"))
        .alias("value")
    )
    write_mart_metric_facts(pl.concat([include, exclude]), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        _request(
            PeriodMode.SINGLE_PERIOD,
            date(2026, 1, 1),
            date(2026, 1, 1),
            metric_concepts=("revenue",),
            comparison_mode=ComparisonMode.YOY,
            private_label_scope=PrivateLabelScope.EXCLUDE,
        )
    )

    assert response.comparisons[0].private_label_scope == PrivateLabelScope.EXCLUDE
    assert response.comparisons[0].current_value == 90.0
    assert response.comparisons[0].comparison_value == 60.0


def test_non_include_scope_on_unscoped_facts_returns_limitation(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = _facts().drop("private_label_scope")
    facts.write_parquet(path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        _request(
            PeriodMode.SINGLE_PERIOD,
            date(2025, 1, 1),
            date(2025, 1, 1),
            metric_concepts=("revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    assert response.metric_results == ()
    assert "private_label_scope_not_materialized" in {item.issue_code for item in response.limitations}


def test_filtered_network_query_rolls_up_single_category_scope(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A",)},
            metric_concepts=("revenue", "retailer_margin_pct"),
            comparison_mode=ComparisonMode.YOY,
            mart_build_id="build_a",
        )
    )

    values = {result.metric_concept: result.value for result in response.metric_results}
    assert values["revenue"] == pytest.approx(40.0)
    assert values["retailer_margin_pct"] == pytest.approx(0.25)
    assert {item.entity_id for item in response.metric_results} == {"ALL"}
    assert response.request_scope["entity_filters"] == {"category": ("CATEGORY_A",)}
    assert {comparison.current_value for comparison in response.comparisons} >= {40.0, 0.25}


def test_filtered_network_query_uses_or_within_filter_and_rolls_up_safe_metrics(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A", "CATEGORY_B")},
            metric_concepts=("revenue", "retailer_margin_pct", "distribution"),
            mart_build_id="build_a",
        )
    )

    values = {result.metric_concept: result.value for result in response.metric_results}
    assert values["revenue"] == pytest.approx(100.0)
    assert values["retailer_margin_pct"] == pytest.approx(0.25)
    assert "distribution" not in values
    assert "scoped_filter_rollup_not_supported_for_metric" in {
        item.issue_code for item in response.limitations
    }


def test_filtered_network_query_uses_and_across_cascading_filters(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A",), "manufacturer": ("MANUFACTURER_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert len(response.metric_results) == 1
    assert response.metric_results[0].value == pytest.approx(30.0)


def test_filtered_query_requires_canonical_filter_ids_not_display_labels(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    canonical = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )
    label = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("Category A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert canonical.metric_results
    assert label.metric_results == ()


def test_product_store_serving_filter_maps_sku_to_canonical_product_id(tmp_path) -> None:
    facts_path, product_store_path = _write_product_store_query_inputs(tmp_path)
    service = DashboardMartQueryService(
        facts_path,
        mart_builds=(_build(period_end=date(2026, 1, 31)),),
        product_store_facts_path=product_store_path,
    )

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="store",
            entity_filters={"sku": ("SKU_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert [result.entity_id for result in response.metric_results] == ["STORE_A", "STORE_B"]
    assert {result.entity_id: result.value for result in response.metric_results} == {
        "STORE_A": pytest.approx(10.0),
        "STORE_B": pytest.approx(40.0),
    }

def test_product_store_filter_intersection_returns_explicit_limitation(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A",), "store": ("STORE_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert response.metric_results == ()
    assert "product_store_filter_intersection_not_materialized" in {
        item.issue_code for item in response.limitations
    }


def test_requested_product_grain_with_store_filter_returns_explicit_limitation(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = pl.DataFrame(
        [
            _entity_fact(
                date(2026, 1, 1),
                "store",
                "STORE_A",
                "revenue",
                1260.0,
                "sum",
            )
        ],
        schema=MART_METRIC_FACT_SCHEMA,
    )
    write_mart_metric_facts(facts, path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="sku",
            entity_ids=("SKU_A",),
            entity_filters={"store": ("STORE_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert response.metric_results == ()
    assert "product_store_filter_intersection_not_materialized" in {
        item.issue_code for item in response.limitations
    }


def test_requested_all_product_grain_with_store_filter_returns_explicit_limitation(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = pl.DataFrame(
        [
            _entity_fact(
                date(2026, 1, 1),
                "store",
                "STORE_A",
                "revenue",
                1260.0,
                "sum",
            )
        ],
        schema=MART_METRIC_FACT_SCHEMA,
    )
    write_mart_metric_facts(facts, path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="sku",
            entity_filters={"store": ("STORE_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert response.metric_results == ()
    assert "product_store_filter_intersection_not_materialized" in {
        item.issue_code for item in response.limitations
    }


def test_existing_product_fact_with_store_parent_filter_is_rejected_before_direct_read(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = pl.DataFrame(
        [
            _entity_fact(
                date(2026, 1, 1),
                "sku",
                "SKU_A",
                "revenue",
                1260.0,
                "sum",
                parent_entity_ids='{"canonical_store_id":"STORE_A"}',
            )
        ],
        schema=MART_METRIC_FACT_SCHEMA,
    )
    write_mart_metric_facts(facts, path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="sku",
            entity_ids=("SKU_A",),
            entity_filters={"store": ("STORE_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert response.metric_results == ()
    assert "product_store_filter_intersection_not_materialized" in {
        item.issue_code for item in response.limitations
    }


def test_product_store_intersection_rolls_up_category_and_store_filters(tmp_path) -> None:
    facts_path = tmp_path / "facts.parquet"
    product_store_path = tmp_path / "product_store.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), facts_path)
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            _product_store_source_rows(),
            build_metadata=_build(period_end=date(2026, 1, 31)),
            source_revision_id="revision_a",
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    service = DashboardMartQueryService(
        facts_path,
        mart_builds=(_build(period_end=date(2026, 1, 31)),),
        product_store_facts_path=product_store_path,
    )

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A",), "store": ("STORE_A",)},
            metric_concepts=("revenue", "retailer_margin_pct", "distribution"),
            comparison_mode=ComparisonMode.YOY,
            mart_build_id="build_a",
        )
    )

    values = {result.metric_concept: result.value for result in response.metric_results}
    assert values["revenue"] == pytest.approx(30.0)
    assert values["retailer_margin_pct"] == pytest.approx(6.0 / 30.0)
    assert "distribution" not in values
    assert "product_store_intersection_not_supported_for_metric" in {
        item.issue_code for item in response.limitations
    }
    assert response.comparisons
    provenance = _require_provenance(response.metric_results[0]).payload
    assert provenance["scoped_rollup"]["status"] == "DERIVED_FROM_PRODUCT_STORE_FACTS"
    assert provenance["scoped_rollup"]["source_fact_grain"] == "sku_store"
    assert provenance["current_analytical_scope"]["entity_filters"] == {
        "category": ("CATEGORY_A",),
        "store": ("STORE_A",),
    }


def test_product_store_intersection_respects_package_and_volume_filters(tmp_path) -> None:
    facts_path = tmp_path / "facts.parquet"
    product_store_path = tmp_path / "product_store.parquet"
    source_rows = _product_store_source_rows().with_columns(
        pl.when(pl.col("canonical_product_id") == "SKU_A")
        .then(pl.lit("пэт"))
        .when(pl.col("canonical_product_id") == "SKU_B")
        .then(pl.lit("ж/б"))
        .otherwise(pl.lit("ст/б"))
        .alias("package"),
        pl.when(pl.col("canonical_product_id") == "SKU_A")
        .then(pl.lit(1.0))
        .when(pl.col("canonical_product_id") == "SKU_B")
        .then(pl.lit(0.5))
        .otherwise(pl.lit(1.5))
        .alias("volume_l"),
    )
    write_mart_metric_facts(_filtered_scope_facts(), facts_path)
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            source_rows,
            build_metadata=_build(period_end=date(2026, 1, 31)),
            source_revision_id="revision_a",
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    service = DashboardMartQueryService(
        facts_path,
        mart_builds=(_build(period_end=date(2026, 1, 31)),),
        product_store_facts_path=product_store_path,
    )

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A",), "package": ("пэт",), "volume": ("1",)},
            metric_concepts=("revenue", "units", "weighted_shelf_price_vat"),
            mart_build_id="build_a",
        )
    )

    values = {result.metric_concept: result for result in response.metric_results}
    assert values["revenue"].value == pytest.approx(50.0)
    assert values["units"].value == pytest.approx(5.0)
    assert values["weighted_shelf_price_vat"].value == pytest.approx(12.0)
    provenance = _require_provenance(values["revenue"]).payload
    assert provenance["scoped_rollup"]["status"] == "DERIVED_FROM_PRODUCT_STORE_FACTS"
    assert provenance["current_analytical_scope"]["entity_filters"] == {
        "category": ("CATEGORY_A",),
        "package": ("пэт",),
        "volume": ("1",),
    }



def test_product_store_sql_rollup_matches_legacy_polars_rollup_for_package_scope(tmp_path) -> None:
    facts_path = tmp_path / "facts.parquet"
    product_store_path = tmp_path / "product_store.parquet"
    source_rows = _product_store_source_rows().with_columns(
        pl.when(pl.col("canonical_product_id") == "SKU_A")
        .then(pl.lit("пэт"))
        .when(pl.col("canonical_product_id") == "SKU_B")
        .then(pl.lit("ж/б"))
        .otherwise(pl.lit("ст/б"))
        .alias("package"),
        pl.when(pl.col("canonical_product_id") == "SKU_A")
        .then(pl.lit(1.0))
        .when(pl.col("canonical_product_id") == "SKU_B")
        .then(pl.lit(0.5))
        .otherwise(pl.lit(1.5))
        .alias("volume_l"),
    )
    write_mart_metric_facts(_filtered_scope_facts(), facts_path)
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            source_rows,
            build_metadata=_build(period_end=date(2026, 1, 31)),
            source_revision_id="revision_a",
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    service = DashboardMartQueryService(
        facts_path,
        mart_builds=(_build(period_end=date(2026, 1, 31)),),
        product_store_facts_path=product_store_path,
    )
    request = DashboardMetricQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 1),
        period_mode=PeriodMode.SINGLE_PERIOD,
        period_grain="month",
        grain_id="network",
        entity_ids=("ALL",),
        entity_filters={"category": ("CATEGORY_A",), "package": ("пэт",), "volume": ("1",)},
        metric_concepts=("revenue", "units", "retailer_margin_pct", "weighted_shelf_price_vat"),
        mart_build_id="build_a",
    )
    clauses = [
        "retailer_id = ?",
        "source_id = ?",
        "period_grain = ?",
        "mart_build_id = ?",
        "private_label_scope = ?",
        "period_start >= CAST(? AS DATE)",
        "period_start <= CAST(? AS DATE)",
        "metric_concept IN (?, ?, ?, ?)",
        "category IN (?)",
        "package IN (?)",
        "ROUND(CAST(volume_l AS DOUBLE), 6) IN (?)",
    ]
    params = [
        "retailer_a",
        "source_a",
        "month",
        "build_a",
        "INCLUDE",
        "2026-01-01",
        "2026-01-01",
        "revenue",
        "units",
        "retailer_margin_pct",
        "weighted_shelf_price_vat",
        "CATEGORY_A",
        "пэт",
        1.0,
    ]
    templates = service._metric_templates(request, "build_a")
    raw = pl.read_parquet(product_store_path).filter(
        (pl.col("retailer_id") == "retailer_a")
        & (pl.col("source_id") == "source_a")
        & (pl.col("period_grain") == "month")
        & (pl.col("mart_build_id") == "build_a")
        & (pl.col("private_label_scope") == "INCLUDE")
        & (pl.col("period_start") >= date(2026, 1, 1))
        & (pl.col("period_start") <= date(2026, 1, 1))
        & pl.col("metric_concept").is_in(request.metric_concepts)
        & (pl.col("category") == "CATEGORY_A")
        & (pl.col("package") == "пэт")
        & (pl.col("volume_l").round(6) == 1.0)
    )

    legacy = _roll_up_product_store_facts(raw, request, templates)
    optimized = _read_product_store_rollup_facts_from_sql(product_store_path, clauses, params, request, templates)

    columns = ["period_start", "grain_id", "entity_id", "parent_entity_ids", "metric_concept", "value", "numerator_value", "denominator_value", "quality_status", "quality_flags"]
    assert optimized.select(columns).sort(columns[:5]).to_dicts() == legacy.select(columns).sort(columns[:5]).to_dicts()


def test_product_store_intersection_supports_sku_grain_with_store_filter(tmp_path) -> None:
    facts_path, product_store_path = _write_product_store_query_inputs(tmp_path)
    service = DashboardMartQueryService(
        facts_path,
        mart_builds=(_build(period_end=date(2026, 1, 31)),),
        product_store_facts_path=product_store_path,
    )

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="sku",
            entity_filters={"store": ("STORE_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    values = {result.entity_id: result.value for result in response.metric_results}
    assert values == {"SKU_A": pytest.approx(10.0), "SKU_B": pytest.approx(20.0), "SKU_C": pytest.approx(50.0)}


def test_product_store_intersection_supports_store_grain_with_product_filter(tmp_path) -> None:
    facts_path, product_store_path = _write_product_store_query_inputs(tmp_path)
    service = DashboardMartQueryService(
        facts_path,
        mart_builds=(_build(period_end=date(2026, 1, 31)),),
        product_store_facts_path=product_store_path,
    )

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="store",
            entity_filters={"category": ("CATEGORY_A",)},
            metric_concepts=("revenue", "units"),
            mart_build_id="build_a",
        )
    )

    revenue = {result.entity_id: result.value for result in response.metric_results if result.metric_concept == "revenue"}
    units = {result.entity_id: result.value for result in response.metric_results if result.metric_concept == "units"}
    assert revenue == {"STORE_A": pytest.approx(30.0), "STORE_B": pytest.approx(40.0)}
    assert units == {"STORE_A": pytest.approx(3.0), "STORE_B": pytest.approx(4.0)}



def test_product_store_intersection_empty_scope_has_explicit_no_data_limitation(tmp_path) -> None:
    facts_path, product_store_path = _write_product_store_query_inputs(tmp_path)
    service = DashboardMartQueryService(
        facts_path,
        mart_builds=(_build(period_end=date(2026, 1, 31)),),
        product_store_facts_path=product_store_path,
    )

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"manufacturer": ("MISSING_MANUFACTURER",), "store": ("STORE_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert response.metric_results == ()
    assert "product_store_intersection_no_data" in {item.issue_code for item in response.limitations}


def test_product_store_builder_rejects_mixed_source_revisions() -> None:
    rows = _product_store_source_rows().with_columns(
        pl.when(pl.arange(0, pl.len()) == 0)
        .then(pl.lit("revision_a"))
        .otherwise(pl.lit("revision_b"))
        .alias("source_revision_id")
    )

    with pytest.raises(ValueError, match="one source_revision_id"):
        build_product_store_metric_facts(rows, build_metadata=_build(period_end=date(2026, 1, 31)))


def test_product_store_intersection_supports_private_label_scope(tmp_path) -> None:
    facts_path = tmp_path / "facts.parquet"
    product_store_path = tmp_path / "product_store.parquet"
    write_mart_metric_facts(
        pl.concat(
            [
                _filtered_scope_facts(),
                _filtered_scope_facts().with_columns(pl.lit("EXCLUDE").alias("private_label_scope")),
            ]
        ),
        facts_path,
    )
    build = _build(period_end=date(2026, 1, 31))
    frames = [
        build_product_store_metric_facts(
            _product_store_source_rows(),
            build_metadata=build,
            source_revision_id="revision_a",
            private_label_scope=scope,
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        )
        for scope in (PrivateLabelScope.INCLUDE, PrivateLabelScope.EXCLUDE, PrivateLabelScope.ONLY)
    ]
    write_product_store_metric_facts(pl.concat(frames), product_store_path)
    service = DashboardMartQueryService(
        facts_path,
        mart_builds=(build,),
        product_store_facts_path=product_store_path,
    )

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A",), "store": ("STORE_A",)},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
            private_label_scope=PrivateLabelScope.EXCLUDE,
        )
    )

    assert response.metric_results[0].value == pytest.approx(10.0)
    assert response.private_label_scope == PrivateLabelScope.EXCLUDE


def test_scoped_rollup_preserves_empty_metric_concepts_as_all_safe_metrics(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A", "CATEGORY_B")},
            mart_build_id="build_a",
        )
    )

    assert {result.metric_concept for result in response.metric_results} == {
        "revenue",
        "retailer_margin_pct",
    }


def test_scoped_rollup_does_not_reinterpret_explicit_definition_ids(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A",)},
            metric_definition_ids=("retailer_a.network.revenue.v1",),
            mart_build_id="build_a",
        )
    )

    assert response.metric_results == ()
    assert "scoped_filter_rollup_not_supported_for_metric_definition_id" in {
        item.issue_code for item in response.limitations
    }


def test_scoped_rollup_aggregates_mixed_quality_metadata(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = _filtered_scope_facts().with_columns(
        pl.when(pl.col("entity_id") == "CATEGORY_B")
        .then(pl.lit("warning"))
        .otherwise(pl.col("quality_status"))
        .alias("quality_status"),
        pl.when(pl.col("entity_id") == "CATEGORY_A")
        .then(pl.lit("flag_a"))
        .when(pl.col("entity_id") == "CATEGORY_B")
        .then(pl.lit("flag_b"))
        .otherwise(pl.col("quality_flags"))
        .alias("quality_flags"),
    )
    write_mart_metric_facts(facts, path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_ids=("ALL",),
            entity_filters={"category": ("CATEGORY_A", "CATEGORY_B")},
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert len(response.metric_results) == 1
    assert response.metric_results[0].value == pytest.approx(100.0)
    assert response.metric_results[0].period_values[0].quality_status == "mixed"
    assert response.metric_results[0].period_values[0].quality_flags == "flag_a,flag_b"


def test_filtered_scope_hash_and_provenance_include_entity_filters(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), path)
    service = DashboardMartQueryService(path, mart_builds=(_build(period_end=date(2026, 1, 31)),))
    base_request = DashboardMetricQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 1),
        period_mode=PeriodMode.SINGLE_PERIOD,
        period_grain="month",
        grain_id="network",
        entity_ids=("ALL",),
        metric_concepts=("revenue",),
        mart_build_id="build_a",
    )

    unfiltered = service.query(base_request)
    filtered = service.query(
        replace(base_request, entity_filters={"category": ("CATEGORY_A",)})
    )

    assert unfiltered.scope_identity_hash != filtered.scope_identity_hash
    provenance = filtered.metric_results[0].provenance
    assert provenance is not None
    assert provenance.payload["current_analytical_scope"]["entity_filters"] == {
        "category": ("CATEGORY_A",)
    }
    assert provenance.payload["scoped_rollup"]["status"] == "DERIVED_FROM_FILTERED_FACTS"
    assert provenance.payload["scoped_rollup"]["source_fact_grain"] == "category"


def test_invalid_private_label_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="UNKNOWN"):
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            private_label_scope=cast(Any, "UNKNOWN"),
        )


def test_unsupported_period_grain_gets_explicit_limitation(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = _facts().with_columns(pl.lit("week").alias("period_grain"))
    write_mart_metric_facts(facts, path)
    service = DashboardMartQueryService(path, mart_builds=(_build(),))

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 4, 1),
            period_mode=PeriodMode.DATE_RANGE,
            period_grain="week",
            grain_id="network",
            metric_concepts=("revenue",),
            mart_build_id="build_a",
        )
    )

    assert response.coverage_status == CoverageStatus.UNSUPPORTED
    assert "coverage_period_grain_unsupported" in {item.issue_code for item in response.limitations}


def _require_provenance(result: MetricQueryResult) -> MetricProvenanceTrace:
    provenance = result.provenance
    assert provenance is not None
    return provenance


def _request(
    mode: PeriodMode,
    start: date,
    end: date,
    *,
    metric_concepts: tuple[str, ...] = (),
    include_lineage: bool = True,
    comparison_mode: ComparisonMode = ComparisonMode.NONE,
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
) -> DashboardMetricQueryRequest:
    return DashboardMetricQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=start,
        date_to=end,
        period_mode=mode,
        period_grain="month",
        grain_id="network",
        metric_concepts=metric_concepts,
        include_lineage=include_lineage,
        comparison_mode=comparison_mode,
        private_label_scope=private_label_scope,
    )


def _build(
    build_id: str = "build_a",
    retailer_id: str = "retailer_a",
    *,
    status: MartBuildStatus = MartBuildStatus.APPROVED,
    period_end: date = date(2025, 4, 30),
) -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id=build_id,
        built_at=datetime(2026, 1, 15, tzinfo=UTC),
        build_version="mart.v1",
        code_version="test",
        retailer_id=retailer_id,
        source_ids=("source_a",),
        source_revision_ids=("revision_a",),
        analysis_run_ids=("analysis_a", "analysis_b"),
        metric_config_hashes=("hash_a", "hash_b"),
        rule_versions=("rules_v1",),
        status=status,
        period_grain="month",
        period_start=date(2025, 1, 1),
        period_end=period_end,
    )


def _facts(
    *,
    retailer_id: str = "retailer_a",
    build_id: str = "build_a",
    periods: tuple[date, ...] = (date(2025, 1, 1), date(2025, 2, 1), date(2025, 4, 1)),
    include_share: bool = False,
    include_velocity: bool = False,
    metric_suffix: str = "v1",
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    revenue_values = {
        date(2025, 1, 1): 100.0,
        date(2025, 2, 1): 200.0,
        date(2025, 3, 1): 300.0,
        date(2025, 4, 1): 100.0,
        date(2026, 1, 1): 150.0,
    }
    margin_num = {
        date(2025, 1, 1): 25.0,
        date(2025, 2, 1): 100.0,
        date(2025, 3, 1): 75.0,
        date(2025, 4, 1): -25.0,
        date(2026, 1, 1): 30.0,
    }
    weighted_num = {
        date(2025, 1, 1): 100.0,
        date(2025, 2, 1): 360.0,
        date(2025, 3, 1): 600.0,
        date(2025, 4, 1): 350.0,
        date(2026, 1, 1): 180.0,
    }
    weights = {
        date(2025, 1, 1): 10.0,
        date(2025, 2, 1): 30.0,
        date(2025, 3, 1): 50.0,
        date(2025, 4, 1): 40.0,
        date(2026, 1, 1): 15.0,
    }
    for period in periods:
        rows.extend(
            [
                _fact(
                    period,
                    "revenue",
                    revenue_values[period],
                    "sum",
                    build_id,
                    retailer_id,
                    metric_suffix=metric_suffix,
                    private_label_scope=private_label_scope,
                ),
                _fact(
                    period,
                    "retailer_margin_pct",
                    margin_num[period] / revenue_values[period],
                    "ratio_of_sums",
                    build_id,
                    retailer_id,
                    numerator=margin_num[period],
                    denominator=revenue_values[period],
                    metric_suffix=metric_suffix,
                    private_label_scope=private_label_scope,
                ),
                _fact(
                    period,
                    "weighted_shelf_price_vat",
                    weighted_num[period] / weights[period],
                    "weighted_average",
                    build_id,
                    retailer_id,
                    numerator=weighted_num[period],
                    denominator=weights[period],
                    metric_suffix=metric_suffix,
                    private_label_scope=private_label_scope,
                ),
                _fact(
                    period,
                    "distribution",
                    0.5,
                    "ratio_of_sums",
                    build_id,
                    retailer_id,
                    numerator=5.0,
                    denominator=10.0,
                    strategy=RangeAggregationStrategy.PERIOD_ONLY,
                    metric_suffix=metric_suffix,
                    private_label_scope=private_label_scope,
                ),
            ]
        )
        if include_share:
            rows.append(
                _fact(
                    period,
                    "category_revenue_share",
                    revenue_values[period] / 1000.0,
                    "share",
                    build_id,
                    retailer_id,
                    numerator=revenue_values[period],
                    denominator=1000.0 / len(periods),
                    share_scope="network",
                    strategy=RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
                    metric_suffix=metric_suffix,
                    private_label_scope=private_label_scope,
                )
            )
        if include_velocity:
            rows.append(
                _fact(
                    period,
                    "velocity",
                    12.0,
                    "ratio_of_sums",
                    build_id,
                    retailer_id,
                    numerator=120.0,
                    denominator=10.0,
                    strategy=RangeAggregationStrategy.PERIOD_ONLY,
                    metric_suffix=metric_suffix,
                    private_label_scope=private_label_scope,
                )
            )
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)


def _fact(
    period: date,
    concept: str,
    value: float,
    aggregation: str,
    build_id: str,
    retailer_id: str,
    *,
    numerator: float | None = None,
    denominator: float | None = None,
    share_scope: str | None = None,
    strategy: RangeAggregationStrategy | None = None,
    metric_suffix: str = "v1",
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
) -> dict[str, object]:
    actual_strategy = strategy or {
        "sum": RangeAggregationStrategy.SUM_AVAILABLE_PERIODS,
        "ratio_of_sums": RangeAggregationStrategy.RATIO_OF_SUMS,
        "weighted_average": RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
        "share": RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
    }[aggregation]
    return {
        "retailer_id": retailer_id,
        "source_id": "source_a",
        "source_revision_id": "revision_a",
        "analysis_run_id": "analysis_a",
        "mart_build_id": build_id,
        "private_label_scope": private_label_scope.value,
        "period_grain": "month",
        "period_start": period,
        "period_end": date(period.year, period.month, 28),
        "business_period_id": period.strftime("%Y-%m"),
        "grain_id": "network",
        "entity_id": "network",
        "parent_entity_ids": "{}",
        "metric_concept": concept,
        "metric_name": concept,
        "metric_definition_id": f"{retailer_id}.network.{concept}.{metric_suffix}",
        "metric_definition_version": metric_suffix,
        "metric_config_hash": "hash_a" if metric_suffix == "v1" else "hash_b",
        "semantic_family": concept,
        "semantic_compatibility_version": "v1",
        "cross_retailer_comparable": False,
        "value": value,
        "numerator_value": numerator,
        "denominator_value": denominator,
        "aggregation": aggregation,
        "range_aggregation_strategy": actual_strategy,
        "share_scope": share_scope,
        "rule_version": "rules_v1",
        "quality_status": "valid",
        "quality_flags": None,
        "created_at": datetime(2026, 1, 15, tzinfo=UTC),
    }


def _filtered_scope_facts() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for period, factor in ((date(2025, 1, 1), 0.5), (date(2026, 1, 1), 1.0)):
        rows.extend(
            [
                _entity_fact(
                    period,
                    "category",
                    "CATEGORY_A",
                    "revenue",
                    40.0 * factor,
                    "sum",
                ),
                _entity_fact(
                    period,
                    "category",
                    "CATEGORY_A",
                    "retailer_margin_pct",
                    0.25,
                    "ratio_of_sums",
                    numerator=10.0 * factor,
                    denominator=40.0 * factor,
                ),
                _entity_fact(
                    period,
                    "category",
                    "CATEGORY_B",
                    "revenue",
                    60.0 * factor,
                    "sum",
                ),
                _entity_fact(
                    period,
                    "category",
                    "CATEGORY_B",
                    "retailer_margin_pct",
                    0.25,
                    "ratio_of_sums",
                    numerator=15.0 * factor,
                    denominator=60.0 * factor,
                ),
                _entity_fact(
                    period,
                    "category",
                    "CATEGORY_A",
                    "distribution",
                    0.5,
                    "ratio_of_sums",
                    numerator=5.0,
                    denominator=10.0,
                    strategy=RangeAggregationStrategy.PERIOD_ONLY,
                ),
                _entity_fact(
                    period,
                    "category",
                    "CATEGORY_B",
                    "distribution",
                    0.4,
                    "ratio_of_sums",
                    numerator=4.0,
                    denominator=10.0,
                    strategy=RangeAggregationStrategy.PERIOD_ONLY,
                ),
                _entity_fact(
                    period,
                    "manufacturer",
                    "MANUFACTURER_A",
                    "revenue",
                    30.0 * factor,
                    "sum",
                    parent_entity_ids='{"category":"CATEGORY_A"}',
                ),
                _entity_fact(
                    period,
                    "manufacturer",
                    "MANUFACTURER_B",
                    "revenue",
                    70.0 * factor,
                    "sum",
                    parent_entity_ids='{"category":"CATEGORY_B"}',
                ),
            ]
        )
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)


def _entity_fact(
    period: date,
    grain: str,
    entity_id: str,
    concept: str,
    value: float,
    aggregation: str,
    *,
    numerator: float | None = None,
    denominator: float | None = None,
    parent_entity_ids: str = "{}",
    strategy: RangeAggregationStrategy | None = None,
) -> dict[str, object]:
    row = _fact(
        period,
        concept,
        value,
        aggregation,
        "build_a",
        "retailer_a",
        numerator=numerator,
        denominator=denominator,
        strategy=strategy,
    )
    row["grain_id"] = grain
    row["entity_id"] = entity_id
    row["parent_entity_ids"] = parent_entity_ids
    row["metric_definition_id"] = f"retailer_a.{grain}.{concept}.v1"
    return row


def _ledger(
    revision: str,
    *,
    active: bool,
    active_periods: tuple[str, ...] = ("2025-01", "2025-02", "2025-04"),
) -> SourceLedgerEntry:
    return SourceLedgerEntry(
        source_revision_id=revision,
        source_artifact_id=source_artifact_id("retailer_a", "source_a", f"hash_{revision}"),
        retailer_id="retailer_a",
        source_id="source_a",
        source_type="monthly_workbook",
        source_version="v1",
        source_file_id="source.xlsx",
        source_hash=f"hash_{revision}",
        raw_object_key="private/source/source.xlsx",
        size_bytes=100,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        registered_at=datetime(2026, 1, 2, tzinfo=UTC),
        period_grain=PeriodGrain.MONTH,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 4, 30),
        observed_periods=(date(2025, 1, 1), date(2025, 2, 1), date(2025, 4, 1)),
        business_period_ids=("2025-01", "2025-02", "2025-04"),
        active_business_period_ids=active_periods if active else (),
        source_schema_version="schema_v1",
        mapping_config_hash="mapping_hash",
        rule_package_hash="rule_hash",
        revision_state="active" if active else "candidate",
        is_active_revision=active,
    )


def _write_product_store_query_inputs(tmp_path) -> tuple[Any, Any]:
    facts_path = tmp_path / "facts.parquet"
    product_store_path = tmp_path / "product_store.parquet"
    write_mart_metric_facts(_filtered_scope_facts(), facts_path)
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            _product_store_source_rows(),
            build_metadata=_build(period_end=date(2026, 1, 31)),
            source_revision_id="revision_a",
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    return facts_path, product_store_path


def _product_store_source_rows() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    specs = (
        (date(2025, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_A", 2.0, 20.0, 4.0, False),
        (date(2025, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_B", "SKU_B", "STORE_A", 1.0, 10.0, 2.0, True),
        (date(2025, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_B", 3.0, 30.0, 6.0, False),
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_A", 1.0, 10.0, 2.0, False),
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_B", "SKU_B", "STORE_A", 2.0, 20.0, 4.0, True),
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_B", 4.0, 40.0, 8.0, False),
        (date(2026, 1, 1), "CATEGORY_B", "MANUFACTURER_B", "BRAND_C", "SKU_C", "STORE_A", 5.0, 50.0, 10.0, False),
    )
    for idx, (period, category, manufacturer, brand, sku, store, units, revenue, margin, is_private_label) in enumerate(specs, start=1):
        rows.append(
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "analysis_run_id": "analysis_a",
                "period": period,
                "category": category,
                "manufacturer": manufacturer,
                "brand": brand,
                "canonical_product_id": sku,
                "canonical_store_id": store,
                "sku_name": f"{sku} name",
                "units": units,
                "revenue_vat": revenue * 1.2,
                "revenue_net": revenue,
                "retailer_margin_abs": margin,
                "shelf_price_vat": 12.0,
                "input_price_vat": 8.0,
                "private_label_flag": is_private_label,
                "source_row_number": idx,
                "store_format": "format_a",
                "region": "region_a",
            }
        )
    return pl.DataFrame(rows)
