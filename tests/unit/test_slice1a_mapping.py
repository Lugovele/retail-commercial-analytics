from retail_analytics.normalization.columns import ColumnMapping


def _base_columns():
    return {
        "demo_year": "year",
        "demo_month": "month",
        "demo_store_id": "source_store_id",
        "demo_sku_id": "source_sku_id",
        "demo_units": "units",
        "demo_revenue_vat": "revenue_vat",
    }

def test_column_mapping_maps_demo_fields_to_canonical():
    mapping = ColumnMapping(_base_columns())
    assert mapping.validate().is_valid
    assert mapping.columns["demo_sku_id"] == "source_sku_id"

def test_missing_required_mapping_fails():
    columns = _base_columns()
    columns.pop("demo_sku_id")
    report = ColumnMapping(columns).validate()
    assert not report.is_valid
    assert any(issue.code == "missing_required_mapping" for issue in report.issues)

def test_unknown_canonical_target_fails():
    columns = _base_columns() | {"demo_extra": "real_world_target"}
    report = ColumnMapping(columns).validate()
    assert not report.is_valid
    assert any(issue.code == "unknown_canonical_target" for issue in report.issues)