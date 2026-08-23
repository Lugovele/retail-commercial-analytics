"""Deterministic ranking projections for dashboard backend analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import polars as pl

from retail_analytics.mart.scopes import PrivateLabelScope, apply_private_label_scope

APPROVED_MANUFACTURER_RANK_METRICS = frozenset({"revenue_net", "revenue_vat", "units"})


class RankingScope(StrEnum):
    """Population scope used for dashboard rankings."""

    CATEGORY = "CATEGORY"


@dataclass(frozen=True)
class ManufacturerRankRow:
    """Rank of a manufacturer within a declared scope."""

    retailer_id: str
    source_id: str
    period_start: date
    period_end: date
    category: str
    manufacturer: str
    metric: str
    metric_value: float
    rank: int
    population_count: int
    tie_count: int
    ranking_scope: RankingScope
    private_label_scope: PrivateLabelScope


def rank_manufacturers(
    frame: pl.DataFrame,
    *,
    retailer_id: str,
    source_id: str,
    metric: str,
    period_start: date,
    period_end: date | None = None,
    category: str | None = None,
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
    ranking_scope: RankingScope | str = RankingScope.CATEGORY,
) -> tuple[ManufacturerRankRow, ...]:
    """Rank manufacturers by summed metric value using competition-rank ties."""

    try:
        resolved_scope = RankingScope(ranking_scope)
    except ValueError as exc:
        raise ValueError(f"Unsupported ranking_scope: {ranking_scope}") from exc
    if resolved_scope != RankingScope.CATEGORY:
        raise ValueError(f"Unsupported ranking_scope: {resolved_scope.value}")
    if metric not in APPROVED_MANUFACTURER_RANK_METRICS:
        raise ValueError(f"Unsupported manufacturer ranking metric: {metric}")
    required = {"retailer_id", "source_id", "period", "category", "manufacturer", metric}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Ranking frame missing columns: {', '.join(missing)}")

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

    grouped = (
        scoped.group_by(["category", "manufacturer"])
        .agg(pl.col(metric).sum().alias("metric_value"))
        .filter(pl.col("manufacturer").is_not_null())
    )
    rows: list[ManufacturerRankRow] = []
    for category_value in sorted(str(value) for value in grouped["category"].unique().to_list()):
        category_rows = grouped.filter(pl.col("category") == category_value).to_dicts()
        values = [float(row["metric_value"]) for row in category_rows]
        population_count = len(values)
        ordered = sorted(category_rows, key=lambda row: (-float(row["metric_value"]), str(row["manufacturer"])))
        for row in ordered:
            value = float(row["metric_value"])
            rank = 1 + sum(1 for other in values if other > value)
            tie_count = sum(1 for other in values if other == value)
            rows.append(
                ManufacturerRankRow(
                    retailer_id=retailer_id,
                    source_id=source_id,
                    period_start=period_start,
                    period_end=end,
                    category=category_value,
                    manufacturer=str(row["manufacturer"]),
                    metric=metric,
                    metric_value=value,
                    rank=rank,
                    population_count=population_count,
                    tie_count=tie_count,
                    ranking_scope=resolved_scope,
                    private_label_scope=PrivateLabelScope(private_label_scope),
                )
            )
    return tuple(rows)
