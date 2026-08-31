from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from retail_analytics.mart.builds import MartBuildMetadata, MartBuildStatus
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA, write_mart_metric_facts
from retail_analytics.mart.query import (
    ComparisonMode,
    DashboardMartQueryService,
    DashboardMetricQueryRequest,
    PeriodMode,
)


def test_price_per_liter_excludes_invalid_volume_rows_from_both_components(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        [
            _source_row("2026-06-01", "S1", "SKU_A", units=1, revenue_vat=100, volume_l=1),
            _source_row("2026-06-01", "S2", "SKU_B", units=1, revenue_vat=100, volume_l=None),
            _source_row("2026-06-01", "S3", "SKU_C", units=1, revenue_vat=100, volume_l=0),
        ],
    )

    response = service.query(_request("network", ("ALL",), ("average_price_per_liter",)))

    result = response.metric_results[0]
    assert result.numerator_value == 100
    assert result.denominator_value == 1
    assert result.value == 100


def test_category_filter_preserves_legacy_overview_metrics_and_effective_approved_kpis(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        [
            _source_row("2026-06-01", "S1", "SKU_A", category="WATER", units=10, revenue_vat=100, volume_l=1),
            _source_row("2026-06-01", "S2", "SKU_B", category="WATER", units=20, revenue_vat=200, volume_l=2),
            _source_row("2026-06-01", "S3", "SKU_C", category="JUICE", units=5, revenue_vat=50, volume_l=1),
        ],
        fact_rows=[
            _fact_row("units", 30, category="WATER"),
            _fact_row("revenue_vat", 300, category="WATER"),
            _fact_row("retailer_margin_abs", 75, category="WATER"),
            _fact_row("retailer_margin_pct", 0.25, numerator=75, denominator=300, category="WATER"),
            _fact_row("weighted_shelf_price_vat", 50, numerator=500, denominator=10, category="WATER"),
            _fact_row("weighted_input_price_vat", 35, numerator=350, denominator=10, category="WATER"),
        ],
    )
    request = replace(
        _request(
            "network",
            ("ALL",),
            (
                "units",
                "revenue_vat",
                "retailer_margin_abs",
                "retailer_margin_pct",
                "velocity",
                "distribution",
                "weighted_distribution",
                "average_price_per_liter",
                "weighted_shelf_price_vat",
                "weighted_input_price_vat",
            ),
        ),
        entity_filters={"category": ("WATER",)},
    )

    response = service.query(request)

    values = {result.metric_concept: result for result in response.metric_results}
    assert values["units"].value == 30
    assert values["revenue_vat"].value == 300
    assert values["retailer_margin_abs"].value == 75
    assert values["retailer_margin_pct"].value == 0.25
    assert values["weighted_shelf_price_vat"].value == 50
    assert values["weighted_input_price_vat"].value == 35
    assert values["velocity"].grain_id == "category"
    assert values["velocity"].entity_id == "WATER"
    assert values["velocity"].value == 15
    assert values["distribution"].value == pytest.approx(2 / 3)
    assert values["average_price_per_liter"].grain_id == "category"
    assert values["average_price_per_liter"].value == pytest.approx(300 / 50)
    assert "weighted_distribution" not in values
    assert {
        (limitation.issue_code, limitation.metric_concept)
        for limitation in response.limitations
    } >= {("metric_not_supported_for_grain", "weighted_distribution")}


def test_numeric_distribution_multi_month_uses_distinct_period_universe(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        [
            _source_row("2026-05-01", "S1", "SKU_A", brand="BRAND_A", units=1),
            _source_row("2026-05-01", "S2", "SKU_B", brand="BRAND_B", units=1),
            _source_row("2026-06-01", "S2", "SKU_A", brand="BRAND_A", units=1),
            _source_row("2026-06-01", "S3", "SKU_B", brand="BRAND_B", units=1),
        ],
    )
    request = _request(
        "brand",
        ("BRAND_A",),
        ("distribution",),
        date_from=date(2026, 5, 1),
        date_to=date(2026, 6, 1),
        period_mode=PeriodMode.DATE_RANGE,
    )

    response = service.query(request)

    result = response.metric_results[0]
    assert result.numerator_value == 2
    assert result.denominator_value == 3
    assert result.value == pytest.approx(2 / 3)


def test_weighted_distribution_uses_category_revenue_in_active_outlets(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        [
            _source_row("2026-06-01", "S1", "SKU_A", brand="BRAND_A", revenue_vat=10, units=1),
            _source_row("2026-06-01", "S1", "SKU_B", brand="BRAND_B", revenue_vat=90, units=1),
            _source_row("2026-06-01", "S2", "SKU_B", brand="BRAND_B", revenue_vat=100, units=1),
        ],
    )

    response = service.query(_request("brand", ("BRAND_A",), ("weighted_distribution",)))

    result = response.metric_results[0]
    assert result.numerator_value == 100
    assert result.denominator_value == 200
    assert result.value == 0.5


def test_source_like_approved_kpi_definition_ids_are_queryable(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        [
            _source_row("2026-06-01", "S1", "SKU_A", brand="BRAND_A", revenue_vat=10, units=1),
            _source_row("2026-06-01", "S1", "SKU_B", brand="BRAND_B", revenue_vat=90, units=1),
            _source_row("2026-06-01", "S2", "SKU_B", brand="BRAND_B", revenue_vat=100, units=1),
        ],
    )
    request = _request("brand", ("BRAND_A",), ())
    request = replace(request, metric_definition_ids=("globus.brand.weighted_distribution.v1",))

    response = service.query(request)

    result = response.metric_results[0]
    assert result.lineage is not None
    assert result.lineage.metric_definition_id == "globus.brand.weighted_distribution.v1"
    assert result.metric_concept == "weighted_distribution"
    assert result.value == 0.5


def test_manufacturer_is_not_approved_kpi_grain(tmp_path: Path) -> None:
    service = _service(tmp_path, [_source_row("2026-06-01", "S1", "SKU_A", manufacturer="MFR_A")])

    response = service.query(_request("manufacturer", ("MFR_A",), ("velocity", "distribution", "weighted_distribution")))

    assert response.metric_results == ()
    assert {item.issue_code for item in response.limitations} >= {
        "manufacturer_kpi_grain_unsupported",
        "metric_not_supported_for_grain",
    }


def _service(
    tmp_path: Path,
    source_rows: list[dict[str, object]],
    *,
    fact_rows: list[dict[str, object]] | None = None,
) -> DashboardMartQueryService:
    facts_path = tmp_path / "facts.parquet"
    source_path = tmp_path / "canonical.parquet"
    write_mart_metric_facts(pl.DataFrame(fact_rows or [], schema=MART_METRIC_FACT_SCHEMA), facts_path)
    pl.DataFrame(source_rows).write_parquet(source_path)
    return DashboardMartQueryService(
        facts_path,
        mart_builds=(_build(),),
        source_like_rows_path=source_path,
    )


def _build() -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id="build_approved_kpis",
        built_at=datetime(2026, 6, 1, tzinfo=UTC),
        build_version="test",
        code_version="test",
        retailer_id="globus",
        source_ids=("globus_base_2025_06_2026",),
        source_revision_ids=("source_revision_test",),
        analysis_run_ids=("analysis_run_test",),
        metric_config_hashes=("hash_test",),
        rule_versions=("private_rules_v1",),
        status=MartBuildStatus.APPROVED,
        period_grain="month",
    )


def _request(
    grain: str,
    entity_ids: tuple[str, ...],
    concepts: tuple[str, ...],
    *,
    date_from: date = date(2026, 6, 1),
    date_to: date = date(2026, 6, 1),
    period_mode: PeriodMode = PeriodMode.SINGLE_PERIOD,
) -> DashboardMetricQueryRequest:
    return DashboardMetricQueryRequest(
        retailer_id="globus",
        source_id="globus_base_2025_06_2026",
        date_from=date_from,
        date_to=date_to,
        period_mode=period_mode,
        period_grain="month",
        grain_id=grain,
        entity_ids=entity_ids,
        metric_concepts=concepts,
        comparison_mode=ComparisonMode.NONE,
    )


def _source_row(
    period: str,
    store: str,
    sku: str,
    *,
    category: str = "WATER",
    manufacturer: str = "MFR",
    brand: str = "BRAND",
    units: float = 1,
    revenue_vat: float = 10,
    volume_l: float | None = 1,
) -> dict[str, object]:
    return {
        "retailer_id": "globus",
        "source_id": "globus_base_2025_06_2026",
        "analysis_run_id": "analysis_run_test",
        "period": date.fromisoformat(period),
        "canonical_store_id": store,
        "canonical_product_id": sku,
        "category": category,
        "manufacturer": manufacturer,
        "brand": brand,
        "units": units,
        "revenue_vat": revenue_vat,
        "volume_l": volume_l,
    }


def _fact_row(
    concept: str,
    value: float,
    *,
    category: str,
    numerator: float | None = None,
    denominator: float | None = None,
) -> dict[str, object]:
    return {
        "retailer_id": "globus",
        "source_id": "globus_base_2025_06_2026",
        "source_revision_id": "source_revision_test",
        "analysis_run_id": "analysis_run_test",
        "mart_build_id": "build_approved_kpis",
        "private_label_scope": "INCLUDE",
        "period_grain": "month",
        "period_start": date(2026, 6, 1),
        "period_end": date(2026, 6, 30),
        "business_period_id": "2026-06-01",
        "grain_id": "category",
        "entity_id": category,
        "parent_entity_ids": "{}",
        "metric_concept": concept,
        "metric_name": concept,
        "metric_definition_id": f"globus.category.{concept}.v1",
        "metric_definition_version": "v1",
        "metric_config_hash": "hash_test",
        "semantic_family": None,
        "semantic_compatibility_version": None,
        "cross_retailer_comparable": False,
        "value": value,
        "numerator_value": numerator,
        "denominator_value": denominator,
        "business_rule_id": None,
        "denominator_universe_type": None,
        "store_alias_mapping_version": None,
        "numerator_metric_name": None,
        "denominator_metric_name": None,
        "aggregation": "ratio_of_sums" if numerator is not None else "sum",
        "range_aggregation_strategy": "ratio_of_sums" if numerator is not None else "sum_available_periods",
        "share_scope": None,
        "rule_version": "private_rules_v1",
        "quality_status": "valid",
        "quality_flags": None,
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
