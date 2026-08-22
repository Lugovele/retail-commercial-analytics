"""Generic commercial event vocabulary."""
from __future__ import annotations

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "MATERIAL_REVENUE_GROWTH",
        "MATERIAL_REVENUE_DECLINE",
        "MATERIAL_UNITS_GROWTH",
        "MATERIAL_UNITS_DECLINE",
        "MATERIAL_MARGIN_GROWTH",
        "MATERIAL_MARGIN_DECLINE",
        "DISTRIBUTION_GAIN",
        "DISTRIBUTION_LOSS",
        "VELOCITY_GAIN",
        "VELOCITY_LOSS",
        "STABLE_VELOCITY",
        "SHARE_GAIN",
        "SHARE_LOSS",
        "PRICE_INCREASE",
        "PRICE_DECREASE",
        "MARGIN_PCT_GAIN",
        "MARGIN_PCT_EROSION",
        "ABC_CLASS_CHANGE",
        "PERSISTENT_C_CLASS",
        "STABLE_SKU",
        "PEER_OUTPERFORMANCE",
        "PEER_UNDERPERFORMANCE",
        "HIGH_VELOCITY_LOW_DISTRIBUTION",
        "LOW_VELOCITY_HIGH_DISTRIBUTION",
        "PRICE_POWER_PATTERN",
        "PRICE_PRESSURE_PATTERN",
        "PROMO_LIKE_PATTERN",
    }
)

EVENT_FAMILIES: frozenset[str] = frozenset(
    {
        "GROWTH_DECLINE",
        "DISTRIBUTION",
        "VELOCITY",
        "SHARE",
        "PRICE",
        "MARGIN_PCT",
        "PORTFOLIO",
        "BENCHMARK",
        "PATTERN_CANDIDATE",
    }
)
