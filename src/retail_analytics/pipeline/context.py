"""Analysis run context."""
from __future__ import annotations

from dataclasses import dataclass


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()

@dataclass(frozen=True)
class AnalysisContext:
    """Immutable metadata for one ingestion or analysis run."""
    analysis_run_id: str
    retailer_id: str
    source_id: str
    source_version: str
    rule_version: str

    def __post_init__(self) -> None:
        for field_name in ("analysis_run_id", "retailer_id", "source_id", "source_version", "rule_version"):
            object.__setattr__(self, field_name, _require_non_empty(field_name, getattr(self, field_name)))