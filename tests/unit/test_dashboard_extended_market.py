from __future__ import annotations

from datetime import date

import pytest

from retail_analytics.mart import (
    DeltaStatus,
    MarketSegmentUniverse,
    calculate_decline_speed_ratio,
    calculate_market_segment_delta,
    private_label_growth_while_portfolio_declines,
)


def test_market_segment_delta_filters_private_label_universe() -> None:
    market = calculate_market_segment_delta(
        _frame(),
        universe=MarketSegmentUniverse.MARKET_EX_PRIVATE_LABEL,
        metric="units",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
    )
    private_label = calculate_market_segment_delta(
        _frame(),
        universe=MarketSegmentUniverse.PRIVATE_LABEL,
        metric="units",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
    )

    assert market.reference_value == 100.0
    assert market.current_value == 80.0
    assert market.delta_pct == pytest.approx(-0.2)
    assert private_label.reference_value == 20.0
    assert private_label.current_value == 30.0
    assert private_label.delta_pct == pytest.approx(0.5)


def test_decline_speed_ratio_is_only_ready_for_double_decline() -> None:
    own = calculate_market_segment_delta(
        _frame(),
        universe=MarketSegmentUniverse.OWN_PORTFOLIO,
        metric="units",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
    )
    market = calculate_market_segment_delta(
        _frame(),
        universe=MarketSegmentUniverse.MARKET_EX_PRIVATE_LABEL,
        metric="units",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
    )

    result = calculate_decline_speed_ratio(own_delta=own, market_delta=market)

    assert result.status == "READY"
    assert result.ratio == pytest.approx(2.0)


def test_private_label_growth_pattern_is_neutral_and_structured() -> None:
    private_label = calculate_market_segment_delta(
        _frame(),
        universe=MarketSegmentUniverse.PRIVATE_LABEL,
        metric="units",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
    )
    own = calculate_market_segment_delta(
        _frame(),
        universe=MarketSegmentUniverse.OWN_PORTFOLIO,
        metric="units",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
    )

    signal = private_label_growth_while_portfolio_declines(private_label_delta=private_label, portfolio_delta=own)

    assert signal.signal_code == "PRIVATE_LABEL_GROWTH_WHILE_PORTFOLIO_DECLINES"
    assert signal.status == "DETECTED"
    assert signal.evidence["private_label_delta_pct"] == pytest.approx(0.5)


def test_zero_reference_denominator_is_structured() -> None:
    result = calculate_market_segment_delta(
        _frame(),
        universe=MarketSegmentUniverse.TOTAL_MARKET,
        metric="units",
        current_period=date(2025, 3, 1),
        reference_period=date(2025, 4, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
    )

    assert result.status == DeltaStatus.ZERO_REFERENCE_DENOMINATOR
    assert result.delta_pct is None


def test_segment_absence_in_available_period_is_zero_not_missing() -> None:
    result = calculate_market_segment_delta(
        _frame(),
        universe=MarketSegmentUniverse.PRIVATE_LABEL,
        metric="units",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_NEW_PRIVATE_LABEL",
    )

    assert result.current_value == 5.0
    assert result.reference_value == 0.0
    assert result.delta_abs == 5.0
    assert result.status == DeltaStatus.ZERO_REFERENCE_DENOMINATOR


def test_market_segment_delta_rejects_non_additive_metric() -> None:
    with pytest.raises(ValueError, match="Unsupported market segment delta metric"):
        calculate_market_segment_delta(
            _frame(),
            universe=MarketSegmentUniverse.TOTAL_MARKET,
            metric="retailer_margin_pct",
            current_period=date(2025, 2, 1),
            reference_period=date(2025, 1, 1),
            retailer_id="retailer_a",
            source_id="source_a",
            category="CATEGORY_STANDARD",
        )


def _frame():
    import polars as pl

    return pl.DataFrame(
        {
            "retailer_id": ["retailer_a"] * 10 + ["retailer_b"],
            "source_id": ["source_a"] * 11,
            "period": [
                date(2025, 1, 1),
                date(2025, 1, 1),
                date(2025, 2, 1),
                date(2025, 2, 1),
                date(2025, 1, 1),
                date(2025, 2, 1),
                date(2025, 3, 1),
                date(2025, 4, 1),
                date(2025, 1, 1),
                date(2025, 2, 1),
                date(2025, 2, 1),
            ],
            "category": ["CATEGORY_STANDARD"] * 8
            + ["CATEGORY_NEW_PRIVATE_LABEL", "CATEGORY_NEW_PRIVATE_LABEL", "CATEGORY_STANDARD"],
            "private_label_flag": [False, False, False, False, True, True, False, False, False, True, False],
            "is_own_product": [True, False, True, False, False, False, False, False, False, False, True],
            "units": [50.0, 50.0, 30.0, 50.0, 20.0, 30.0, 10.0, 0.0, 10.0, 5.0, 999.0],
        }
    )
