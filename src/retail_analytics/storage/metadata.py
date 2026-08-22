"""Ingestion metadata contracts."""
from __future__ import annotations

from dataclasses import dataclass

from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.schema.validation import ValidationReport
from retail_analytics.storage.profile import SourceProfile


@dataclass(frozen=True)
class IngestionMetadata:
    context: AnalysisContext
    source_row_count: int
    canonical_row_count: int
    mapping_id: str | None
    mapping_version: str | None
    mapping_config_hash: str
    validation_status: str

    def __post_init__(self) -> None:
        if not self.mapping_config_hash:
            raise ValueError("mapping_config_hash must be present")
        if not ((self.mapping_id and self.mapping_version) or self.mapping_config_hash):
            raise ValueError("mapping id/version or mapping_config_hash must be present")

@dataclass(frozen=True)
class Slice1AResult:
    context: AnalysisContext
    canonical_data_path: str
    source_profile: SourceProfile
    validation_report: ValidationReport
    metadata: IngestionMetadata