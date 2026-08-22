"""Type normalization helpers for canonical ingestion."""
from __future__ import annotations

import polars as pl

from retail_analytics.schema.canonical import REQUIRED_STRING_COLUMNS
from retail_analytics.schema.validation import ValidationIssue, ValidationReport

STRING_FIELDS = ("retailer_id", "source_id", "analysis_run_id", "source_store_id", "canonical_store_id", "source_sku_id", "canonical_product_id", "sku_name", "manufacturer", "brand", "category", "store_format", "region", "subcategory", "subcategory_2", "volume_band", "package", "carbonation")
INTEGER_FIELDS = ("year", "month", "source_row_number")
NUMERIC_FIELDS = ("units", "revenue_vat", "volume_l", "shelf_price_vat", "input_price_vat")
BOOLEAN_FIELDS = ("private_label_flag",)

def _row_numbers(frame: pl.DataFrame) -> list[int]:
    if "source_row_number" in frame.columns:
        return [int(value) for value in frame.get_column("source_row_number").to_list()]
    return list(range(1, frame.height + 1))

def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())

def normalize_types(frame: pl.DataFrame) -> tuple[pl.DataFrame, ValidationReport]:
    """Coerce canonical fields without silently swallowing invalid values."""
    issues: list[ValidationIssue] = []
    output = frame.clone()
    row_numbers = _row_numbers(frame)
    for field in STRING_FIELDS:
        if field not in output.columns:
            continue
        values = output.get_column(field).to_list()
        if field in REQUIRED_STRING_COLUMNS:
            for raw, row_number in zip(values, row_numbers, strict=True):
                if _is_blank(raw):
                    issues.append(ValidationIssue("blank_required_string", f"{field} cannot be blank", field=field, source_row_number=row_number))
        output = output.with_columns(pl.col(field).cast(pl.String, strict=False))
    for field in INTEGER_FIELDS:
        if field not in output.columns:
            continue
        values: list[int | None] = []
        for raw, row_number in zip(output.get_column(field).to_list(), row_numbers, strict=True):
            if _is_blank(raw):
                issues.append(ValidationIssue("null_integer_value", f"{field} cannot be null", field=field, source_row_number=row_number))
                values.append(None)
            else:
                try:
                    values.append(int(raw))
                except (TypeError, ValueError):
                    issues.append(ValidationIssue("invalid_integer_value", f"{field} must be an integer", field=field, source_row_number=row_number))
                    values.append(None)
        output = output.with_columns(pl.Series(field, values, dtype=pl.Int64))
    for field in NUMERIC_FIELDS:
        if field not in output.columns:
            continue
        values_float: list[float | None] = []
        for raw, row_number in zip(output.get_column(field).to_list(), row_numbers, strict=True):
            if _is_blank(raw):
                issues.append(ValidationIssue("null_numeric_value", f"{field} cannot be null", field=field, source_row_number=row_number))
                values_float.append(None)
            else:
                try:
                    values_float.append(float(raw))
                except (TypeError, ValueError):
                    issues.append(ValidationIssue("invalid_numeric_value", f"{field} must be numeric", field=field, source_row_number=row_number))
                    values_float.append(None)
        output = output.with_columns(pl.Series(field, values_float, dtype=pl.Float64))
    for field in BOOLEAN_FIELDS:
        if field in output.columns:
            output = output.with_columns(pl.col(field).cast(pl.Boolean, strict=False))
    return output, ValidationReport(tuple(issues))