"""Config-driven source column mapping."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from retail_analytics.schema.canonical import ALLOWED_CANONICAL_TARGETS, REQUIRED_INPUT_COLUMNS
from retail_analytics.schema.validation import ValidationIssue, ValidationReport


@dataclass(frozen=True)
class ColumnMapping:
    """Mapping from source-specific fields to canonical target names."""
    columns: dict[str, str]
    mapping_id: str | None = None
    version: str | None = None

    def validate(self) -> ValidationReport:
        issues: list[ValidationIssue] = []
        target_to_sources: dict[str, list[str]] = {}
        for source_column, target in self.columns.items():
            if target not in ALLOWED_CANONICAL_TARGETS:
                issues.append(ValidationIssue("unknown_canonical_target", f"Unknown canonical target: {target}", field=target, source_column=source_column))
            target_to_sources.setdefault(target, []).append(source_column)
        for required_target in REQUIRED_INPUT_COLUMNS:
            if required_target not in target_to_sources:
                issues.append(ValidationIssue("missing_required_mapping", f"Missing required mapping for {required_target}", field=required_target))
        for target, sources in target_to_sources.items():
            if len(sources) > 1:
                issues.append(ValidationIssue("duplicate_target_mapping", f"Multiple source columns map to {target}", field=target))
        return ValidationReport(tuple(issues))

    @property
    def source_columns(self) -> tuple[str, ...]:
        return tuple(self.columns.keys())

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.columns, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

def load_column_mapping(path: str | Path) -> ColumnMapping:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw_columns = payload.get("columns", payload.get("mapping", {}))
    if not isinstance(raw_columns, dict):
        return ColumnMapping(columns={})
    return ColumnMapping(
        columns={str(source): str(target) for source, target in raw_columns.items()},
        mapping_id=payload.get("mapping_id"),
        version=payload.get("version"),
    )