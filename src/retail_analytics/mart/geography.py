"""Geography dashboard projections over scoped deterministic facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from retail_analytics.mart.scopes import PrivateLabelScope, apply_private_label_scope

UNKNOWN_REGION = "UNKNOWN_REGION"


@dataclass(frozen=True)
class RegionalMetricRow:
    """Regional additive metrics and recomputed revenue share."""

    retailer_id: str
    source_id: str
    period_start: date
    period_end: date
    region: str
    revenue_net: float
    units: float
    retailer_margin_abs: float
    regional_share_revenue: float | None
    private_label_scope: PrivateLabelScope


def calculate_regional_summary(
    frame: pl.DataFrame,
    *,
    retailer_id: str,
    source_id: str,
    period_start: date,
    period_end: date | None = None,
    category: str | None = None,
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
) -> tuple[RegionalMetricRow, ...]:
    """Aggregate regional metrics and recompute share over the selected range."""

    required = {
        "retailer_id",
        "source_id",
        "period",
        "region",
        "revenue_net",
        "units",
        "retailer_margin_abs",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Regional summary frame missing columns: {', '.join(missing)}")
    end = period_end or period_start
    scoped = frame.filter(
        (pl.col("retailer_id") == retailer_id)
        & (pl.col("source_id") == source_id)
        & (pl.col("period") >= period_start)
        & (pl.col("period") <= end)
    )
    if category is not None:
        scoped = scoped.filter(pl.col("category") == category)
    scoped = apply_private_label_scope(scoped, private_label_scope).frame
    if scoped.is_empty():
        return ()
    normalized = scoped.with_columns(
        pl.when(pl.col("region").is_null() | (pl.col("region").cast(pl.Utf8).str.strip_chars() == ""))
        .then(pl.lit(UNKNOWN_REGION))
        .otherwise(pl.col("region").cast(pl.Utf8))
        .alias("region")
    )
    grouped = normalized.group_by("region").agg(
        pl.col("revenue_net").sum().alias("revenue_net"),
        pl.col("units").sum().alias("units"),
        pl.col("retailer_margin_abs").sum().alias("retailer_margin_abs"),
    )
    total_revenue = float(grouped.select(pl.col("revenue_net").sum()).item() or 0.0)
    rows: list[RegionalMetricRow] = []
    for row in grouped.sort("region").to_dicts():
        revenue = float(row["revenue_net"] or 0.0)
        rows.append(
            RegionalMetricRow(
                retailer_id=retailer_id,
                source_id=source_id,
                period_start=period_start,
                period_end=end,
                region=str(row["region"]),
                revenue_net=revenue,
                units=float(row["units"] or 0.0),
                retailer_margin_abs=float(row["retailer_margin_abs"] or 0.0),
                regional_share_revenue=None if total_revenue == 0 else revenue / total_revenue,
                private_label_scope=PrivateLabelScope(private_label_scope),
            )
        )
    return tuple(rows)
