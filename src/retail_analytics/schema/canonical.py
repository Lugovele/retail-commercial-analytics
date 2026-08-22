"""Canonical sales schema for Slice 1A ingestion."""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

CONTEXT_COLUMNS = ("retailer_id", "source_id", "analysis_run_id")
PERIOD_COLUMNS = ("period", "year", "month")
IDENTITY_COLUMNS = ("source_store_id", "canonical_store_id", "source_sku_id", "canonical_product_id")
PRODUCT_COLUMNS = ("sku_name", "manufacturer", "brand", "category")
VALUE_COLUMNS = ("units", "revenue_vat")
TRACE_COLUMNS = ("source_row_number",)
REQUIRED_INPUT_COLUMNS = ("year", "month", "source_store_id", "source_sku_id", "units", "revenue_vat")
REQUIRED_STRING_COLUMNS = (*CONTEXT_COLUMNS, *IDENTITY_COLUMNS, *PRODUCT_COLUMNS)
REQUIRED_CANONICAL_COLUMNS = (*CONTEXT_COLUMNS, *PERIOD_COLUMNS, *IDENTITY_COLUMNS, *PRODUCT_COLUMNS, *VALUE_COLUMNS, *TRACE_COLUMNS)
OPTIONAL_CANONICAL_COLUMNS = ("store_format", "region", "subcategory", "subcategory_2", "volume_l", "volume_band", "package", "carbonation", "private_label_flag", "shelf_price_vat", "input_price_vat")
ALLOWED_CANONICAL_TARGETS = frozenset((*REQUIRED_CANONICAL_COLUMNS, *OPTIONAL_CANONICAL_COLUMNS))
CANONICAL_SCHEMA = {
    "retailer_id": pl.String, "source_id": pl.String, "analysis_run_id": pl.String,
    "period": pl.Date, "year": pl.Int64, "month": pl.Int64,
    "source_store_id": pl.String, "canonical_store_id": pl.String,
    "source_sku_id": pl.String, "canonical_product_id": pl.String,
    "sku_name": pl.String, "manufacturer": pl.String, "brand": pl.String, "category": pl.String,
    "units": pl.Float64, "revenue_vat": pl.Float64, "source_row_number": pl.Int64,
    "store_format": pl.String, "region": pl.String, "subcategory": pl.String, "subcategory_2": pl.String,
    "volume_l": pl.Float64, "volume_band": pl.String, "package": pl.String, "carbonation": pl.String,
    "private_label_flag": pl.Boolean, "shelf_price_vat": pl.Float64, "input_price_vat": pl.Float64,
}
CANDIDATE_GRAIN_COLUMNS = ("period", "retailer_id", "source_store_id", "source_sku_id")

@dataclass(frozen=True)
class CanonicalSchemaValidation:
    missing_columns: tuple[str, ...]
    unexpected_columns: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.missing_columns

def validate_canonical_columns(columns: list[str] | tuple[str, ...]) -> CanonicalSchemaValidation:
    present = set(columns)
    missing = tuple(column for column in REQUIRED_CANONICAL_COLUMNS if column not in present)
    unexpected = tuple(column for column in columns if column not in ALLOWED_CANONICAL_TARGETS)
    return CanonicalSchemaValidation(missing, unexpected)

def canonical_select_order(columns: list[str] | tuple[str, ...]) -> list[str]:
    present = set(columns)
    ordered = [column for column in REQUIRED_CANONICAL_COLUMNS if column in present]
    ordered.extend(column for column in OPTIONAL_CANONICAL_COLUMNS if column in present)
    return ordered