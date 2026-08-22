import polars as pl

from retail_analytics.schema.canonical import (
    ALLOWED_CANONICAL_TARGETS,
    CANONICAL_SCHEMA,
    REQUIRED_CANONICAL_COLUMNS,
)


def test_canonical_schema_contains_required_columns_and_types():
    assert set(CANONICAL_SCHEMA) == ALLOWED_CANONICAL_TARGETS
    assert set(REQUIRED_CANONICAL_COLUMNS).issubset(CANONICAL_SCHEMA)
    assert CANONICAL_SCHEMA["retailer_id"] == pl.String
    assert CANONICAL_SCHEMA["period"] == pl.Date
    assert CANONICAL_SCHEMA["year"] == pl.Int64
    assert CANONICAL_SCHEMA["month"] == pl.Int64
    assert CANONICAL_SCHEMA["units"] == pl.Float64
    assert CANONICAL_SCHEMA["revenue_vat"] == pl.Float64
    assert CANONICAL_SCHEMA["private_label_flag"] == pl.Boolean
    assert CANONICAL_SCHEMA["source_row_number"] == pl.Int64