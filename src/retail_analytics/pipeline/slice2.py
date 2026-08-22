"""Thin Slice 2 metrics, comparisons, shares, and ABC orchestrator."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from retail_analytics.core.calculation.aggregations import (
    MetricsResult,
    calculate_metric_share,
    calculate_metrics,
)
from retail_analytics.core.comparisons.engine import (
    ComparisonRequest,
    ComparisonResult,
    compare_periods,
)
from retail_analytics.core.scoring.abc import ABCResult, calculate_abc
from retail_analytics.metrics.registry import (
    MetricDefinition,
    MetricRegistry,
    load_metric_definition_config,
)
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityReport


@dataclass(frozen=True)
class Slice2Result:
    context: AnalysisContext
    aggregates: pl.DataFrame
    shares: pl.DataFrame
    comparisons: pl.DataFrame
    abc: pl.DataFrame
    quality_report: QualityReport
    metric_result: MetricsResult
    share_result: MetricsResult
    comparison_result: ComparisonResult
    abc_result: ABCResult
    metric_config_hash: str


def run_slice2_metrics(
    *,
    enriched_frame: pl.DataFrame,
    metric_definitions: MetricRegistry | Sequence[MetricDefinition] | str | Path,
    context: AnalysisContext,
    comparison_requests: Sequence[ComparisonRequest] = (),
) -> Slice2Result:
    """Run Slice 2 analytical feature calculations without mutating inputs."""
    registry = _resolve_registry(metric_definitions)
    context_registry = registry.for_context(context)
    metric_result = calculate_metrics(
        enriched_frame,
        context_registry.definitions,
        context,
        metric_config_hash=registry.config_hash,
    )
    share_result = calculate_metric_share(metric_result.metrics)
    metric_and_share = (
        pl.concat([metric_result.metrics, share_result.metrics], how="diagonal")
        if not metric_result.metrics.is_empty() and not share_result.metrics.is_empty()
        else metric_result.metrics
    )
    comparison_result = compare_periods(metric_and_share, comparison_requests, context)
    abc_result = calculate_abc(metric_result.metrics)
    quality_report = metric_result.quality_report.extend(share_result.quality_report).extend(
        comparison_result.quality_report
    ).extend(abc_result.quality_report)
    return Slice2Result(
        context=context,
        aggregates=metric_result.metrics,
        shares=share_result.metrics,
        comparisons=comparison_result.comparisons,
        abc=abc_result.classifications,
        quality_report=quality_report,
        metric_result=metric_result,
        share_result=share_result,
        comparison_result=comparison_result,
        abc_result=abc_result,
        metric_config_hash=registry.config_hash,
    )


def _resolve_registry(metric_definitions: MetricRegistry | Sequence[MetricDefinition] | str | Path) -> MetricRegistry:
    if isinstance(metric_definitions, MetricRegistry):
        return metric_definitions
    if isinstance(metric_definitions, (str, Path)):
        return load_metric_definition_config(metric_definitions)
    return MetricRegistry(tuple(metric_definitions), "")
