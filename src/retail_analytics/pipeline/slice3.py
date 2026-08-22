"""Thin Slice 3 competitor benchmarking orchestrator."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from retail_analytics.core.benchmarking.contracts import (
    BenchmarkRequest,
    PeerRule,
    PriceSegmentRule,
    Slice3BenchmarkingResult,
)
from retail_analytics.core.benchmarking.features import calculate_benchmark_features
from retail_analytics.core.benchmarking.peer_groups import build_peer_groups
from retail_analytics.core.benchmarking.price_segments import build_price_segments
from retail_analytics.core.benchmarking.registry import (
    load_peer_rule_config,
    load_price_segment_rule_config,
    peer_rules_for_context,
    price_segment_rules_for_context,
)
from retail_analytics.pipeline.context import AnalysisContext


def run_slice3_benchmarking(
    *,
    metric_frame: pl.DataFrame,
    product_frame: pl.DataFrame,
    peer_rules: tuple[PeerRule, ...] | str | Path,
    price_segment_rules: tuple[PriceSegmentRule, ...] | str | Path,
    context: AnalysisContext,
    request: BenchmarkRequest | None = None,
) -> Slice3BenchmarkingResult:
    """Run Slice 3 benchmarking without mutating metric or product inputs."""
    benchmark_request = request or BenchmarkRequest()
    resolved_peer_rules, peer_hash = _resolve_peer_rules(peer_rules)
    resolved_segment_rules, segment_hash = _resolve_price_segment_rules(price_segment_rules)
    context_peer_rules = peer_rules_for_context(resolved_peer_rules, context)
    context_segment_rules = price_segment_rules_for_context(resolved_segment_rules, context)
    segment_result = build_price_segments(
        metric_frame,
        product_frame,
        context_segment_rules,
        context,
        benchmark_request,
        config_hash=segment_hash,
    )
    peer_result = build_peer_groups(
        metric_frame,
        product_frame,
        context_peer_rules,
        segment_result.price_segments,
        context,
        benchmark_request,
        config_hash=peer_hash,
    )
    feature_result = calculate_benchmark_features(
        metric_frame,
        peer_result.peer_groups,
        segment_result.price_segments,
        context,
        benchmark_request,
    )
    quality_report = segment_result.quality_report.extend(peer_result.quality_report).extend(
        feature_result.quality_report
    )
    return Slice3BenchmarkingResult(
        context=context,
        price_segments=segment_result.price_segments,
        peer_groups=peer_result.peer_groups,
        benchmark_features=feature_result.benchmark_features,
        quality_report=quality_report,
        peer_config_hash=peer_hash,
        price_segment_config_hash=segment_hash,
    )


def _resolve_peer_rules(peer_rules: tuple[PeerRule, ...] | str | Path) -> tuple[tuple[PeerRule, ...], str]:
    if isinstance(peer_rules, (str, Path)):
        return load_peer_rule_config(peer_rules)
    return peer_rules, ""


def _resolve_price_segment_rules(
    price_segment_rules: tuple[PriceSegmentRule, ...] | str | Path,
) -> tuple[tuple[PriceSegmentRule, ...], str]:
    if isinstance(price_segment_rules, (str, Path)):
        return load_price_segment_rule_config(price_segment_rules)
    return price_segment_rules, ""
