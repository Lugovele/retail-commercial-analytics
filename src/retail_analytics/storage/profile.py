"""Source profiling for canonical ingestion."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from retail_analytics.schema.canonical import CANDIDATE_GRAIN_COLUMNS


@dataclass(frozen=True)
class SourceProfile:
    row_count: int
    column_count: int
    periods: tuple[date, ...]
    source_store_count: int
    source_sku_count: int
    null_counts: dict[str, int]
    duplicate_candidate_count: int

def profile_canonical_source(frame: pl.DataFrame) -> SourceProfile:
    periods = tuple(sorted(value for value in frame.get_column("period").unique().to_list() if value is not None))
    null_counts = {column: int(frame.get_column(column).null_count()) for column in frame.columns}
    duplicate_candidate_count = 0
    if all(column in frame.columns for column in CANDIDATE_GRAIN_COLUMNS) and frame.height:
        grouped = frame.group_by(list(CANDIDATE_GRAIN_COLUMNS)).len(name="row_count")
        duplicate_candidate_count = int(grouped.filter(pl.col("row_count") > 1)["row_count"].sum() or 0)
    return SourceProfile(
        row_count=frame.height,
        column_count=len(frame.columns),
        periods=periods,
        source_store_count=frame.get_column("source_store_id").n_unique() if "source_store_id" in frame.columns else 0,
        source_sku_count=frame.get_column("source_sku_id").n_unique() if "source_sku_id" in frame.columns else 0,
        null_counts=null_counts,
        duplicate_candidate_count=duplicate_candidate_count,
    )