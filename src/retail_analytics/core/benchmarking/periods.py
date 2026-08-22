"""Benchmark period selection helpers."""
from __future__ import annotations

from datetime import date

import polars as pl

from retail_analytics.core.benchmarking.contracts import BenchmarkRequest


def select_benchmark_period(metric_frame: pl.DataFrame, request: BenchmarkRequest, price_metric_name: str) -> date | None:
    if request.benchmark_period is not None:
        return request.benchmark_period
    scoped = metric_frame.filter(
        (pl.col("metric_name") == price_metric_name)
        & pl.col("metric_value").is_not_null()
        & (pl.col("metric_value") > 0)
    )
    if scoped.is_empty():
        return None
    return scoped.get_column("period").max()
