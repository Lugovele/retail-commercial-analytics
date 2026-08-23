"""Market-segment comparison universes for dashboard projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import polars as pl

from retail_analytics.mart.scopes import PrivateLabelScope, apply_private_label_scope

APPROVED_MARKET_DELTA_METRICS = frozenset({"revenue_net", "revenue_vat", "units"})


class MarketSegmentUniverse(StrEnum):
    """Explicit analytical sub-universes for market-vs-portfolio comparisons."""

    TOTAL_MARKET = "TOTAL_MARKET"
    MARKET_EX_PRIVATE_LABEL = "MARKET_EX_PRIVATE_LABEL"
    PRIVATE_LABEL = "PRIVATE_LABEL"
    OWN_PORTFOLIO = "OWN_PORTFOLIO"


class DeltaStatus(StrEnum):
    """Structured status for period delta calculations."""

    READY = "READY"
    ZERO_REFERENCE_DENOMINATOR = "ZERO_REFERENCE_DENOMINATOR"
    MISSING_PERIOD = "MISSING_PERIOD"
    UNSUPPORTED_UNIVERSE = "UNSUPPORTED_UNIVERSE"


@dataclass(frozen=True)
class MarketSegmentDelta:
    """Current/reference delta for one market segment and metric."""

    universe: MarketSegmentUniverse
    metric: str
    current_period: date
    reference_period: date
    current_value: float | None
    reference_value: float | None
    delta_abs: float | None
    delta_pct: float | None
    status: DeltaStatus
    limitation: str | None = None


@dataclass(frozen=True)
class DeclineSpeedResult:
    """Safe comparison of own decline pace against a market benchmark."""

    metric: str
    own_delta_pct: float | None
    market_delta_pct: float | None
    ratio: float | None
    status: str
    limitation: str | None = None


@dataclass(frozen=True)
class ComparativePatternSignal:
    """Deterministic market-vs-portfolio pattern signal."""

    signal_code: str
    metric: str
    current_period: date
    reference_period: date
    status: str
    evidence: dict[str, float | None]
    limitation: str | None = None


def filter_market_universe(frame: pl.DataFrame, universe: MarketSegmentUniverse | str) -> pl.DataFrame:
    """Return rows in the requested explicit comparison universe."""

    selected = MarketSegmentUniverse(universe)
    if selected == MarketSegmentUniverse.TOTAL_MARKET:
        return frame.clone()
    if selected == MarketSegmentUniverse.MARKET_EX_PRIVATE_LABEL:
        return apply_private_label_scope(frame, PrivateLabelScope.EXCLUDE).frame
    if selected == MarketSegmentUniverse.PRIVATE_LABEL:
        return apply_private_label_scope(frame, PrivateLabelScope.ONLY).frame
    if "is_own_product" not in frame.columns:
        raise ValueError("is_own_product is required for OWN_PORTFOLIO universe")
    return frame.filter(pl.col("is_own_product") == True)


def calculate_market_segment_delta(
    frame: pl.DataFrame,
    *,
    universe: MarketSegmentUniverse | str,
    metric: str,
    current_period: date,
    reference_period: date,
    retailer_id: str,
    source_id: str,
    category: str | None = None,
) -> MarketSegmentDelta:
    """Calculate one safe current/reference segment delta."""

    selected = MarketSegmentUniverse(universe)
    if metric not in APPROVED_MARKET_DELTA_METRICS:
        raise ValueError(f"Unsupported market segment delta metric: {metric}")
    base_scope = _scope_frame(frame, retailer_id, source_id, category)
    try:
        scoped = filter_market_universe(base_scope, selected)
    except ValueError as exc:
        return MarketSegmentDelta(
            selected,
            metric,
            current_period,
            reference_period,
            None,
            None,
            None,
            None,
            DeltaStatus.UNSUPPORTED_UNIVERSE,
            str(exc),
        )
    if metric not in scoped.columns:
        raise ValueError(f"Metric column is missing: {metric}")
    current_value = _sum_period(scoped, metric, current_period, availability_frame=base_scope)
    reference_value = _sum_period(scoped, metric, reference_period, availability_frame=base_scope)
    if current_value is None or reference_value is None:
        return MarketSegmentDelta(
            selected,
            metric,
            current_period,
            reference_period,
            current_value,
            reference_value,
            None,
            None,
            DeltaStatus.MISSING_PERIOD,
            "Current or reference period has no rows in the selected universe",
        )
    delta_abs = current_value - reference_value
    if reference_value == 0:
        return MarketSegmentDelta(
            selected,
            metric,
            current_period,
            reference_period,
            current_value,
            reference_value,
            delta_abs,
            None,
            DeltaStatus.ZERO_REFERENCE_DENOMINATOR,
            "Reference period denominator is zero",
        )
    return MarketSegmentDelta(
        selected,
        metric,
        current_period,
        reference_period,
        current_value,
        reference_value,
        delta_abs,
        delta_abs / reference_value,
        DeltaStatus.READY,
    )


def calculate_decline_speed_ratio(
    *,
    own_delta: MarketSegmentDelta,
    market_delta: MarketSegmentDelta,
) -> DeclineSpeedResult:
    """Return ratio only when both deltas are valid declines."""

    if own_delta.metric != market_delta.metric:
        raise ValueError("Decline speed ratio requires matching metrics")
    if own_delta.status != DeltaStatus.READY or market_delta.status != DeltaStatus.READY:
        return DeclineSpeedResult(own_delta.metric, own_delta.delta_pct, market_delta.delta_pct, None, "NOT_APPLICABLE")
    if own_delta.delta_pct is None or market_delta.delta_pct is None:
        return DeclineSpeedResult(own_delta.metric, own_delta.delta_pct, market_delta.delta_pct, None, "NOT_APPLICABLE")
    if own_delta.delta_pct >= 0 or market_delta.delta_pct >= 0:
        return DeclineSpeedResult(
            own_delta.metric,
            own_delta.delta_pct,
            market_delta.delta_pct,
            None,
            "NOT_A_DOUBLE_DECLINE",
            "Ratio is emitted only when both own and market deltas are negative",
        )
    if market_delta.delta_pct == 0:
        return DeclineSpeedResult(
            own_delta.metric,
            own_delta.delta_pct,
            market_delta.delta_pct,
            None,
            "ZERO_MARKET_DECLINE",
        )
    return DeclineSpeedResult(
        own_delta.metric,
        own_delta.delta_pct,
        market_delta.delta_pct,
        abs(own_delta.delta_pct) / abs(market_delta.delta_pct),
        "READY",
    )


def private_label_growth_while_portfolio_declines(
    *,
    private_label_delta: MarketSegmentDelta,
    portfolio_delta: MarketSegmentDelta,
) -> ComparativePatternSignal:
    """Detect the neutral private-label-growth/portfolio-decline pattern."""

    if private_label_delta.metric != portfolio_delta.metric:
        raise ValueError("Pattern detection requires matching metrics")
    evidence = {
        "private_label_delta_pct": private_label_delta.delta_pct,
        "portfolio_delta_pct": portfolio_delta.delta_pct,
    }
    if private_label_delta.status != DeltaStatus.READY or portfolio_delta.status != DeltaStatus.READY:
        return ComparativePatternSignal(
            "PRIVATE_LABEL_GROWTH_WHILE_PORTFOLIO_DECLINES",
            private_label_delta.metric,
            private_label_delta.current_period,
            private_label_delta.reference_period,
            "NOT_APPLICABLE",
            evidence,
            "Both segment deltas must be READY",
        )
    detected = (
        private_label_delta.delta_pct is not None
        and portfolio_delta.delta_pct is not None
        and private_label_delta.delta_pct > 0
        and portfolio_delta.delta_pct < 0
    )
    return ComparativePatternSignal(
        "PRIVATE_LABEL_GROWTH_WHILE_PORTFOLIO_DECLINES",
        private_label_delta.metric,
        private_label_delta.current_period,
        private_label_delta.reference_period,
        "DETECTED" if detected else "NOT_DETECTED",
        evidence,
    )


def _scope_frame(frame: pl.DataFrame, retailer_id: str, source_id: str, category: str | None) -> pl.DataFrame:
    result = frame.filter((pl.col("retailer_id") == retailer_id) & (pl.col("source_id") == source_id))
    if category is not None:
        result = result.filter(pl.col("category") == category)
    return result


def _sum_period(
    frame: pl.DataFrame,
    metric: str,
    period: date,
    *,
    availability_frame: pl.DataFrame,
) -> float | None:
    if availability_frame.filter(pl.col("period") == period).is_empty():
        return None
    period_rows = frame.filter(pl.col("period") == period)
    if period_rows.is_empty():
        return 0.0
    return float(period_rows.select(pl.col(metric).sum()).item())
