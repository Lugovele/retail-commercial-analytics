from __future__ import annotations

from datetime import date

import pytest

from retail_analytics.mart import UNKNOWN_REGION, PrivateLabelScope, calculate_regional_summary


def test_regional_summary_sums_range_and_recomputes_share() -> None:
    rows = calculate_regional_summary(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 2, 1),
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    by_region = {row.region: row for row in rows}
    assert by_region["REGION_A"].revenue_net == 90.0
    assert by_region["REGION_B"].revenue_net == 30.0
    assert by_region["REGION_A"].regional_share_revenue == pytest.approx(90.0 / 120.0)
    assert sum(row.revenue_net for row in rows) == 120.0


def test_regional_summary_handles_unknown_region_and_scope_isolation() -> None:
    rows = calculate_regional_summary(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 2, 1),
    )

    by_region = {row.region: row for row in rows}
    assert UNKNOWN_REGION in by_region
    assert by_region[UNKNOWN_REGION].revenue_net == 40.0
    assert all(row.private_label_scope == PrivateLabelScope.INCLUDE for row in rows)
    assert sum(row.revenue_net for row in rows) == 200.0


def _frame():
    import polars as pl

    return pl.DataFrame(
        {
            "retailer_id": ["retailer_a"] * 5 + ["retailer_b"],
            "source_id": ["source_a"] * 6,
            "period": [
                date(2025, 1, 1),
                date(2025, 1, 1),
                date(2025, 2, 1),
                date(2025, 2, 1),
                date(2025, 2, 1),
                date(2025, 1, 1),
            ],
            "category": ["CATEGORY_STANDARD"] * 6,
            "region": ["REGION_A", "REGION_B", "REGION_A", "REGION_B", None, "REGION_A"],
            "private_label_flag": [False, False, False, True, True, False],
            "revenue_net": [60.0, 30.0, 30.0, 40.0, 40.0, 999.0],
            "units": [6.0, 3.0, 3.0, 4.0, 4.0, 99.0],
            "retailer_margin_abs": [12.0, 6.0, 6.0, 8.0, 8.0, 99.0],
        }
    )
