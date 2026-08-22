import polars as pl

from retail_analytics.adapters.base import ConfiguredSourceAdapter
from retail_analytics.normalization.columns import ColumnMapping
from retail_analytics.pipeline.context import AnalysisContext


def _context(retailer_id="retailer_a"):
    return AnalysisContext("run_a", retailer_id, "source_a", "v1", "rules_v1")


def _mapping():
    return ColumnMapping({
        "demo_year": "year", "demo_month": "month", "demo_store_id": "source_store_id",
        "demo_sku_id": "source_sku_id", "demo_sku_name": "sku_name",
        "demo_manufacturer": "manufacturer", "demo_brand": "brand", "demo_category": "category",
        "demo_units": "units", "demo_revenue_vat": "revenue_vat",
    })


def _raw():
    return pl.DataFrame({
        "demo_year": [2026], "demo_month": [6], "demo_store_id": ["STORE_A_001"],
        "demo_sku_id": ["SKU_A_001"], "demo_sku_name": ["SKU_A_001"],
        "demo_manufacturer": ["MANUFACTURER_A"], "demo_brand": ["BRAND_A"],
        "demo_category": ["CATEGORY_A"], "demo_units": ["10"], "demo_revenue_vat": ["100.5"],
    })


def test_adapter_returns_canonical_columns():
    result = ConfiguredSourceAdapter().to_canonical(_raw(), _mapping(), _context())
    assert result.validation_report.is_valid
    assert "retailer_id" in result.canonical_frame.columns
    assert "canonical_product_id" in result.canonical_frame.columns


def test_adapter_does_not_mutate_source():
    raw = _raw()
    before = raw.clone()
    ConfiguredSourceAdapter().to_canonical(raw, _mapping(), _context())
    assert raw.equals(before)


def test_adapter_preserves_source_row_number():
    result = ConfiguredSourceAdapter().to_canonical(_raw(), _mapping(), _context())
    assert result.canonical_frame.get_column("source_row_number").to_list() == [1]


def test_unmapped_source_column_fails():
    raw = _raw().with_columns(pl.lit("ignored").alias("demo_unmapped_column"))
    result = ConfiguredSourceAdapter().to_canonical(raw, _mapping(), _context())
    assert not result.validation_report.is_valid
    assert any(issue.code == "unmapped_source_column" for issue in result.validation_report.fatal_errors)
    assert result.canonical_frame.is_empty()