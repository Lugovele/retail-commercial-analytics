"""Structured data quality reporting contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

QualitySeverity = Literal["FATAL", "ERROR", "WARNING", "BUSINESS_EXCEPTION", "SUSPICIOUS"]


@dataclass(frozen=True)
class QualityIssue:
    """Machine-readable data quality issue with row-level trace references."""
    issue_code: str
    severity: QualitySeverity
    row_count: int
    affected_rows: tuple[int, ...] = field(default_factory=tuple)
    message: str = ""
    field: str | None = None

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ValueError("row_count must be non-negative")


@dataclass(frozen=True)
class QualityReport:
    """Structured data quality report for programmatic checks."""
    issues: tuple[QualityIssue, ...] = field(default_factory=tuple)

    @property
    def blocking_issues(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity in {"FATAL", "ERROR"})

    @property
    def warnings(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "WARNING")

    @property
    def is_valid(self) -> bool:
        return not self.blocking_issues

    def extend(self, other: QualityReport) -> QualityReport:
        return QualityReport((*self.issues, *other.issues))
