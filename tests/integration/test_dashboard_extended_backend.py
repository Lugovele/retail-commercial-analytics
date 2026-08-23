from __future__ import annotations

from datetime import date

import pytest

from retail_analytics.mart import (
    MarketSegmentUniverse,
    PrivateLabelScope,
    ShareMetric,
    calculate_category_share,
    calculate_market_segment_delta,
    calculate_regional_summary,
    rank_manufacturers,
)


def test_extended_dashboard_projections_share_one_scope_contract() -> None:
    frame = _frame()

    rank_rows = rank_manufacturers(
        frame,
        retailer_id="retailer_a",
        source_id="source_a",
        metric="revenue_net",
        period_start=date(2025, 2, 1),
        category="CATEGORY_STANDARD",
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )
    category_share = calculate_category_share(
        frame,
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
        entity_grain="manufacturer",
        entity_id="MANUFACTURER_A",
        share_metric=ShareMetric.REVENUE,
        period_start=date(2025, 2, 1),
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )
    regions = calculate_regional_summary(
        frame,
        retailer_id="retailer_a",
        source_id="source_a",
        period_start=date(2025, 2, 1),
        category="CATEGORY_STANDARD",
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )
    market = calculate_market_segment_delta(
        frame,
        universe=MarketSegmentUniverse.MARKET_EX_PRIVATE_LABEL,
        metric="revenue_net",
        current_period=date(2025, 2, 1),
        reference_period=date(2025, 1, 1),
        retailer_id="retailer_a",
        source_id="source_a",
        category="CATEGORY_STANDARD",
    )

    assert {row.manufacturer for row in rank_rows} == {"MANUFACTURER_A", "MANUFACTURER_B"}
    assert category_share.value == pytest.approx(80.0 / 120.0)
    assert sum(row.revenue_net for row in regions) == 120.0
    assert market.current_value == 120.0
    assert market.reference_value == 100.0


def _frame():
    import polars as pl

    return pl.DataFrame(
        {
            "retailer_id": ["retailer_a"] * 6,
            "source_id": ["source_a"] * 6,
            "period": [
                date(2025, 1, 1),
                date(2025, 1, 1),
                date(2025, 1, 1),
                date(2025, 2, 1),
                date(2025, 2, 1),
                date(2025, 2, 1),
            ],
            "category": ["CATEGORY_STANDARD"] * 6,
            "manufacturer": [
                "MANUFACTURER_A",
                "MANUFACTURER_B",
                "MANUFACTURER_PL",
                "MANUFACTURER_A",
                "MANUFACTURER_B",
                "MANUFACTURER_PL",
            ],
            "brand": ["BRAND_A", "BRAND_B", "BRAND_PL", "BRAND_A", "BRAND_B", "BRAND_PL"],
            "canonical_product_id": ["SKU_A_001", "SKU_A_002", "SKU_A_003"] * 2,
            "region": ["REGION_A", "REGION_B", "REGION_A", "REGION_A", "REGION_B", "REGION_A"],
            "private_label_flag": [False, False, True, False, False, True],
            "revenue_net": [60.0, 40.0, 50.0, 80.0, 40.0, 10.0],
            "units": [6.0, 4.0, 5.0, 8.0, 4.0, 1.0],
            "retailer_margin_abs": [12.0, 8.0, 10.0, 16.0, 8.0, 2.0],
        }
    )
