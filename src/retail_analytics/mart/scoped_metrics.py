"""Scope-aware metric calculation helpers for mart builds."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from retail_analytics.core.calculation.aggregations import (
    calculate_metric_share,
    calculate_metrics,
)
from retail_analytics.mart.scopes import (
    PrivateLabelScope,
    PrivateLabelScopeResult,
    apply_private_label_scope,
)
from retail_analytics.metrics.registry import MetricDefinition
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityReport


@dataclass(frozen=True)
class ScopedMetricsResult:
    """Metric outputs calculated inside one analytical universe."""

    private_label_scope: PrivateLabelScope
    metrics: pl.DataFrame
    aggregates: pl.DataFrame
    shares: pl.DataFrame
    quality_report: QualityReport
    scope_result: PrivateLabelScopeResult


def calculate_private_label_scoped_metrics(
    frame: pl.DataFrame,
    definitions: Sequence[MetricDefinition],
    context: AnalysisContext,
    *,
    metric_config_hash: str = "",
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
) -> ScopedMetricsResult:
    """Calculate deterministic metric rows after applying private-label scope."""

    scope_result = apply_private_label_scope(frame, private_label_scope)
    full_metric_result = calculate_metrics(
        frame,
        definitions,
        context,
        metric_config_hash=metric_config_hash,
    )
    metric_result = calculate_metrics(
        scope_result.frame,
        definitions,
        context,
        metric_config_hash=metric_config_hash,
    )
    aggregate_metrics = _preserve_store_universe_denominators(
        metric_result.metrics,
        full_metric_result.metrics,
        definitions,
    )
    share_result = calculate_metric_share(aggregate_metrics)
    metrics = (
        pl.concat([aggregate_metrics, share_result.metrics], how="diagonal")
        if not aggregate_metrics.is_empty() and not share_result.metrics.is_empty()
        else aggregate_metrics
    )
    if not metrics.is_empty():
        metrics = metrics.with_columns(pl.lit(scope_result.private_label_scope.value).alias("private_label_scope"))
    quality_report = metric_result.quality_report.extend(share_result.quality_report)
    return ScopedMetricsResult(
        private_label_scope=scope_result.private_label_scope,
        metrics=metrics,
        aggregates=aggregate_metrics,
        shares=share_result.metrics,
        quality_report=quality_report,
        scope_result=scope_result,
    )


def calculate_private_label_scope_set(
    frame: pl.DataFrame,
    definitions: Sequence[MetricDefinition],
    context: AnalysisContext,
    *,
    metric_config_hash: str = "",
    private_label_scopes: Sequence[PrivateLabelScope | str] = (PrivateLabelScope.INCLUDE,),
) -> tuple[ScopedMetricsResult, ...]:
    """Calculate deterministic metric rows for multiple private-label scopes."""

    return tuple(
        calculate_private_label_scoped_metrics(
            frame,
            definitions,
            context,
            metric_config_hash=metric_config_hash,
            private_label_scope=scope,
        )
        for scope in private_label_scopes
    )


def _preserve_store_universe_denominators(
    scoped_metrics: pl.DataFrame,
    full_metrics: pl.DataFrame,
    definitions: Sequence[MetricDefinition],
) -> pl.DataFrame:
    active_store_names = {
        definition.name
        for definition in definitions
        if definition.concept == "active_store_count"
    }
    if scoped_metrics.is_empty() or full_metrics.is_empty() or not active_store_names:
        return scoped_metrics

    result = _replace_full_universe_metrics(scoped_metrics, full_metrics, active_store_names)
    for definition in definitions:
        if definition.aggregation != "ratio_of_sums" or definition.denominator not in active_store_names:
            continue
        result = _replace_ratio_denominator(result, full_metrics, definition.name, definition.denominator or "")
    return result


def _replace_full_universe_metrics(
    scoped_metrics: pl.DataFrame,
    full_metrics: pl.DataFrame,
    metric_names: set[str],
) -> pl.DataFrame:
    scoped_without_full_universe = scoped_metrics.filter(~pl.col("metric_name").is_in(sorted(metric_names)))
    scoped_full_universe_rows = scoped_metrics.filter(pl.col("metric_name").is_in(sorted(metric_names)))
    full_universe_rows = full_metrics.filter(pl.col("metric_name").is_in(sorted(metric_names)))
    if full_universe_rows.is_empty():
        return scoped_metrics
    join_keys = _metric_identity_join_keys(scoped_full_universe_rows, full_universe_rows)
    if join_keys:
        full_universe_rows = full_universe_rows.join(
            scoped_full_universe_rows.select(join_keys).unique(),
            on=join_keys,
            how="inner",
        )
    return pl.concat([scoped_without_full_universe, full_universe_rows], how="diagonal")


def _replace_ratio_denominator(
    metrics: pl.DataFrame,
    full_metrics: pl.DataFrame,
    ratio_metric_name: str,
    denominator_metric_name: str,
) -> pl.DataFrame:
    ratio_rows = metrics.filter(pl.col("metric_name") == ratio_metric_name)
    denominator_rows = full_metrics.filter(pl.col("metric_name") == denominator_metric_name)
    if ratio_rows.is_empty() or denominator_rows.is_empty():
        return metrics

    join_keys = _metric_identity_join_keys(ratio_rows, denominator_rows)
    if not join_keys:
        return metrics

    denominators = denominator_rows.select(
        [*join_keys, pl.col("metric_value").alias("__full_universe_denominator")]
    )
    ratio_with_denominator = ratio_rows.join(denominators, on=join_keys, how="left")
    ratio_with_denominator = ratio_with_denominator.with_columns(
        pl.coalesce(["__full_universe_denominator", "denominator_value"]).alias("denominator_value")
    ).with_columns(
        pl.when((pl.col("denominator_value") == 0) | pl.col("denominator_value").is_null())
        .then(None)
        .otherwise(pl.col("numerator_value") / pl.col("denominator_value"))
        .alias("metric_value")
    ).drop("__full_universe_denominator")

    unaffected = metrics.filter(pl.col("metric_name") != ratio_metric_name)
    return pl.concat([unaffected, ratio_with_denominator], how="diagonal")


def _metric_identity_join_keys(left: pl.DataFrame, right: pl.DataFrame) -> list[str]:
    return [
        column
        for column in (
            "analysis_run_id",
            "retailer_id",
            "source_id",
            "period",
            "category",
            "manufacturer",
            "brand",
            "canonical_product_id",
            "canonical_store_id",
            "grain_id",
            "entity_id",
        )
        if column in left.columns and column in right.columns
    ]
