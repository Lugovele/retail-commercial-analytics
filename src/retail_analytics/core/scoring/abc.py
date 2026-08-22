"""ABC classification over metric outputs."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from retail_analytics.quality.report import QualityIssue, QualityReport


@dataclass(frozen=True)
class ABCResult:
    classifications: pl.DataFrame
    quality_report: QualityReport


def calculate_abc(
    metric_frame: pl.DataFrame,
    *,
    concepts: Sequence[str] = ("revenue", "units", "retailer_margin_abs"),
) -> ABCResult:
    if metric_frame.is_empty():
        return ABCResult(pl.DataFrame(), QualityReport())
    source = metric_frame.filter((pl.col("entity_type") == "sku") & pl.col("concept").is_in(list(concepts)))
    if source.is_empty():
        return ABCResult(pl.DataFrame(), QualityReport())
    negative_count = source.filter(pl.col("metric_value") < 0).height
    positive = source.filter(pl.col("metric_value") > 0)
    if positive.is_empty():
        issues = (
            QualityIssue("NEGATIVE_ABC_CONTRIBUTION", "WARNING", negative_count, (), "Negative values excluded from ABC ranking."),
        ) if negative_count else ()
        return ABCResult(_abc_negative_or_unclassified(source), QualityReport(issues))
    totals = positive.group_by(["analysis_run_id", "retailer_id", "source_id", "period", "category", "concept"]).agg(
        pl.col("metric_value").sum().alias("__abc_total")
    )
    ranked = positive.join(
        totals,
        on=["analysis_run_id", "retailer_id", "source_id", "period", "category", "concept"],
        how="left",
    ).sort(
        ["analysis_run_id", "retailer_id", "source_id", "period", "category", "concept", "metric_value", "entity_id"],
        descending=[False, False, False, False, False, False, True, False],
    )
    ranked = ranked.with_columns((pl.col("metric_value") / pl.col("__abc_total")).alias("share"))
    ranked = ranked.with_columns(
        pl.col("share")
        .cum_sum()
        .over(["analysis_run_id", "retailer_id", "source_id", "period", "category", "concept"])
        .alias("cumulative_share")
    )
    ranked = ranked.with_columns(
        pl.col("metric_value")
        .rank("ordinal", descending=True)
        .over(["analysis_run_id", "retailer_id", "source_id", "period", "category", "concept"])
        .alias("__abc_rank")
    )
    ranked = ranked.with_columns(
        pl.when((pl.col("__abc_rank") == 1) | (pl.col("cumulative_share") <= 0.80))
        .then(pl.lit("A"))
        .when(pl.col("cumulative_share") <= 0.95)
        .then(pl.lit("B"))
        .otherwise(pl.lit("C"))
        .alias("abc_class")
    )
    negative = _abc_negative_or_unclassified(source.filter(pl.col("metric_value") <= 0))
    result = pl.concat([ranked, negative], how="diagonal") if not negative.is_empty() else ranked
    result = result.with_columns(
        (pl.lit("abc_") + pl.col("concept")).alias("abc_metric"),
    )
    issues = (
        QualityIssue("NEGATIVE_ABC_CONTRIBUTION", "WARNING", negative_count, (), "Negative values excluded from ABC ranking."),
    ) if negative_count else ()
    return ABCResult(result.drop(["__abc_total", "__abc_rank"], strict=False), QualityReport(issues))


def _abc_negative_or_unclassified(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    return frame.with_columns(
        pl.when(pl.col("metric_value") < 0)
        .then(pl.lit("NEGATIVE_OR_CORRECTION"))
        .otherwise(pl.lit("UNCLASSIFIED"))
        .alias("abc_class"),
        pl.lit(None, dtype=pl.Float64).alias("share"),
        pl.lit(None, dtype=pl.Float64).alias("cumulative_share"),
    )
