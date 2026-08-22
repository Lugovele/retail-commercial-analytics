"""Analytical period index helpers."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PeriodIndex:
    available_periods: tuple[date, ...]

    def previous_available_period(self, period: date) -> date | None:
        earlier = [candidate for candidate in self.available_periods if candidate < period]
        return earlier[-1] if earlier else None

    def previous_calendar_month(self, period: date) -> date:
        year = period.year - 1 if period.month == 1 else period.year
        month = 12 if period.month == 1 else period.month - 1
        return date(year, month, 1)

    def same_month_previous_year(self, period: date) -> date:
        return date(period.year - 1, period.month, 1)

    def month_gap(self, current_period: date, base_period: date) -> int:
        return (current_period.year - base_period.year) * 12 + current_period.month - base_period.month


def build_period_index(periods: Iterable[date]) -> PeriodIndex:
    return PeriodIndex(tuple(sorted(set(periods))))
