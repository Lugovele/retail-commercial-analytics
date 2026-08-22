"""Period normalization helpers."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import polars as pl

from retail_analytics.schema.validation import ValidationIssue, ValidationReport


def _parse_month(value: object, month_names: Mapping[str, int] | None = None) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if month_names and stripped in month_names:
            return month_names[stripped]
        try:
            return int(stripped)
        except ValueError:
            return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

def normalize_period(frame: pl.DataFrame, *, month_names: Mapping[str, int] | None = None) -> tuple[pl.DataFrame, ValidationReport]:
    """Add normalized month-start period from year and month columns."""
    issues: list[ValidationIssue] = []
    periods: list[date | None] = []
    years = frame.get_column("year").to_list()
    months = frame.get_column("month").to_list()
    row_numbers = frame.get_column("source_row_number").to_list() if "source_row_number" in frame.columns else list(range(1, frame.height + 1))
    for year_value, month_value, row_number in zip(years, months, row_numbers, strict=True):
        try:
            year = int(year_value)
        except (TypeError, ValueError):
            issues.append(ValidationIssue("invalid_year", "Year must be coercible to an integer", field="year", source_row_number=int(row_number)))
            periods.append(None)
            continue
        month = _parse_month(month_value, month_names)
        if month is None or not 1 <= month <= 12:
            issues.append(ValidationIssue("invalid_month", "Month must be between 1 and 12", field="month", source_row_number=int(row_number)))
            periods.append(None)
            continue
        periods.append(date(year, month, 1))
    return frame.with_columns(pl.Series("period", periods, dtype=pl.Date)), ValidationReport(tuple(issues))