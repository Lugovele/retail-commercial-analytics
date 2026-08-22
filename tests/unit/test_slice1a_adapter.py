import polars as pl

from retail_analytics.adapters.base import ConfiguredSourceAdapter
from retail_analytics.normalization.columns import ColumnMapping
from retail_analytics.normalization.stores import StoreAliasMapping
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


def test_allowed_unmapped_source_column_is_accepted():
    raw = _raw().with_columns(pl.lit("allowed").alias("demo_allowed_extra"))
    mapping = ColumnMapping(_mapping().columns, allowed_unmapped_source_columns=("demo_allowed_extra",))
    result = ConfiguredSourceAdapter().to_canonical(raw, mapping, _context())
    assert result.validation_report.is_valid
    assert result.canonical_frame.height == 1


def test_semantic_value_map_applies_boolean_values():
    raw = _raw().with_columns(pl.Series("demo_private_label", ["YES_FLAG"]))
    mapping = ColumnMapping(
        _mapping().columns | {"demo_private_label": "private_label_flag"},
        semantic_value_maps={"private_label_flag": {"YES_FLAG": True, "NO_FLAG": False}},
    )
    result = ConfiguredSourceAdapter().to_canonical(raw, mapping, _context())
    assert result.validation_report.is_valid
    assert result.canonical_frame.get_column("private_label_flag").to_list() == [True]


def test_unknown_semantic_value_fails():
    raw = _raw().with_columns(pl.Series("demo_private_label", ["UNKNOWN_FLAG"]))
    mapping = ColumnMapping(
        _mapping().columns | {"demo_private_label": "private_label_flag"},
        semantic_value_maps={"private_label_flag": {"YES_FLAG": True, "NO_FLAG": False}},
    )
    result = ConfiguredSourceAdapter().to_canonical(raw, mapping, _context())
    assert not result.validation_report.is_valid
    assert any(issue.code == "unknown_semantic_value" for issue in result.validation_report.fatal_errors)
    assert result.canonical_frame.is_empty()


def test_store_alias_resolves_and_preserves_source_store_id():
    aliases = StoreAliasMapping({"STORE_A_001": "STORE_A_CANONICAL"}, retailer_id="retailer_a", source_id="source_a", rule_version="rules_v1")
    result = ConfiguredSourceAdapter().to_canonical(_raw(), _mapping(), _context(), store_aliases=aliases)
    assert result.validation_report.is_valid
    assert result.canonical_frame.get_column("source_store_id").to_list() == ["STORE_A_001"]
    assert result.canonical_frame.get_column("canonical_store_id").to_list() == ["STORE_A_CANONICAL"]


def test_store_alias_is_context_scoped():
    aliases = StoreAliasMapping({"STORE_A_001": "STORE_A_CANONICAL"}, retailer_id="retailer_b", source_id="source_a", rule_version="rules_v1")
    result = ConfiguredSourceAdapter().to_canonical(_raw(), _mapping(), _context(), store_aliases=aliases)
    assert result.validation_report.is_valid
    assert result.canonical_frame.get_column("canonical_store_id").to_list() == ["STORE_A_001"]


def test_mapping_hash_includes_runtime_semantics():
    base = ColumnMapping(_mapping().columns)
    with_month_map = ColumnMapping(_mapping().columns, month_value_map={"JAN_LABEL": 1})
    with_allowlist = ColumnMapping(_mapping().columns, allowed_unmapped_source_columns=("demo_allowed_extra",))
    assert base.config_hash != with_month_map.config_hash
    assert base.config_hash != with_allowlist.config_hash
