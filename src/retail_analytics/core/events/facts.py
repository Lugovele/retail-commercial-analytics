"""Normalize prepared analytics outputs into event facts."""
from __future__ import annotations

import polars as pl

from retail_analytics.core.events.contracts import EventFactResult
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityReport


def build_event_facts(
    *,
    metrics: pl.DataFrame | None = None,
    comparisons: pl.DataFrame | None = None,
    abc: pl.DataFrame | None = None,
    benchmark_features: pl.DataFrame | None = None,
    context: AnalysisContext,
) -> EventFactResult:
    """Build long event facts from already-computed Slice 2/3 outputs."""
    frames = [
        _comparison_facts(_frame_or_empty(comparisons), context),
        _abc_facts(_frame_or_empty(abc), context),
        _benchmark_facts(_frame_or_empty(benchmark_features), context),
    ]
    del metrics
    non_empty = [frame for frame in frames if not frame.is_empty()]
    facts = pl.concat(non_empty, how="diagonal") if non_empty else pl.DataFrame()
    return EventFactResult(facts, QualityReport())


def _comparison_facts(frame: pl.DataFrame, context: AnalysisContext) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame()
    scoped = _scope(frame, context)
    if scoped.is_empty():
        return pl.DataFrame()
    return scoped.with_columns(
        _optional_col(scoped, "rule_version", pl.Utf8).fill_null(context.rule_version).alias("rule_version"),
        pl.lit("comparison").alias("input_source"),
        _first_present(scoped, ("concept", "metric_name", "metric_definition_id")).alias("feature_name"),
        pl.col("current_period").alias("period"),
        pl.col("reference_period"),
        pl.col("current_value").alias("observed_value"),
        pl.col("reference_value"),
        pl.lit(None, dtype=pl.Utf8).alias("observed_label"),
        pl.lit(None, dtype=pl.Utf8).alias("reference_label"),
        pl.lit(None, dtype=pl.Boolean).alias("label_changed"),
        _optional_col(scoped, "delta_abs", pl.Float64),
        _optional_col(scoped, "delta_pct", pl.Float64),
        _optional_col(scoped, "delta_pp", pl.Float64),
        _optional_col(scoped, "comparison_type", pl.Utf8),
        _optional_col(scoped, "comparison_quality", pl.Utf8),
        _optional_col(scoped, "metric_definition_id", pl.Utf8),
        _optional_col(scoped, "metric_definition_version", pl.Utf8),
        _optional_col(scoped, "metric_config_hash", pl.Utf8),
        pl.lit(None, dtype=pl.Utf8).alias("benchmark_scope"),
        pl.lit(None, dtype=pl.Utf8).alias("benchmark_scope_id"),
        pl.lit(None, dtype=pl.Utf8).alias("pool_source"),
        pl.lit(None, dtype=pl.Utf8).alias("peer_rule_id"),
        pl.lit(None, dtype=pl.Utf8).alias("peer_rule_version"),
        pl.lit(None, dtype=pl.Utf8).alias("peer_config_hash"),
        pl.lit(None, dtype=pl.Utf8).alias("price_segment_rule_id"),
        pl.lit(None, dtype=pl.Utf8).alias("price_segment_rule_version"),
        pl.lit(None, dtype=pl.Utf8).alias("price_segment_config_hash"),
        pl.lit(None, dtype=pl.Float64).alias("rank"),
        pl.lit(None, dtype=pl.Float64).alias("percentile"),
        pl.lit(None, dtype=pl.Int64).alias("population_size"),
        pl.lit(None, dtype=pl.Float64).alias("peer_median_price"),
    ).select(_FACT_COLUMNS)


def _abc_facts(frame: pl.DataFrame, context: AnalysisContext) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame()
    scoped = _scope(frame, context)
    if scoped.is_empty():
        return pl.DataFrame()
    return scoped.with_columns(
        _optional_col(scoped, "rule_version", pl.Utf8).fill_null(context.rule_version).alias("rule_version"),
        pl.lit("abc").alias("input_source"),
        _first_present(scoped, ("abc_metric", "concept", "metric_definition_id")).alias("feature_name"),
        pl.col("period"),
        _optional_col(scoped, "reference_period", pl.Date),
        pl.lit(None, dtype=pl.Float64).alias("observed_value"),
        pl.lit(None, dtype=pl.Float64).alias("reference_value"),
        pl.col("abc_class").alias("observed_label"),
        _optional_col(scoped, "reference_abc_class", pl.Utf8).alias("reference_label"),
        (pl.col("abc_class") != _optional_col(scoped, "reference_abc_class", pl.Utf8)).alias("label_changed"),
        pl.lit(None, dtype=pl.Float64).alias("delta_abs"),
        pl.lit(None, dtype=pl.Float64).alias("delta_pct"),
        pl.lit(None, dtype=pl.Float64).alias("delta_pp"),
        _optional_col(scoped, "comparison_type", pl.Utf8),
        pl.lit(None, dtype=pl.Utf8).alias("comparison_quality"),
        _optional_col(scoped, "metric_definition_id", pl.Utf8),
        _optional_col(scoped, "metric_definition_version", pl.Utf8),
        _optional_col(scoped, "metric_config_hash", pl.Utf8),
        pl.lit(None, dtype=pl.Utf8).alias("benchmark_scope"),
        pl.lit(None, dtype=pl.Utf8).alias("benchmark_scope_id"),
        pl.lit(None, dtype=pl.Utf8).alias("pool_source"),
        pl.lit(None, dtype=pl.Utf8).alias("peer_rule_id"),
        pl.lit(None, dtype=pl.Utf8).alias("peer_rule_version"),
        pl.lit(None, dtype=pl.Utf8).alias("peer_config_hash"),
        pl.lit(None, dtype=pl.Utf8).alias("price_segment_rule_id"),
        pl.lit(None, dtype=pl.Utf8).alias("price_segment_rule_version"),
        pl.lit(None, dtype=pl.Utf8).alias("price_segment_config_hash"),
        pl.lit(None, dtype=pl.Float64).alias("rank"),
        pl.lit(None, dtype=pl.Float64).alias("percentile"),
        pl.lit(None, dtype=pl.Int64).alias("population_size"),
        pl.lit(None, dtype=pl.Float64).alias("peer_median_price"),
    ).select(_FACT_COLUMNS)


def _benchmark_facts(frame: pl.DataFrame, context: AnalysisContext) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame()
    scoped = _scope(frame, context)
    if scoped.is_empty():
        return pl.DataFrame()
    return scoped.with_columns(
        _optional_col(scoped, "rule_version", pl.Utf8).fill_null(context.rule_version).alias("rule_version"),
        _benchmark_entity_id(scoped).alias("entity_id"),
        _optional_col(scoped, "entity_type", pl.Utf8).fill_null("sku").alias("entity_type"),
        pl.lit("benchmark").alias("input_source"),
        pl.col("metric_name").alias("feature_name"),
        _optional_col(scoped, "reference_period", pl.Date).alias("period"),
        pl.lit(None, dtype=pl.Date).alias("reference_period"),
        _benchmark_observed_value(scoped).alias("observed_value"),
        pl.lit(None, dtype=pl.Float64).alias("reference_value"),
        pl.lit(None, dtype=pl.Utf8).alias("observed_label"),
        pl.lit(None, dtype=pl.Utf8).alias("reference_label"),
        pl.lit(None, dtype=pl.Boolean).alias("label_changed"),
        _optional_col(scoped, "price_vs_peer_median_abs", pl.Float64).alias("delta_abs"),
        _optional_col(scoped, "price_delta_pct_to_peer_median", pl.Float64).alias("delta_pct"),
        pl.lit(None, dtype=pl.Float64).alias("delta_pp"),
        pl.lit(None, dtype=pl.Utf8).alias("comparison_type"),
        pl.lit(None, dtype=pl.Utf8).alias("comparison_quality"),
        _optional_col(scoped, "metric_definition_id", pl.Utf8),
        _optional_col(scoped, "metric_definition_version", pl.Utf8),
        pl.lit(None, dtype=pl.Utf8).alias("metric_config_hash"),
        _optional_col(scoped, "benchmark_scope", pl.Utf8),
        _optional_col(scoped, "benchmark_scope_id", pl.Utf8),
        _optional_col(scoped, "pool_source", pl.Utf8),
        _optional_col(scoped, "peer_rule_id", pl.Utf8),
        _optional_col(scoped, "peer_rule_version", pl.Utf8),
        _optional_col(scoped, "peer_config_hash", pl.Utf8),
        _optional_col(scoped, "price_segment_rule_id", pl.Utf8),
        _optional_col(scoped, "price_segment_rule_version", pl.Utf8),
        _optional_col(scoped, "price_segment_config_hash", pl.Utf8),
        _optional_col(scoped, "rank", pl.Float64),
        _optional_col(scoped, "percentile", pl.Float64),
        _optional_col(scoped, "population_size", pl.Int64),
        _optional_col(scoped, "peer_median_price", pl.Float64),
    ).select(_FACT_COLUMNS)


def _scope(frame: pl.DataFrame, context: AnalysisContext) -> pl.DataFrame:
    scoped = frame.filter(
        (pl.col("analysis_run_id") == context.analysis_run_id)
        & (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
    )
    if "rule_version" in scoped.columns:
        scoped = scoped.filter(pl.col("rule_version") == context.rule_version)
    return scoped


def _frame_or_empty(frame: pl.DataFrame | None) -> pl.DataFrame:
    return frame if frame is not None else pl.DataFrame()


def _optional_col(frame: pl.DataFrame, name: str, dtype: pl.DataType) -> pl.Expr:
    return pl.col(name).cast(dtype, strict=False) if name in frame.columns else pl.lit(None, dtype=dtype).alias(name)


def _first_present(frame: pl.DataFrame, names: tuple[str, ...]) -> pl.Expr:
    for name in names:
        if name in frame.columns:
            return pl.col(name)
    return pl.lit(None, dtype=pl.Utf8)


def _benchmark_observed_value(frame: pl.DataFrame) -> pl.Expr:
    if "metric_value" in frame.columns:
        return pl.col("metric_value")
    if "price_delta_pct_to_peer_median" in frame.columns:
        return pl.col("price_delta_pct_to_peer_median")
    return pl.lit(None, dtype=pl.Float64)


def _benchmark_entity_id(frame: pl.DataFrame) -> pl.Expr:
    if "entity_id" in frame.columns:
        return pl.col("entity_id")
    return pl.col("target_entity_id")


_FACT_COLUMNS = [
    "analysis_run_id",
    "retailer_id",
    "source_id",
    "rule_version",
    "entity_type",
    "entity_id",
    "category",
    "input_source",
    "feature_name",
    "period",
    "reference_period",
    "comparison_type",
    "comparison_quality",
    "observed_value",
    "reference_value",
    "observed_label",
    "reference_label",
    "label_changed",
    "delta_abs",
    "delta_pct",
    "delta_pp",
    "metric_definition_id",
    "metric_definition_version",
    "metric_config_hash",
    "benchmark_scope",
    "benchmark_scope_id",
    "pool_source",
    "peer_rule_id",
    "peer_rule_version",
    "peer_config_hash",
    "price_segment_rule_id",
    "price_segment_rule_version",
    "price_segment_config_hash",
    "rank",
    "percentile",
    "population_size",
    "peer_median_price",
]
