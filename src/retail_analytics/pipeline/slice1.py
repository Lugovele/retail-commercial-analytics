"""Thin Slice 1A canonical ingestion orchestrator."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from retail_analytics.adapters.base import ConfiguredSourceAdapter, SourceAdapter
from retail_analytics.normalization.columns import ColumnMapping, load_column_mapping
from retail_analytics.normalization.periods import normalize_period
from retail_analytics.normalization.values import normalize_types
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.schema.canonical import canonical_select_order, validate_canonical_columns
from retail_analytics.schema.validation import ValidationIssue, ValidationReport, raise_if_fatal
from retail_analytics.storage.metadata import IngestionMetadata, Slice1AResult
from retail_analytics.storage.parquet import write_canonical_parquet
from retail_analytics.storage.profile import profile_canonical_source


def _merge_reports(*reports: ValidationReport) -> ValidationReport:
    return ValidationReport(tuple(issue for report in reports for issue in report.issues))

def _canonical_schema_report(frame: pl.DataFrame) -> ValidationReport:
    validation = validate_canonical_columns(frame.columns)
    issues = [ValidationIssue("missing_canonical_column", f"Canonical column is missing: {column}", field=column) for column in validation.missing_columns]
    issues.extend(ValidationIssue("unexpected_canonical_column", f"Unexpected canonical column: {column}", severity="warning", field=column) for column in validation.unexpected_columns)
    return ValidationReport(tuple(issues))

def run_slice1a_ingestion(*, raw_source: pl.DataFrame, mapping: ColumnMapping | str | Path, context: AnalysisContext, output_path: str | Path, adapter: SourceAdapter | None = None) -> Slice1AResult:
    """Map, normalize, validate, profile, and persist a canonical Slice 1A dataset."""
    resolved_mapping = load_column_mapping(mapping) if isinstance(mapping, (str, Path)) else mapping
    source_adapter = adapter or ConfiguredSourceAdapter()
    adapter_result = source_adapter.to_canonical(raw_source, resolved_mapping, context)
    raise_if_fatal(adapter_result.validation_report)
    typed_frame, type_report = normalize_types(adapter_result.canonical_frame)
    period_frame, period_report = normalize_period(typed_frame)
    schema_report = _canonical_schema_report(period_frame)
    validation_report = _merge_reports(adapter_result.validation_report, type_report, period_report, schema_report)
    raise_if_fatal(validation_report)
    canonical_frame = period_frame.select(canonical_select_order(period_frame.columns))
    source_profile = profile_canonical_source(canonical_frame)
    parquet_path = write_canonical_parquet(canonical_frame, output_path)
    metadata = IngestionMetadata(
        context=context,
        source_row_count=raw_source.height,
        canonical_row_count=canonical_frame.height,
        mapping_id=resolved_mapping.mapping_id,
        mapping_version=resolved_mapping.version,
        mapping_config_hash=resolved_mapping.config_hash,
        validation_status="valid" if validation_report.is_valid else "invalid",
    )
    return Slice1AResult(context, str(parquet_path), source_profile, validation_report, metadata)