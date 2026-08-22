"""Data quality and reconciliation checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import polars as pl

from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport

ReconciliationStatus = Literal["PASS", "FAIL"]


@dataclass(frozen=True)
class ReconciliationCheck:
    check_id: str
    status: ReconciliationStatus
    expected: float | int | str
    actual: float | int | str
    delta: float
    tolerance: float


@dataclass(frozen=True)
class ReconciliationResult:
    checks: tuple[ReconciliationCheck, ...]
    quality_report: QualityReport

    @property
    def is_valid(self) -> bool:
        return all(check.status == "PASS" for check in self.checks) and self.quality_report.is_valid


def run_quality_checks(
    frame: pl.DataFrame,
    context: AnalysisContext,
    *,
    include_optional_price_checks: bool = True,
) -> QualityReport:
    """Classify Slice 1B data quality issues without repairing rows."""
    del context
    issues: list[QualityIssue] = []
    issues.extend(_sign_issues(frame))
    if include_optional_price_checks:
        issues.extend(_missing_optional_price_issues(frame, "input_price_net", "missing_input_price"))
        issues.extend(_missing_optional_price_issues(frame, "shelf_price_net", "missing_shelf_price"))
    return QualityReport(tuple(issues))


def reconcile_economics(
    source_frame: pl.DataFrame,
    enriched_frame: pl.DataFrame,
    context: AnalysisContext,
    *,
    tolerance: float = 1e-9,
) -> ReconciliationResult:
    """Verify enrichment preserves rows, additive totals, and source traceability."""
    del context
    checks = (
        _sum_check("preserve_revenue_vat_total", source_frame, enriched_frame, "revenue_vat", tolerance),
        _sum_check("preserve_units_total", source_frame, enriched_frame, "units", tolerance),
        _row_count_check(source_frame, enriched_frame),
        _traceability_check(source_frame, enriched_frame),
    )
    issues = tuple(
        QualityIssue(check.check_id, "ERROR", 0, (), f"Reconciliation check failed: {check.check_id}")
        for check in checks
        if check.status == "FAIL"
    )
    return ReconciliationResult(checks, QualityReport(issues))


def _sign_issues(frame: pl.DataFrame) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for row_number, row in enumerate(frame.to_dicts()):
        units = row.get("units")
        revenue = row.get("revenue_vat")
        trace = _trace(row, row_number)
        if units is None or revenue is None:
            continue
        if units < 0 and revenue < 0:
            issues.append(QualityIssue("negative_units_negative_revenue", "BUSINESS_EXCEPTION", 1, (trace,), "Negative correction row is preserved."))
        elif units > 0 and revenue < 0:
            issues.append(QualityIssue("positive_units_negative_revenue", "SUSPICIOUS", 1, (trace,), "Positive units with negative revenue."))
        elif units < 0 and revenue > 0:
            issues.append(QualityIssue("negative_units_positive_revenue", "SUSPICIOUS", 1, (trace,), "Negative units with positive revenue."))
    return issues


def _missing_optional_price_issues(frame: pl.DataFrame, column: str, code: str) -> list[QualityIssue]:
    if column not in frame.columns:
        return [QualityIssue(code, "WARNING", frame.height, (), f"{column} is not available.", column)]
    issues: list[QualityIssue] = []
    for row_number, row in enumerate(frame.to_dicts()):
        if row.get(column) is None:
            issues.append(QualityIssue(code, "WARNING", 1, (_trace(row, row_number),), f"{column} is missing.", column))
    return issues


def _sum_check(check_id: str, source_frame: pl.DataFrame, enriched_frame: pl.DataFrame, column: str, tolerance: float) -> ReconciliationCheck:
    expected = float(source_frame.get_column(column).sum())
    actual = float(enriched_frame.get_column(column).sum())
    delta = actual - expected
    status: ReconciliationStatus = "PASS" if abs(delta) <= tolerance else "FAIL"
    return ReconciliationCheck(check_id, status, expected, actual, delta, tolerance)


def _row_count_check(source_frame: pl.DataFrame, enriched_frame: pl.DataFrame) -> ReconciliationCheck:
    expected = source_frame.height
    actual = enriched_frame.height
    delta = float(actual - expected)
    status: ReconciliationStatus = "PASS" if expected == actual else "FAIL"
    return ReconciliationCheck("preserve_row_count", status, expected, actual, delta, 0.0)


def _traceability_check(source_frame: pl.DataFrame, enriched_frame: pl.DataFrame) -> ReconciliationCheck:
    expected = _trace_values(source_frame)
    actual = _trace_values(enriched_frame)
    status: ReconciliationStatus = "PASS" if expected == actual else "FAIL"
    delta = 0.0 if status == "PASS" else 1.0
    return ReconciliationCheck("preserve_source_row_traceability", status, ",".join(expected), ",".join(actual), delta, 0.0)


def _trace_values(frame: pl.DataFrame) -> tuple[str, ...]:
    if "source_row_number" not in frame.columns:
        return ()
    return tuple(str(value) for value in frame.get_column("source_row_number").to_list())


def _trace(row: dict[str, Any], fallback: int) -> int:
    value = row.get("source_row_number")
    return int(value) if isinstance(value, int) else fallback
