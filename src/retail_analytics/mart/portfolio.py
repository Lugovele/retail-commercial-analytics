"""Portfolio dashboard summary projections from deterministic row-level facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import polars as pl

from retail_analytics.mart.scopes import PrivateLabelScope, apply_private_label_scope


class ShareMetric(StrEnum):
    """Supported category-share numerator families."""

    REVENUE = "revenue"
    UNITS = "units"
    MARGIN = "margin"


@dataclass(frozen=True)
class CategoryShareResult:
    """Entity share of category total in the selected analytical universe."""

    retailer_id: str
    source_id: str
    period_start: date
    period_end: date
    category: str
    entity_grain: str
    entity_id: str
    share_metric: ShareMetric
    numerator_value: float
    denominator_value: float
    value: float | None
    private_label_scope: PrivateLabelScope


@dataclass(frozen=True)
class ActiveSkuSummary:
    """Active SKU count and historical peak across available periods."""

    retailer_id: str
    source_id: str
    current_period: date
    current_active_sku_count: int
    historical_peak_active_sku_count: int
    peak_period: date | None
    change_from_peak_pct: float | None
    evaluated_periods: tuple[date, ...]
    private_label_scope: PrivateLabelScope


@dataclass(frozen=True)
class BrandVsCategoryComparison:
    """Brand delta compared with its category delta."""

    retailer_id: str
    source_id: str
    category: str
    brand: str
    metric: str
    current_period: date
    reference_period: date
    brand_current_value: float | None
    brand_reference_value: float | None
    brand_delta_pct: float | None
    category_current_value: float | None
    category_reference_value: float | None
    category_delta_pct: float | None
    gap_pp: float | None
    private_label_scope: PrivateLabelScope
    status: str


_SHARE_VALUE_COLUMNS = {
    ShareMetric.REVENUE: "revenue_net",
    ShareMetric.UNITS: "units",
    ShareMetric.MARGIN: "retailer_margin_abs",
}


def calculate_category_share(
    frame: pl.DataFrame,
    *,
    retailer_id: str,
    source_id: str,
    category: str,
    entity_grain: str,
    entity_id: str,
    share_metric: ShareMetric | str,
    period_start: date,
    period_end: date | None = None,
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
) -> CategoryShareResult:
    """Calculate entity/category share from scoped additive components."""

    metric = ShareMetric(share_metric)
    value_column = _SHARE_VALUE_COLUMNS[metric]
    if entity_grain not in {"manufacturer", "brand", "sku"}:
        raise ValueError(f"Unsupported category share entity_grain: {entity_grain}")
    entity_column = "canonical_product_id" if entity_grain == "sku" else entity_grain
    required = {"retailer_id", "source_id", "period", "category", entity_column, value_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Category share frame missing columns: {', '.join(missing)}")

    end = period_end or period_start
    scoped = _base_scope(frame, retailer_id, source_id, period_start, end, category, private_label_scope)
    denominator = _sum(scoped, value_column)
    numerator = _sum(scoped.filter(pl.col(entity_column) == entity_id), value_column)
    value = None if denominator == 0 else numerator / denominator
    return CategoryShareResult(
        retailer_id,
        source_id,
        period_start,
        end,
        category,
        entity_grain,
        entity_id,
        metric,
        numerator,
        denominator,
        value,
        PrivateLabelScope(private_label_scope),
    )


def calculate_active_sku_summary(
    frame: pl.DataFrame,
    *,
    retailer_id: str,
    source_id: str,
    current_period: date,
    history_start: date | None = None,
    history_end: date | None = None,
    category: str | None = None,
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
) -> ActiveSkuSummary:
    """Count SKU with positive unit sales in current and available historical periods."""

    required = {"retailer_id", "source_id", "period", "canonical_product_id", "units"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Active SKU frame missing columns: {', '.join(missing)}")
    start = history_start or current_period
    end = history_end or current_period
    availability_scope = _base_scope(frame, retailer_id, source_id, start, end, category, PrivateLabelScope.INCLUDE)
    scoped = _base_scope(frame, retailer_id, source_id, start, end, category, private_label_scope)
    available_periods = tuple(sorted(availability_scope["period"].unique().to_list())) if not availability_scope.is_empty() else ()
    active = (
        scoped.filter(pl.col("units") > 0)
        .group_by("period")
        .agg(pl.col("canonical_product_id").n_unique().alias("active_sku_count"))
    )
    active_counts = {row["period"]: int(row["active_sku_count"]) for row in active.to_dicts()}
    counts = {period: active_counts.get(period, 0) for period in available_periods}
    evaluated_periods = available_periods
    current_count = counts.get(current_period, 0)
    if counts:
        peak_period, peak_count = min(counts.items(), key=lambda item: (-item[1], item[0]))
    else:
        peak_period, peak_count = None, 0
    change = None if peak_count == 0 else (current_count - peak_count) / peak_count
    return ActiveSkuSummary(
        retailer_id,
        source_id,
        current_period,
        current_count,
        peak_count,
        peak_period,
        change,
        evaluated_periods,
        PrivateLabelScope(private_label_scope),
    )


def compare_brand_to_category(
    frame: pl.DataFrame,
    *,
    retailer_id: str,
    source_id: str,
    category: str,
    brand: str,
    metric: str,
    current_period: date,
    reference_period: date,
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
) -> BrandVsCategoryComparison:
    """Compare brand percentage delta to category percentage delta in percentage points."""

    required = {"retailer_id", "source_id", "period", "category", "brand", metric}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Brand/category frame missing columns: {', '.join(missing)}")
    availability_scope = _base_scope(
        frame,
        retailer_id,
        source_id,
        reference_period,
        current_period,
        category,
        PrivateLabelScope.INCLUDE,
    )
    scoped = _base_scope(frame, retailer_id, source_id, reference_period, current_period, category, private_label_scope)
    brand_rows = scoped.filter(pl.col("brand") == brand)
    brand_current = _sum_period(brand_rows, metric, current_period, availability_frame=availability_scope)
    brand_reference = _sum_period(brand_rows, metric, reference_period, availability_frame=availability_scope)
    category_current = _sum_period(scoped, metric, current_period, availability_frame=availability_scope)
    category_reference = _sum_period(scoped, metric, reference_period, availability_frame=availability_scope)
    brand_delta = _pct_delta(brand_current, brand_reference)
    category_delta = _pct_delta(category_current, category_reference)
    gap = None if brand_delta is None or category_delta is None else brand_delta - category_delta
    status = "READY" if gap is not None else "INSUFFICIENT_REFERENCE"
    return BrandVsCategoryComparison(
        retailer_id,
        source_id,
        category,
        brand,
        metric,
        current_period,
        reference_period,
        brand_current,
        brand_reference,
        brand_delta,
        category_current,
        category_reference,
        category_delta,
        gap,
        PrivateLabelScope(private_label_scope),
        status,
    )


def _base_scope(
    frame: pl.DataFrame,
    retailer_id: str,
    source_id: str,
    period_start: date,
    period_end: date,
    category: str | None,
    private_label_scope: PrivateLabelScope | str,
) -> pl.DataFrame:
    result = frame.filter(
        (pl.col("retailer_id") == retailer_id)
        & (pl.col("source_id") == source_id)
        & (pl.col("period") >= period_start)
        & (pl.col("period") <= period_end)
    )
    if category is not None:
        result = result.filter(pl.col("category") == category)
    return apply_private_label_scope(result, private_label_scope).frame


def _sum(frame: pl.DataFrame, column: str) -> float:
    if frame.is_empty():
        return 0.0
    return float(frame.select(pl.col(column).sum()).item() or 0.0)


def _sum_period(
    frame: pl.DataFrame,
    column: str,
    period: date,
    *,
    availability_frame: pl.DataFrame | None = None,
) -> float | None:
    availability = availability_frame if availability_frame is not None else frame
    if availability.filter(pl.col("period") == period).is_empty():
        return None
    rows = frame.filter(pl.col("period") == period)
    if rows.is_empty():
        return 0.0
    return _sum(rows, column)


def _pct_delta(current: float | None, reference: float | None) -> float | None:
    if current is None or reference in (None, 0):
        return None
    return (current - reference) / reference
