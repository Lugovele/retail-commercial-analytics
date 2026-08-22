import polars as pl
import pytest

from retail_analytics.normalization.columns import ColumnMapping
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.pipeline.slice1 import run_slice1a_ingestion
from retail_analytics.schema.validation import ValidationError
from retail_analytics.storage.parquet import read_canonical_parquet


def _mapping(mapping_id="demo_mapping_v1", version="v1"):
    return ColumnMapping({
        "demo_year": "year", "demo_month": "month", "demo_store_id": "source_store_id",
        "demo_sku_id": "source_sku_id", "demo_sku_name": "sku_name",
        "demo_manufacturer": "manufacturer", "demo_brand": "brand", "demo_category": "category",
        "demo_units": "units", "demo_revenue_vat": "revenue_vat",
    }, mapping_id=mapping_id, version=version)


def _context(retailer_id, source_id):
    return AnalysisContext(f"run_{retailer_id}", retailer_id, source_id, "v1", "rules_v1")


def _raw():
    return pl.DataFrame({
        "demo_year": [2026, 2026], "demo_month": [6, 7],
        "demo_store_id": ["STORE_A_001", "STORE_A_002"],
        "demo_sku_id": ["SKU_A_001", "SKU_A_002"],
        "demo_sku_name": ["SKU_A_001", "SKU_A_002"],
        "demo_manufacturer": ["MANUFACTURER_A", "MANUFACTURER_A"],
        "demo_brand": ["BRAND_A", "BRAND_A"], "demo_category": ["CATEGORY_A", "CATEGORY_A"],
        "demo_units": ["10", "20"], "demo_revenue_vat": ["100.5", "210.0"],
    })


def test_canonical_parquet_roundtrip_preserves_schema_and_values(tmp_path):
    result = run_slice1a_ingestion(raw_source=_raw(), mapping=_mapping(), context=_context("retailer_a", "source_a"), output_path=tmp_path / "canonical.parquet")
    roundtrip = read_canonical_parquet(result.canonical_data_path)
    assert result.validation_report.is_valid
    assert result.metadata.source_row_count == 2
    assert result.metadata.mapping_id == "demo_mapping_v1"
    assert result.metadata.mapping_version == "v1"
    assert result.metadata.mapping_config_hash
    assert result.source_profile.source_sku_count == 2
    assert roundtrip.height == 2
    assert roundtrip.get_column("units").to_list() == [10.0, 20.0]
    assert roundtrip.schema["period"] == pl.Date


def test_mapping_without_id_or_version_records_config_hash(tmp_path):
    result = run_slice1a_ingestion(raw_source=_raw(), mapping=_mapping(mapping_id=None, version=None), context=_context("retailer_a", "source_a"), output_path=tmp_path / "hash.parquet")
    assert result.metadata.mapping_id is None
    assert result.metadata.mapping_version is None
    assert len(result.metadata.mapping_config_hash) == 16


def test_unmapped_source_column_fails_ingestion(tmp_path):
    raw = _raw().with_columns(pl.lit("ignored").alias("demo_unmapped_column"))
    with pytest.raises(ValidationError) as error:
        run_slice1a_ingestion(raw_source=raw, mapping=_mapping(), context=_context("retailer_a", "source_a"), output_path=tmp_path / "unmapped.parquet")
    assert any(issue.code == "unmapped_source_column" for issue in error.value.report.issues)


def test_same_source_sku_id_in_two_retailers_remains_distinct(tmp_path):
    result_a = run_slice1a_ingestion(raw_source=_raw().with_columns(pl.lit("SKU_A_001").alias("demo_sku_id")), mapping=_mapping(), context=_context("retailer_a", "source_a"), output_path=tmp_path / "a.parquet")
    result_b = run_slice1a_ingestion(raw_source=_raw().with_columns(pl.lit("SKU_A_001").alias("demo_sku_id")), mapping=_mapping(), context=_context("retailer_b", "source_b"), output_path=tmp_path / "b.parquet")
    data_a = read_canonical_parquet(result_a.canonical_data_path)
    data_b = read_canonical_parquet(result_b.canonical_data_path)
    assert data_a.get_column("retailer_id").unique().to_list() == ["retailer_a"]
    assert data_b.get_column("retailer_id").unique().to_list() == ["retailer_b"]
    assert data_a.get_column("canonical_product_id").to_list() == ["SKU_A_001", "SKU_A_001"]
    assert data_b.get_column("canonical_product_id").to_list() == ["SKU_A_001", "SKU_A_001"]


def test_same_source_store_id_in_two_retailers_remains_distinct(tmp_path):
    result_a = run_slice1a_ingestion(raw_source=_raw().with_columns(pl.lit("STORE_A_001").alias("demo_store_id")), mapping=_mapping(), context=_context("retailer_a", "source_a"), output_path=tmp_path / "stores_a.parquet")
    result_b = run_slice1a_ingestion(raw_source=_raw().with_columns(pl.lit("STORE_A_001").alias("demo_store_id")), mapping=_mapping(), context=_context("retailer_b", "source_b"), output_path=tmp_path / "stores_b.parquet")
    data_a = read_canonical_parquet(result_a.canonical_data_path)
    data_b = read_canonical_parquet(result_b.canonical_data_path)
    assert set(zip(data_a["retailer_id"].to_list(), data_a["canonical_store_id"].to_list())) == {("retailer_a", "STORE_A_001")}
    assert set(zip(data_b["retailer_id"].to_list(), data_b["canonical_store_id"].to_list())) == {("retailer_b", "STORE_A_001")}


def test_invalid_month_fixture_fails(tmp_path):
    raw = _raw().with_columns(pl.Series("demo_month", [13, 7]))
    with pytest.raises(ValidationError) as error:
        run_slice1a_ingestion(raw_source=raw, mapping=_mapping(), context=_context("retailer_a", "source_a"), output_path=tmp_path / "bad_month.parquet")
    assert any(issue.code == "invalid_month" for issue in error.value.report.issues)


def test_invalid_numeric_fixture_fails(tmp_path):
    raw = _raw().with_columns(pl.Series("demo_units", ["bad", "20"]))
    with pytest.raises(ValidationError) as error:
        run_slice1a_ingestion(raw_source=raw, mapping=_mapping(), context=_context("retailer_a", "source_a"), output_path=tmp_path / "bad_numeric.parquet")
    assert any(issue.code == "invalid_numeric_value" for issue in error.value.report.issues)


def test_duplicate_candidate_fixture_reports_without_aggregation(tmp_path):
    raw = _raw().with_columns(pl.Series("demo_month", [6, 6]), pl.Series("demo_store_id", ["STORE_A_001", "STORE_A_001"]), pl.Series("demo_sku_id", ["SKU_A_001", "SKU_A_001"]))
    result = run_slice1a_ingestion(raw_source=raw, mapping=_mapping(), context=_context("retailer_a", "source_a"), output_path=tmp_path / "duplicate.parquet")
    assert result.metadata.canonical_row_count == 2
    assert result.source_profile.duplicate_candidate_count == 2