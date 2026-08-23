from __future__ import annotations

from datetime import date

import pytest

from retail_analytics.mart import (
    PrivateLabelScope,
    ShareMetric,
    calculate_active_sku_summary,
    calculate_category_share,
    compare_brand_to_category,
)


def test_category_share_recomputes_denominator_after_private_label_exclusion() -> None:
    include = calculate_category_share(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
        entity_grain="brand",
        entity_id="BRAND_NATIONAL",
        share_metric=ShareMetric.REVENUE,
        period_start=date(2025, 2, 1),
    )
    exclude = calculate_category_share(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
        entity_grain="brand",
        entity_id="BRAND_NATIONAL",
        share_metric=ShareMetric.REVENUE,
        period_start=date(2025, 2, 1),
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    assert include.value == pytest.approx(60.0 / 100.0)
    assert exclude.value == pytest.approx(1.0)
    assert exclude.denominator_value == 60.0


def test_active_sku_summary_uses_actual_available_periods_and_peak() -> None:
    result = calculate_active_sku_summary(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        current_period=date(2025, 4, 1),
        history_start=date(2025, 1, 1),
        history_end=date(2025, 4, 1),
        category="CATEGORY_STANDARD",
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    assert result.evaluated_periods == (
        date(2025, 1, 1),
        date(2025, 2, 1),
        date(2025, 3, 1),
        date(2025, 4, 1),
    )
    assert result.current_active_sku_count == 1
    assert result.historical_peak_active_sku_count == 2
    assert result.peak_period == date(2025, 1, 1)
    assert result.change_from_peak_pct == pytest.approx(-0.5)


def test_active_sku_summary_preserves_available_zero_active_period() -> None:
    result = calculate_active_sku_summary(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        current_period=date(2025, 3, 1),
        history_start=date(2025, 1, 1),
        history_end=date(2025, 4, 1),
        category="CATEGORY_STANDARD",
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    assert date(2025, 3, 1) in result.evaluated_periods
    assert result.current_active_sku_count == 0
    assert result.change_from_peak_pct == pytest.approx(-1.0)


def test_brand_vs_category_gap_is_percentage_points() -> None:
    result = compare_brand_to_category(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
        brand="BRAND_NATIONAL",
        metric="units",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    assert result.brand_delta_pct == pytest.approx(-0.3)
    assert result.category_delta_pct == pytest.approx(-0.1)
    assert result.gap_pp == pytest.approx(-0.2)
    assert result.status == "READY"


def test_brand_absence_in_available_current_period_is_zero_not_missing() -> None:
    result = compare_brand_to_category(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
        brand="BRAND_OTHER",
        metric="units",
        current_period=date(2025, 4, 1),
        reference_period=date(2025, 1, 1),
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    assert result.brand_current_value == 0.0
    assert result.brand_reference_value == 100.0
    assert result.brand_delta_pct == pytest.approx(-1.0)
    assert result.status == "READY"


def _frame():
    import polars as pl

    return pl.DataFrame(
        {
            "retailer_id": ["retailer_a"] * 9,
            "source_id": ["source_a"] * 9,
            "period": [
                date(2025, 1, 1),
                date(2025, 1, 1),
                date(2025, 1, 1),
                date(2025, 2, 1),
                date(2025, 2, 1),
                date(2025, 2, 1),
                date(2025, 3, 1),
                date(2025, 4, 1),
                date(2025, 4, 1),
            ],
            "category": ["CATEGORY_STANDARD"] * 9,
            "brand": [
                "BRAND_NATIONAL",
                "BRAND_OTHER",
                "BRAND_PRIVATE",
                "BRAND_NATIONAL",
                "BRAND_OTHER",
                "BRAND_PRIVATE",
                "BRAND_NATIONAL",
                "BRAND_NATIONAL",
                "BRAND_PRIVATE",
            ],
            "canonical_product_id": [
                "SKU_A_001",
                "SKU_A_002",
                "SKU_A_003",
                "SKU_A_001",
                "SKU_A_002",
                "SKU_A_003",
                "SKU_A_001",
                "SKU_A_001",
                "SKU_A_003",
            ],
            "private_label_flag": [False, False, True, False, False, True, False, False, True],
            "revenue_net": [100.0, 100.0, 25.0, 60.0, 0.0, 40.0, 0.0, 10.0, 90.0],
            "retailer_margin_abs": [10.0, 20.0, 5.0, 6.0, 0.0, 8.0, 0.0, 1.0, 18.0],
            "units": [100.0, 100.0, 10.0, 70.0, 110.0, 20.0, 0.0, 5.0, 30.0],
        }
    )
