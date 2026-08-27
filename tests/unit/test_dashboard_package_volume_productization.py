from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from retail_analytics.dashboard.package_volume import (
    PackageVolumeQueryRequest,
    PackageVolumeQueryService,
)
from retail_analytics.mart import (
    MartBuildMetadata,
    PrivateLabelScope,
    build_product_store_metric_facts,
    write_product_store_metric_facts,
)


def test_package_grouping_recomputes_share_and_margin_ratio(tmp_path: Path) -> None:
    source_path, product_store_path = _write_inputs(tmp_path)
    service = PackageVolumeQueryService(source_path, product_store_path, mart_builds=(_build(),))

    response = service.query(
        PackageVolumeQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grouping="package",
            basis_metric="revenue",
            metric_concepts=("revenue", "units", "retailer_margin_abs", "retailer_margin_pct"),
            entity_filters={"category": ("CATEGORY_A",)},
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )

    rows = {row["entity_id"]: row for row in response["rows"]}
    assert rows["PACK_A"]["metric_value"] == 160.0
    assert rows["PACK_A"]["share"] == pytest.approx(160.0 / 400.0)
    assert rows["PACK_A"]["metrics"]["retailer_margin_pct"] == pytest.approx(34.0 / 160.0)
    assert rows["PACK_A"]["sku_count"] == 2
    assert rows["PACK_B"]["metric_value"] == 240.0
    assert sum(row["metric_value"] for row in response["rows"]) == 400.0
    provenance = rows["PACK_A"]["provenance"]
    assert provenance["source_evidence"]["status"] == "JOINED_CANONICAL_PRODUCT_ATTRIBUTES_TO_PRODUCT_STORE_FACTS"
    assert provenance["guardrails"]["package_abc_exposed"] is False
    assert provenance["guardrails"]["flavor_inferred"] is False


def test_volume_grouping_uses_exact_volume_and_numeric_order(tmp_path: Path) -> None:
    source_path, product_store_path = _write_inputs(tmp_path)
    service = PackageVolumeQueryService(source_path, product_store_path, mart_builds=(_build(),))

    response = service.query(
        PackageVolumeQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grouping="volume",
            basis_metric="units",
            metric_concepts=("units", "revenue"),
            entity_filters={"category": ("CATEGORY_A",)},
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )

    assert [row["dimension_values"]["volume_l"] for row in response["rows"]] == [0.5, 1.0]
    assert [row["entity_id"] for row in response["rows"]] == ["0.5 L", "1 L"]
    assert {row["entity_id"]: row["metric_value"] for row in response["rows"]} == {"0.5 L": 16.0, "1 L": 24.0}
    assert all(row["provenance"]["guardrails"]["volume_band_exposed"] is False for row in response["rows"])


def test_package_volume_grouping_and_product_filters(tmp_path: Path) -> None:
    source_path, product_store_path = _write_inputs(tmp_path)
    service = PackageVolumeQueryService(source_path, product_store_path, mart_builds=(_build(),))

    response = service.query(
        PackageVolumeQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grouping="package_volume",
            basis_metric="retailer_margin_abs",
            metric_concepts=("revenue", "retailer_margin_abs"),
            entity_filters={"category": ("CATEGORY_A",), "manufacturer": ("MANUFACTURER_A",)},
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )

    rows = {row["entity_id"]: row for row in response["rows"]}
    assert rows["PACK_A | 0.5 L"]["metric_value"] == 34.0
    assert rows["PACK_B | 1 L"]["metric_value"] == 48.0
    assert sum(row["metric_value"] for row in response["rows"]) == 82.0
    assert response["request_scope"]["entity_filters"] == {"category": ("CATEGORY_A",), "manufacturer": ("MANUFACTURER_A",)}


def test_comparison_and_available_months_are_backend_period_set_values(tmp_path: Path) -> None:
    source_path, product_store_path = _write_inputs(tmp_path)
    service = PackageVolumeQueryService(source_path, product_store_path, mart_builds=(_build(),))

    response = service.query(
        PackageVolumeQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 12, 1),
            period_mode="AVAILABLE_MONTH_SET",
            period_grain="month",
            grouping="package",
            basis_metric="revenue",
            metric_concepts=("revenue",),
            entity_filters={"category": ("CATEGORY_A",)},
            comparison_mode="YOY",
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )

    pack_a = next(row for row in response["rows"] if row["entity_id"] == "PACK_A")
    assert pack_a["metric_value"] == 160.0
    assert pack_a["reference_metric_value"] == 150.0
    assert pack_a["pct_delta"] == pytest.approx(10.0 / 150.0)
    assert pack_a["provenance"]["current_analytical_scope"]["period_set"]["scope_type"] == "AVAILABLE_MONTH_SET"
    assert pack_a["provenance"]["current_analytical_scope"]["period_set"]["comparison_policy"] == "MATCHED_AVAILABLE_MONTHS"


def test_store_filter_is_served_from_product_store_without_scope_widening(tmp_path: Path) -> None:
    source_path, product_store_path = _write_inputs(tmp_path)
    service = PackageVolumeQueryService(source_path, product_store_path, mart_builds=(_build(),))

    response = service.query(
        PackageVolumeQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grouping="package",
            basis_metric="revenue",
            metric_concepts=("revenue",),
            entity_filters={"category": ("CATEGORY_A",), "store": ("STORE_A",)},
            private_label_scope=PrivateLabelScope.INCLUDE,
        )
    )

    rows = {row["entity_id"]: row for row in response["rows"]}
    assert rows == {"PACK_A": rows["PACK_A"]}
    assert rows["PACK_A"]["metric_value"] == 120.0
    assert rows["PACK_A"]["share"] == pytest.approx(1.0)


def test_unsupported_package_volume_semantics_fail_closed(tmp_path: Path) -> None:
    source_path, product_store_path = _write_inputs(tmp_path)
    service = PackageVolumeQueryService(source_path, product_store_path, mart_builds=(_build(),))
    request = PackageVolumeQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        period_mode="SINGLE_PERIOD",
        period_grain="month",
        grouping="flavor",
        basis_metric="revenue",
        metric_concepts=("revenue",),
        private_label_scope=PrivateLabelScope.INCLUDE,
    )

    with pytest.raises(ValueError, match="Unsupported package/volume grouping"):
        service.query(request)


def test_portfolio_ui_exposes_package_volume_local_mode_without_package_abc() -> None:
    html = (PROJECT_ROOT / "src/retail_analytics/dashboard/templates/index.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "src/retail_analytics/dashboard/static/app.js").read_text(encoding="utf-8")

    assert 'id="portfolio-analysis-mode"' in html
    assert '"/api/dashboard/package-volume"' in script
    assert "package_volume" in script
    assert "portfolioMixMetricConcepts" in script
    assert "package_abc" not in script.lower()
    assert "volume_abc" not in script.lower()
    assert "flavor" not in script.lower().split("const portfoliomixmodes", maxsplit=1)[1].split("};", maxsplit=1)[0]


def _write_inputs(tmp_path: Path) -> tuple[str, str]:
    source_path = tmp_path / "source_like.parquet"
    source_rows = _source_rows()
    source_rows.write_parquet(source_path)
    product_store_path = tmp_path / "product_store.parquet"
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            source_rows,
            build_metadata=_build(),
            source_revision_id="revision_a",
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    return str(source_path), str(product_store_path)


def _source_rows() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    specs = (
        (date(2025, 6, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_A", "PACK_A", 0.5, 10.0, 100.0, 20.0),
        (date(2025, 6, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_B", "STORE_B", "PACK_A", 0.5, 5.0, 50.0, 10.0),
        (date(2025, 6, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_B", "SKU_C", "STORE_C", "PACK_B", 1.0, 20.0, 200.0, 50.0),
        (date(2026, 6, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_A", "PACK_A", 0.5, 12.0, 120.0, 30.0),
        (date(2026, 6, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_B", "STORE_B", "PACK_A", 0.5, 4.0, 40.0, 4.0),
        (date(2026, 6, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_B", "SKU_C", "STORE_C", "PACK_B", 1.0, 24.0, 240.0, 48.0),
        (date(2026, 6, 1), "CATEGORY_B", "MANUFACTURER_B", "BRAND_C", "SKU_D", "STORE_A", "PACK_C", 1.5, 99.0, 990.0, 99.0),
    )
    for index, (period, category, manufacturer, brand, sku, store, package, volume, units, revenue, margin) in enumerate(specs, start=1):
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
                "private_label_flag": False,
                "source_row_number": index,
                "store_format": "FORMAT_A",
                "region": "REGION_A",
                "package": package,
                "volume_l": volume,
                "volume_band": "NOT_PRODUCTIZED",
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
