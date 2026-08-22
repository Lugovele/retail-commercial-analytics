"""Structured validation primitives for ingestion."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["fatal", "warning"]

@dataclass(frozen=True)
class ValidationIssue:
    """Machine-readable validation issue."""
    code: str
    message: str
    severity: Severity = "fatal"
    field: str | None = None
    source_column: str | None = None
    source_row_number: int | None = None

@dataclass(frozen=True)
class ValidationReport:
    """Validation result with fatal errors and warnings separated by severity."""
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def fatal_errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "fatal")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def is_valid(self) -> bool:
        return not self.fatal_errors

class ValidationError(Exception):
    """Raised when fatal validation issues prevent ingestion from continuing."""
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        message = "; ".join(issue.message for issue in report.fatal_errors) or "validation failed"
        super().__init__(message)

def raise_if_fatal(report: ValidationReport) -> None:
    if not report.is_valid:
        raise ValidationError(report)