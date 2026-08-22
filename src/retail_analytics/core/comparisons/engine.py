"""Period comparison engine."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import polars as pl

from retail_analytics.core.comparisons.comparability import ComparisonQuality, ComparisonType
from retail_analytics.core.comparisons.period_index import build_period_index
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport


@dataclass(frozen=True)
class ComparisonRequest:
    comparison_type: ComparisonType
    current_period: date


@dataclass(frozen=True)
class ComparisonResult:
    comparisons: pl.DataFrame
    quality_report: QualityReport


def compare_periods(
    metric_frame: pl.DataFrame,
    requests: Sequence[ComparisonRequest],
    context: AnalysisContext,
) -> ComparisonResult:
    scoped = metric_frame.filter(
        (pl.col("analysis_run_id") == context.analysis_run_id)
        & (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
    )
    period_index = build_period_index(scoped.get_column("period").to_list()) if not scoped.is_empty() else build_period_index(())
    frames: list[pl.DataFrame] = []
    issues: list[QualityIssue] = []
    for request in requests:
        reference_period = _reference_period(period_index, request)
        if reference_period is None:
            issues.append(QualityIssue("MISSING_COMPARISON_BASE", "WARNING", 0, (), f"Missing base period for {request.comparison_type}."))
            continue
        current = scoped.filter(pl.col("period") == request.current_period)
        base = scoped.filter(pl.col("period") == reference_period)
        keys = [
            column
            for column in ["analysis_run_id", "retailer_id", "source_id", "metric_definition_id", "metric_definition_version", "entity_type", "entity_id", "category"]
            if column in scoped.columns
        ]
        joined = current.join(base, on=keys, how="left", suffix="_base")
        missing = joined.filter(pl.col("metric_value_base").is_null()).height
        if missing:
            issues.append(QualityIssue("MISSING_COMPARISON_BASE", "WARNING", missing, (), "Missing comparison base metric row."))
        month_gap = period_index.month_gap(request.current_period, reference_period)
        quality = _quality(request.comparison_type, month_gap)
        frames.append(
            joined.with_columns(
                pl.lit(request.comparison_type).alias("comparison_type"),
                pl.lit(request.current_period).alias("current_period"),
                pl.lit(reference_period).alias("reference_period"),
                pl.lit(month_gap).alias("month_gap"),
                pl.lit(request.current_period.month == reference_period.month).alias("same_calendar_month"),
                pl.lit(month_gap == 1).alias("is_contiguous"),
                pl.lit(quality).alias("comparison_quality"),
                pl.col("metric_value").alias("current_value"),
                pl.col("metric_value_base").alias("reference_value"),
                (pl.col("metric_value") - pl.col("metric_value_base")).alias("delta_abs"),
                pl.when(pl.col("metric_value_base") == 0)
                .then(None)
                .otherwise((pl.col("metric_value") - pl.col("metric_value_base")) / pl.col("metric_value_base"))
                .alias("delta_pct"),
                pl.when(pl.col("concept").is_in(["distribution", "retailer_margin_pct", "category_revenue_share", "category_units_share", "category_margin_share"]))
                .then(pl.col("metric_value") - pl.col("metric_value_base"))
                .otherwise(None)
                .alias("delta_pp"),
                pl.col("metric_value_base").is_not_null().alias("comparable"),
            ).select(
                [
                    *keys,
                    "comparison_type",
                    "current_period",
                    "reference_period",
                    "month_gap",
                    "same_calendar_month",
                    "is_contiguous",
                    "comparison_quality",
                    "current_value",
                    "reference_value",
                    "delta_abs",
                    "delta_pct",
                    "delta_pp",
                    "comparable",
                ]
            )
        )
        zero_base = joined.filter(pl.col("metric_value_base") == 0).height
        if zero_base:
            issues.append(QualityIssue("ZERO_METRIC_DENOMINATOR", "WARNING", zero_base, (), "Comparison base value is zero."))
    comparisons = pl.concat(frames, how="diagonal") if frames else pl.DataFrame()
    return ComparisonResult(comparisons, QualityReport(tuple(issues)))


def _reference_period(period_index, request: ComparisonRequest) -> date | None:
    if request.comparison_type == "YOY":
        candidate = period_index.same_month_previous_year(request.current_period)
        return candidate if candidate in period_index.available_periods else None
    if request.comparison_type == "MOM":
        candidate = period_index.previous_calendar_month(request.current_period)
        return candidate if candidate in period_index.available_periods else None
    return period_index.previous_available_period(request.current_period)


def _quality(comparison_type: ComparisonType, month_gap: int) -> ComparisonQuality:
    if comparison_type == "YOY" and month_gap == 12:
        return "HIGH"
    if comparison_type == "MOM" and month_gap == 1:
        return "HIGH"
    if comparison_type == "PREVIOUS_AVAILABLE" and month_gap > 1:
        return "MEDIUM"
    return "LOW"
