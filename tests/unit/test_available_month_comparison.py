from __future__ import annotations

import json
from datetime import UTC, date, datetime

import polars as pl
import pytest

from retail_analytics.mart import (
    ComparisonMode,
    DashboardMartQueryService,
    DashboardMetricQueryRequest,
    MartBuildMetadata,
    MartBuildStatus,
    PeriodMode,
    PortfolioConceptStatus,
    PortfolioMarketQueryRequest,
    PortfolioMarketService,
    PrivateLabelScope,
    RangeAggregationStrategy,
    write_mart_metric_facts,
)
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA


def test_available_month_set_compares_matched_months_and_sums_additive_totals(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts())

    response = service.query(_request(("revenue",), comparison_mode=ComparisonMode.YOY))

    revenue = _result(response, "revenue")
    assert revenue.value == pytest.approx(300.0 + 600.0 + 900.0)
    assert revenue.numerator_value is None
    assert revenue.denominator_value is None
    assert response.available_periods == (date(2026, 3, 1), date(2026, 4, 1), date(2026, 6, 1))
    comparison = response.comparisons[0]
    assert comparison.comparison_value == pytest.approx(100.0 + 200.0 + 300.0)
    assert comparison.current_included_periods == (date(2026, 3, 1), date(2026, 4, 1), date(2026, 6, 1))
    assert comparison.comparison_included_periods == (date(2025, 3, 1), date(2025, 4, 1), date(2025, 6, 1))
    assert comparison.comparison_policy == "MATCHED_AVAILABLE_MONTHS"
    provenance = revenue.provenance.payload
    assert provenance["current_analytical_scope"]["period_set"]["comparison_policy"] == "MATCHED_AVAILABLE_MONTHS"
    assert provenance["current_analytical_scope"]["period_set"]["included_month_numbers"] == (3, 4, 6)
    assert provenance["comparison"]["period_set"]["current_month_numbers"] == (3, 4, 6)
    assert provenance["comparison"]["period_set"]["comparison_month_numbers"] == (3, 4, 6)
    assert provenance["value"]["available_month_aggregation_method"] == "SUM_OF_MATCHED_AVAILABLE_MONTHS"


def test_explicit_reference_month_drives_custom_comparison(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts())

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            metric_concepts=("revenue",),
            comparison_mode=ComparisonMode.CUSTOM,
            comparison_period_start=date(2026, 4, 1),
        )
    )

    revenue = _result(response, "revenue")
    comparison = response.comparisons[0]
    assert revenue.value == pytest.approx(900.0)
    assert response.request_scope["comparison_period_start"] == date(2026, 4, 1)
    assert comparison.comparison_mode == ComparisonMode.CUSTOM
    assert comparison.comparison_period_start == date(2026, 4, 1)
    assert comparison.comparison_value == pytest.approx(600.0)
    assert comparison.delta == pytest.approx(300.0)


def test_explicit_reference_month_can_be_after_current_month(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts())

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            metric_concepts=("revenue",),
            comparison_mode=ComparisonMode.CUSTOM,
            comparison_period_start=date(2026, 6, 1),
        )
    )

    revenue = _result(response, "revenue")
    comparison = response.comparisons[0]
    assert revenue.value == pytest.approx(600.0)
    assert response.available_periods == (date(2026, 4, 1),)
    assert comparison.current_period_start == date(2026, 4, 1)
    assert comparison.comparison_period_start == date(2026, 6, 1)
    assert comparison.comparison_value == pytest.approx(900.0)
    assert comparison.delta == pytest.approx(-300.0)


def test_matched_month_set_can_compare_user_selected_years(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts())

    response = service.query(
        _request(
            ("revenue",),
            comparison_mode=ComparisonMode.CUSTOM,
            comparison_period_start=date(2025, 1, 1),
        )
    )

    comparison = response.comparisons[0]
    assert comparison.current_included_periods == (date(2026, 3, 1), date(2026, 4, 1), date(2026, 6, 1))
    assert comparison.comparison_included_periods == (date(2025, 3, 1), date(2025, 4, 1), date(2025, 6, 1))
    assert comparison.comparison_value == pytest.approx(600.0)


def test_matched_month_set_can_compare_against_later_selected_year(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts())

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 1),
            period_mode=PeriodMode.AVAILABLE_MONTH_SET,
            period_grain="month",
            grain_id="network",
            metric_concepts=("revenue",),
            comparison_mode=ComparisonMode.CUSTOM,
            comparison_period_start=date(2026, 1, 1),
        )
    )

    comparison = response.comparisons[0]
    assert response.available_periods == (date(2025, 3, 1), date(2025, 4, 1), date(2025, 6, 1))
    assert comparison.current_included_periods == (date(2025, 3, 1), date(2025, 4, 1), date(2025, 6, 1))
    assert comparison.comparison_included_periods == (date(2026, 3, 1), date(2026, 4, 1), date(2026, 6, 1))
    assert comparison.comparison_value == pytest.approx(1800.0)


def test_available_month_margin_pct_is_ratio_of_sums_not_mean_of_monthly_percentages(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts())

    response = service.query(_request(("retailer_margin_pct",)))

    result = _result(response, "retailer_margin_pct")
    assert result.value == pytest.approx((30.0 + 120.0 + 270.0) / (300.0 + 600.0 + 900.0))
    assert result.value != pytest.approx((0.10 + 0.20 + 0.30) / 3)
    assert result.provenance.payload["value"]["available_month_aggregation_method"] == (
        "RECOMPUTE_FROM_AVAILABLE_MONTH_COMPONENTS"
    )


def test_available_month_weighted_price_uses_weights_not_unweighted_mean(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts())

    response = service.query(_request(("weighted_shelf_price_vat",)))

    result = _result(response, "weighted_shelf_price_vat")
    assert result.value == pytest.approx((100.0 + 360.0 + 840.0) / (10.0 + 30.0 + 60.0))
    assert result.value != pytest.approx((10.0 + 12.0 + 14.0) / 3)


def test_available_month_share_recomputes_from_components(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts(include_share=True))

    response = service.query(_request(("category_revenue_share",)))

    result = _result(response, "category_revenue_share")
    assert result.value == pytest.approx((60.0 + 60.0 + 45.0) / (300.0 + 600.0 + 900.0))
    assert result.value != pytest.approx((0.20 + 0.10 + 0.05) / 3)
    assert result.share_scope == "network"


def test_available_month_period_only_metrics_fail_closed(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts(include_velocity=True))

    response = service.query(_request(("distribution", "velocity")))

    assert {result.value for result in response.metric_results} == {None}
    assert {"range_aggregation_period_only"} <= {item.issue_code for item in response.limitations}


def test_available_month_set_rejects_non_yoy_comparison_mode(tmp_path) -> None:
    service = _query_service(tmp_path, _metric_facts())

    response = service.query(_request(("revenue",), comparison_mode=ComparisonMode.PREVIOUS_AVAILABLE))

    assert response.comparisons == ()
    assert "available_month_comparison_mode_unsupported" in {item.issue_code for item in response.limitations}


def test_available_month_abc_recomputes_once_from_aggregated_basis(tmp_path) -> None:
    service = _portfolio_service(tmp_path, _portfolio_facts())

    response = service.query(
        PortfolioMarketQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 12, 1),
            period_mode=PeriodMode.AVAILABLE_MONTH_SET,
            period_grain="month",
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            entity_filters={"category": ("category_a",)},
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.READY
    assert [row["entity_id"] for row in item.rows] == ["manufacturer_b", "manufacturer_a", "manufacturer_c"]
    assert item.rows[0]["period_scope"] == "AVAILABLE_MONTH_YEAR"
    assert item.provenance["projection"]["population_scope"]["period_scope"] == "AVAILABLE_MONTH_YEAR"
    assert item.provenance["projection"]["evaluated_periods"] == (date(2026, 3, 1), date(2026, 4, 1))


def test_available_month_rank_movement_fails_closed_until_set_movement_route_exists(tmp_path) -> None:
    service = _portfolio_service(tmp_path, _portfolio_facts())

    response = service.query(
        PortfolioMarketQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 12, 1),
            period_mode=PeriodMode.AVAILABLE_MONTH_SET,
            period_grain="month",
            grain_id="manufacturer",
            concept_ids=("manufacturer_rank_revenue",),
            entity_filters={"category": ("category_a",)},
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("available_month_rank_movement_not_implemented",)


def _query_service(tmp_path, facts: pl.DataFrame) -> DashboardMartQueryService:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(facts, path)
    return DashboardMartQueryService(path, mart_builds=(_build(),))


def _portfolio_service(tmp_path, facts: pl.DataFrame) -> PortfolioMarketService:
    path = tmp_path / "portfolio_facts.parquet"
    write_mart_metric_facts(facts, path)
    return PortfolioMarketService(DashboardMartQueryService(path, mart_builds=(_build(),)))


def _request(
    metric_concepts: tuple[str, ...],
    *,
    comparison_mode: ComparisonMode = ComparisonMode.NONE,
    comparison_period_start: date | None = None,
) -> DashboardMetricQueryRequest:
    return DashboardMetricQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 1),
        period_mode=PeriodMode.AVAILABLE_MONTH_SET,
        period_grain="month",
        grain_id="network",
        metric_concepts=metric_concepts,
        comparison_mode=comparison_mode,
        comparison_period_start=comparison_period_start,
    )


def _metric_facts(*, include_share: bool = False, include_velocity: bool = False) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    specs = {
        date(2025, 3, 1): (100.0, 10.0, 100.0, 10.0),
        date(2025, 4, 1): (200.0, 40.0, 240.0, 20.0),
        date(2025, 6, 1): (300.0, 30.0, 450.0, 30.0),
        date(2025, 9, 1): (900.0, 90.0, 900.0, 90.0),
        date(2026, 3, 1): (300.0, 30.0, 100.0, 10.0),
        date(2026, 4, 1): (600.0, 120.0, 360.0, 30.0),
        date(2026, 6, 1): (900.0, 270.0, 840.0, 60.0),
    }
    share_by_period = {date(2026, 3, 1): 0.20, date(2026, 4, 1): 0.10, date(2026, 6, 1): 0.05}
    for period, (revenue, margin, shelf_numerator, units) in specs.items():
        rows.extend(
            [
                _fact(period, "network", "network", "revenue", revenue, "sum"),
                _fact(
                    period,
                    "network",
                    "network",
                    "retailer_margin_pct",
                    margin / revenue,
                    "ratio_of_sums",
                    numerator=margin,
                    denominator=revenue,
                ),
                _fact(
                    period,
                    "network",
                    "network",
                    "weighted_shelf_price_vat",
                    shelf_numerator / units,
                    "weighted_average",
                    numerator=shelf_numerator,
                    denominator=units,
                ),
                _fact(
                    period,
                    "network",
                    "network",
                    "distribution",
                    0.5,
                    "ratio_of_sums",
                    numerator=5.0,
                    denominator=10.0,
                    strategy=RangeAggregationStrategy.PERIOD_ONLY,
                ),
            ]
        )
        if include_share and period.year == 2026:
            rows.append(
                _fact(
                    period,
                    "network",
                    "network",
                    "category_revenue_share",
                    share_by_period[period],
                    "share",
                    numerator=share_by_period[period] * revenue,
                    denominator=revenue,
                    share_scope="network",
                    strategy=RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
                )
            )
        if include_velocity:
            rows.append(
                _fact(
                    period,
                    "network",
                    "network",
                    "velocity",
                    12.0,
                    "ratio_of_sums",
                    numerator=120.0,
                    denominator=10.0,
                    strategy=RangeAggregationStrategy.PERIOD_ONLY,
                )
            )
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)


def _portfolio_facts() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for period, values in (
        (date(2026, 3, 1), {"manufacturer_a": 100.0, "manufacturer_b": 220.0, "manufacturer_c": 20.0}),
        (date(2026, 4, 1), {"manufacturer_a": 200.0, "manufacturer_b": 280.0, "manufacturer_c": 80.0}),
    ):
        for entity_id, value in values.items():
            rows.append(
                _fact(
                    period,
                    "manufacturer",
                    entity_id,
                    "revenue",
                    value,
                    "sum",
                    private_label_scope=PrivateLabelScope.ONLY,
                    parent_entity_ids={"category": "category_a", "manufacturer": entity_id},
                )
            )
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)


def _fact(
    period: date,
    grain_id: str,
    entity_id: str,
    concept: str,
    value: float,
    aggregation: str,
    *,
    numerator: float | None = None,
    denominator: float | None = None,
    share_scope: str | None = None,
    strategy: RangeAggregationStrategy | None = None,
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
    parent_entity_ids: dict[str, str] | None = None,
) -> dict[str, object]:
    actual_strategy = strategy or {
        "sum": RangeAggregationStrategy.SUM_AVAILABLE_PERIODS,
        "ratio_of_sums": RangeAggregationStrategy.RATIO_OF_SUMS,
        "weighted_average": RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
        "share": RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
    }[aggregation]
    return {
        "retailer_id": "retailer_a",
        "source_id": "source_a",
        "source_revision_id": "revision_a",
        "analysis_run_id": "analysis_a",
        "mart_build_id": "build_a",
        "private_label_scope": private_label_scope.value,
        "period_grain": "month",
        "period_start": period,
        "period_end": date(period.year, period.month, 28),
        "business_period_id": period.strftime("%Y-%m"),
        "grain_id": grain_id,
        "entity_id": entity_id,
        "parent_entity_ids": json.dumps(parent_entity_ids or {}, sort_keys=True),
        "metric_concept": concept,
        "metric_name": concept,
        "metric_definition_id": f"retailer_a.{grain_id}.{concept}.v1",
        "metric_definition_version": "v1",
        "metric_config_hash": "hash_a",
        "semantic_family": concept,
        "semantic_compatibility_version": "v1",
        "cross_retailer_comparable": False,
        "value": value,
        "numerator_value": numerator,
        "denominator_value": denominator,
        "business_rule_id": None,
        "denominator_universe_type": None,
        "store_alias_mapping_version": None,
        "numerator_metric_name": None,
        "denominator_metric_name": None,
        "aggregation": aggregation,
        "range_aggregation_strategy": actual_strategy.value,
        "share_scope": share_scope,
        "rule_version": "rules_v1",
        "quality_status": "valid",
        "quality_flags": None,
        "created_at": datetime(2026, 1, 15, tzinfo=UTC),
    }


def _build() -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id="build_a",
        built_at=datetime(2026, 1, 15, tzinfo=UTC),
        build_version="mart.v1",
        code_version="test",
        retailer_id="retailer_a",
        source_ids=("source_a",),
        source_revision_ids=("revision_a",),
        analysis_run_ids=("analysis_a",),
        metric_config_hashes=("hash_a",),
        rule_versions=("rules_v1",),
        status=MartBuildStatus.APPROVED,
        period_grain="month",
        period_start=date(2025, 3, 1),
        period_end=date(2026, 12, 31),
    )


def _result(response, concept: str):
    matches = [result for result in response.metric_results if result.metric_concept == concept]
    assert len(matches) == 1
    return matches[0]
