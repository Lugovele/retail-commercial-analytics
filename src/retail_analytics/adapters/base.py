"""Source adapter contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import polars as pl

from retail_analytics.normalization.columns import ColumnMapping
from retail_analytics.normalization.stores import StoreAliasMapping, normalize_store_aliases
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.schema.canonical import REQUIRED_INPUT_COLUMNS
from retail_analytics.schema.validation import ValidationIssue, ValidationReport


@dataclass(frozen=True)
class AdapterResult:
    canonical_frame: pl.DataFrame
    validation_report: ValidationReport

class SourceAdapter(Protocol):
    """Adapter interface for mapping raw source tables to canonical-shaped rows."""
    def to_canonical(
        self,
        raw_source: pl.DataFrame,
        mapping: ColumnMapping,
        context: AnalysisContext,
        *,
        store_aliases: StoreAliasMapping | None = None,
    ) -> AdapterResult:
        """Return canonical-shaped data without mutating raw_source."""

class ConfiguredSourceAdapter:
    """Generic config-driven source adapter."""
    def to_canonical(
        self,
        raw_source: pl.DataFrame,
        mapping: ColumnMapping,
        context: AnalysisContext,
        *,
        store_aliases: StoreAliasMapping | None = None,
    ) -> AdapterResult:
        issues: list[ValidationIssue] = list(mapping.validate().issues)
        mapped_source_columns = set(mapping.source_columns)
        allowed_unmapped = set(mapping.allowed_unmapped_source_columns)
        for column in [column for column in mapping.source_columns if column not in raw_source.columns]:
            issues.append(ValidationIssue("missing_source_column", f"Source column is missing: {column}", source_column=column))
        for column in [column for column in raw_source.columns if column not in mapped_source_columns and column not in allowed_unmapped]:
            issues.append(ValidationIssue("unmapped_source_column", f"Source column is not mapped: {column}", source_column=column))
        if any(issue.severity == "fatal" for issue in issues):
            return AdapterResult(pl.DataFrame(), ValidationReport(tuple(issues)))
        selected = raw_source.select(list(mapping.source_columns)).rename(mapping.columns)
        selected, semantic_report = _apply_semantic_value_maps(selected, mapping)
        issues.extend(semantic_report.issues)
        for required in REQUIRED_INPUT_COLUMNS:
            if required not in selected.columns:
                issues.append(ValidationIssue("missing_required_column", f"Canonical column is missing: {required}", field=required))
        if any(issue.severity == "fatal" for issue in issues):
            return AdapterResult(pl.DataFrame(), ValidationReport(tuple(issues)))
        canonical = selected.with_columns(
            pl.lit(context.retailer_id).alias("retailer_id"),
            pl.lit(context.source_id).alias("source_id"),
            pl.lit(context.analysis_run_id).alias("analysis_run_id"),
            pl.col("source_store_id").cast(pl.String, strict=False).alias("canonical_store_id"),
            pl.col("source_sku_id").cast(pl.String, strict=False).alias("canonical_product_id"),
            pl.int_range(1, pl.len() + 1, eager=False).alias("source_row_number"),
        )
        canonical = normalize_store_aliases(canonical, store_aliases, context)
        return AdapterResult(canonical, ValidationReport(tuple(issues)))


def _apply_semantic_value_maps(frame: pl.DataFrame, mapping: ColumnMapping) -> tuple[pl.DataFrame, ValidationReport]:
    if not mapping.semantic_value_maps:
        return frame, ValidationReport()
    issues: list[ValidationIssue] = []
    output = frame
    row_numbers = list(range(1, frame.height + 1))
    for field, value_map in mapping.semantic_value_maps.items():
        if field not in output.columns:
            continue
        mapped_values: list[object] = []
        for raw, row_number in zip(output.get_column(field).to_list(), row_numbers, strict=True):
            if raw is None:
                mapped_values.append(None)
                continue
            if raw in value_map:
                mapped_values.append(value_map[raw])
                continue
            issues.append(ValidationIssue("unknown_semantic_value", f"Unknown semantic value for {field}", field=field, source_row_number=row_number))
            mapped_values.append(None)
        output = output.with_columns(pl.Series(field, mapped_values))
    return output, ValidationReport(tuple(issues))
