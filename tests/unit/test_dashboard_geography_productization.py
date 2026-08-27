from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from retail_analytics.dashboard.geography import GeographyQueryRequest, GeographyQueryService
from retail_analytics.mart import (
    MartBuildMetadata,
    PrivateLabelScope,
    build_product_store_metric_facts,
    write_product_store_metric_facts,
)


def test_region_grouping_reconciles_additive_metrics_and_margin_ratio(tmp_path) -> None:
    product_store_path = _write_product_store_facts(tmp_path)
    service = GeographyQueryService(product_store_path, mart_builds=(_build(),))

    response = service.query(
        GeographyQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grouping="region",
            metric_concepts=("revenue", "units", "retailer_margin_abs", "retailer_margin_pct"),
            entity_filters={"category": ("CATEGORY_A",)},
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )

    values = _values(response)
    assert values[("REGION_NORTH", "revenue")] == 160.0
    assert values[("REGION_NORTH", "units")] == 16.0
    assert values[("REGION_NORTH", "retailer_margin_abs")] == 34.0
    assert values[("REGION_NORTH", "retailer_margin_pct")] == pytest.approx(34.0 / 160.0)
    assert values[("REGION_SOUTH", "revenue")] == 240.0
    assert sum(value for (entity_id, metric), value in values.items() if metric == "revenue") == 400.0
    north_margin = next(
        item
        for item in response["metric_results"]
        if item["entity_id"] == "REGION_NORTH" and item["metric_concept"] == "retailer_margin_pct"
    )
    assert north_margin["range_aggregation_strategy"] == "ratio_of_sums"
    assert north_margin["numerator_value"] == 34.0
    assert north_margin["denominator_value"] == 160.0
    assert north_margin["provenance"]["current_analytical_scope"]["grain_id"] == "region"
    assert north_margin["provenance"]["current_analytical_scope"]["entity_id"] == "REGION_NORTH"
    assert north_margin["provenance"]["current_analytical_scope"]["requested_periods"] == ["2026-06-01"]
    assert north_margin["provenance"]["value"]["range_aggregation_strategy"] == "ratio_of_sums"
    assert north_margin["provenance"]["guardrails"]["distribution_exposed"] is False


def test_store_format_and_region_format_groupings_are_filter_aware(tmp_path) -> None:
    product_store_path = _write_product_store_facts(tmp_path)
    service = GeographyQueryService(product_store_path, mart_builds=(_build(),))

    format_response = service.query(
        GeographyQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grouping="store_format",
            metric_concepts=("revenue", "retailer_margin_pct"),
            entity_filters={"category": ("CATEGORY_A",)},
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )
    matrix_response = service.query(
        GeographyQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grouping="region_store_format",
            metric_concepts=("revenue",),
            entity_filters={"category": ("CATEGORY_A",)},
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )

    assert _values(format_response)[("FORMAT_LARGE", "revenue")] == 360.0
    assert _values(format_response)[("FORMAT_SMALL", "revenue")] == 40.0
    matrix_values = _values(matrix_response)
    assert matrix_values[("REGION_NORTH | FORMAT_LARGE", "revenue")] == 120.0
    assert matrix_values[("REGION_NORTH | FORMAT_SMALL", "revenue")] == 40.0
    assert matrix_values[("REGION_SOUTH | FORMAT_LARGE", "revenue")] == 240.0
    assert sum(matrix_values.values()) == 400.0


def test_geography_comparison_uses_backend_periods_without_frontend_math(tmp_path) -> None:
    product_store_path = _write_product_store_facts(tmp_path)
    service = GeographyQueryService(product_store_path, mart_builds=(_build(),))

    response = service.query(
        GeographyQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grouping="region",
            metric_concepts=("revenue",),
            entity_filters={"category": ("CATEGORY_A",)},
            comparison_mode="YOY",
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )

    north = next(item for item in response["comparisons"] if item["entity_id"] == "REGION_NORTH")
    assert north["current_value"] == 160.0
    assert north["comparison_value"] == 150.0
    assert north["delta"] == 10.0


def test_unsupported_geography_semantics_fail_closed(tmp_path) -> None:
    service = GeographyQueryService(_write_product_store_facts(tmp_path), mart_builds=(_build(),))
    request = GeographyQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        period_mode="SINGLE_PERIOD",
        period_grain="month",
        grouping="fo2",
        metric_concepts=("revenue",),
        private_label_scope=PrivateLabelScope.INCLUDE,
    )

    with pytest.raises(ValueError, match="Unsupported geography grouping"):
        service.query(request)


def test_stores_ui_exposes_local_geography_grouping_without_distribution_or_fo2() -> None:
    html = (PROJECT_ROOT / "src/retail_analytics/dashboard/templates/index.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "src/retail_analytics/dashboard/static/app.js").read_text(encoding="utf-8")

    assert 'id="stores-group-mode"' in html
    assert '"/api/dashboard/geography"' in script
    assert "region_store_format" in script
    assert "geographyMetricConcepts" in script
    assert "distribution" not in script.split("const geographyMetricConcepts", maxsplit=1)[1].split(";", maxsplit=1)[0]
    assert "fo2" not in script.lower().split("const storegroupmodes", maxsplit=1)[1].split("];", maxsplit=1)[0]
    assert "territory" not in script.lower().split("const storegroupmodes", maxsplit=1)[1].split("];", maxsplit=1)[0]


def _values(response: dict) -> dict[tuple[str, str], float | None]:
    return {
        (item["entity_id"], item["metric_concept"]): item["value"]
        for item in response["metric_results"]
    }


def _write_product_store_facts(tmp_path) -> str:
    path = tmp_path / "product_store.parquet"
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            _source_rows(),
            build_metadata=_build(),
            source_revision_id="revision_a",
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        path,
    )
    return str(path)


def _source_rows() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    specs = (
        (date(2025, 6, 1), "CATEGORY_A", "SKU_A", "STORE_A", "REGION_NORTH", "FORMAT_LARGE", 10.0, 100.0, 20.0),
        (date(2025, 6, 1), "CATEGORY_A", "SKU_B", "STORE_B", "REGION_NORTH", "FORMAT_SMALL", 5.0, 50.0, 10.0),
        (date(2025, 6, 1), "CATEGORY_A", "SKU_C", "STORE_C", "REGION_SOUTH", "FORMAT_LARGE", 20.0, 200.0, 50.0),
        (date(2026, 6, 1), "CATEGORY_A", "SKU_A", "STORE_A", "REGION_NORTH", "FORMAT_LARGE", 12.0, 120.0, 30.0),
        (date(2026, 6, 1), "CATEGORY_A", "SKU_B", "STORE_B", "REGION_NORTH", "FORMAT_SMALL", 4.0, 40.0, 4.0),
        (date(2026, 6, 1), "CATEGORY_A", "SKU_C", "STORE_C", "REGION_SOUTH", "FORMAT_LARGE", 24.0, 240.0, 48.0),
        (date(2026, 6, 1), "CATEGORY_B", "SKU_D", "STORE_A", "REGION_NORTH", "FORMAT_LARGE", 99.0, 990.0, 99.0),
    )
    for index, (period, category, sku, store, region, store_format, units, revenue, margin) in enumerate(specs, start=1):
        rows.append(
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "analysis_run_id": "analysis_a",
                "period": period,
                "category": category,
                "manufacturer": "MANUFACTURER_A",
                "brand": "BRAND_A",
                "canonical_product_id": sku,
                "canonical_store_id": store,
                "sku_name": f"{sku} name",
                "units": units,
                "revenue_vat": revenue * 1.2,
                "revenue_net": revenue,
                "retailer_margin_abs": margin,
                "shelf_price_vat": 12.0,
                "input_price_vat": 8.0,
                "private_label_flag": False,
                "source_row_number": index,
                "store_format": store_format,
                "region": region,
            }
        )
    return pl.DataFrame(rows)


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
        status="approved",
        period_grain="month",
        period_start=date(2025, 6, 1),
        period_end=date(2026, 6, 1),
    )


PROJECT_ROOT = Path(__file__).resolve().parents[2]
