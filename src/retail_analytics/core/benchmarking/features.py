"""Benchmark ranks, percentiles, and relative price features."""
from __future__ import annotations

from typing import Any

import polars as pl

from retail_analytics.core.benchmarking.contracts import (
    BenchmarkFeatureResult,
    BenchmarkRequest,
)
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport

BENCHMARK_METRICS = (
    "revenue_net",
    "units",
    "units_per_selling_store",
    "retailer_margin_abs",
    "numeric_distribution",
    "weighted_shelf_price_vat",
)


def calculate_benchmark_features(
    metric_frame: pl.DataFrame,
    peer_groups: pl.DataFrame,
    price_segments: pl.DataFrame,
    context: AnalysisContext,
    request: BenchmarkRequest,
) -> BenchmarkFeatureResult:
    if peer_groups.is_empty():
        return BenchmarkFeatureResult(pl.DataFrame(), QualityReport())
    rows: list[dict[str, Any]] = []
    issues: list[QualityIssue] = []
    metrics = metric_frame.filter(
        (pl.col("analysis_run_id") == context.analysis_run_id)
        & (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
        & pl.col("metric_name").is_in(list(BENCHMARK_METRICS))
    )
    if request.benchmark_period is not None:
        metrics = metrics.filter(pl.col("period") == request.benchmark_period)
    group_columns = [
        "benchmark_scope_id",
        "benchmark_scope",
        "pool_source",
        "peer_rule_id",
        "peer_rule_version",
        "peer_config_hash",
        "target_entity_id",
        "category",
        "reference_period",
    ]
    for group in peer_groups.group_by(group_columns, maintain_order=True).agg(pl.col("peer_entity_id")).to_dicts():
        peer_ids = tuple(group["peer_entity_id"])
        target_id = group["target_entity_id"]
        for metric_name in BENCHMARK_METRICS:
            metric_rows = metrics.filter(pl.col("metric_name") == metric_name)
            if group["reference_period"] is not None:
                metric_rows = metric_rows.filter(pl.col("period") == group["reference_period"])
            population = metric_rows.filter(pl.col("entity_id").is_in(list(peer_ids))).select(
                "entity_id",
                "metric_value",
                "metric_definition_id",
                "metric_definition_version",
            )
            if population.is_empty():
                issues.append(QualityIssue("MISSING_BENCHMARK_METRIC", "WARNING", 1, (), f"Missing benchmark metric: {metric_name}."))
                continue
            target_rows = population.filter(pl.col("entity_id") == target_id).to_dicts()
            value = target_rows[0]["metric_value"] if target_rows else None
            definition_id = target_rows[0]["metric_definition_id"] if target_rows else None
            definition_version = target_rows[0]["metric_definition_version"] if target_rows else None
            ascending = metric_name == "weighted_shelf_price_vat"
            rank = _competition_rank(population, target_id, ascending=ascending)
            percentile = _midrank_percentile(population, target_id, ascending=ascending)
            rows.append(
                {
                    "analysis_run_id": context.analysis_run_id,
                    "retailer_id": context.retailer_id,
                    "source_id": context.source_id,
                    "rule_version": context.rule_version,
                    "reference_period": group["reference_period"],
                    "target_entity_id": target_id,
                    "benchmark_scope": group["benchmark_scope"],
                    "benchmark_scope_id": group["benchmark_scope_id"],
                    "pool_source": group["pool_source"],
                    "peer_rule_id": group["peer_rule_id"],
                    "peer_rule_version": group["peer_rule_version"],
                    "peer_config_hash": group["peer_config_hash"],
                    "category": group["category"],
                    "metric_name": metric_name,
                    "metric_definition_id": definition_id,
                    "metric_definition_version": definition_version,
                    "metric_value": value,
                    "rank": rank,
                    "percentile": percentile,
                    "population_size": population.height,
                }
            )
        price_features, price_issues = _relative_price_features(price_segments, target_id, peer_ids, context, group)
        rows.extend(price_features)
        issues.extend(price_issues)
    return BenchmarkFeatureResult(pl.DataFrame(rows), QualityReport(tuple(issues)))


def _competition_rank(frame: pl.DataFrame, entity_id: str, *, ascending: bool) -> int | None:
    values = frame.filter(pl.col("metric_value").is_not_null())
    target = values.filter(pl.col("entity_id") == entity_id).get_column("metric_value").to_list()
    if not target:
        return None
    value = target[0]
    if ascending:
        better = values.filter(pl.col("metric_value") < value).height
    else:
        better = values.filter(pl.col("metric_value") > value).height
    return better + 1


def _midrank_percentile(frame: pl.DataFrame, entity_id: str, *, ascending: bool) -> float | None:
    values = frame.filter(pl.col("metric_value").is_not_null())
    target = values.filter(pl.col("entity_id") == entity_id).get_column("metric_value").to_list()
    if not target or values.height <= 1:
        return None
    value = target[0]
    if ascending:
        better = values.filter(pl.col("metric_value") < value).height
    else:
        better = values.filter(pl.col("metric_value") > value).height
    tied = values.filter(pl.col("metric_value") == value).height
    midrank = better + 1 + ((tied - 1) / 2)
    return 1 - ((midrank - 1) / (values.height - 1))


def _relative_price_features(
    price_segments: pl.DataFrame,
    target_id: str,
    peer_ids: tuple[str, ...],
    context: AnalysisContext,
    group: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[QualityIssue]]:
    issues: list[QualityIssue] = []
    if price_segments.is_empty():
        return [], issues
    prices = price_segments.filter(
        (pl.col("reference_period") == group["reference_period"])
        if group["reference_period"] is not None
        else pl.lit(True)
    ).select("entity_id", "representative_price")
    own = prices.filter(pl.col("entity_id") == target_id).get_column("representative_price").to_list()
    peer_prices = prices.filter(
        pl.col("entity_id").is_in(list(peer_ids))
        & (pl.col("entity_id") != target_id)
        & pl.col("representative_price").is_not_null()
        & (pl.col("representative_price") > 0)
    )
    if not own or own[0] is None or not peer_prices.height:
        issues.append(QualityIssue("EMPTY_DIRECT_PEER_GROUP", "WARNING", 1, (), "Peer median price is unavailable."))
        median = None
    else:
        median = peer_prices.get_column("representative_price").median()
    if median in (None, 0):
        issues.append(QualityIssue("ZERO_PEER_MEDIAN", "WARNING", 1, (), "Peer median price is zero or null."))
        delta_abs = index = delta_pct = None
    else:
        delta_abs = own[0] - median
        index = 100 * own[0] / median
        delta_pct = own[0] / median - 1
    return [
        {
            "analysis_run_id": context.analysis_run_id,
            "retailer_id": context.retailer_id,
            "source_id": context.source_id,
            "rule_version": context.rule_version,
            "reference_period": group["reference_period"],
            "target_entity_id": target_id,
            "benchmark_scope": group["benchmark_scope"],
            "benchmark_scope_id": group["benchmark_scope_id"],
            "pool_source": group["pool_source"],
            "peer_rule_id": group["peer_rule_id"],
            "peer_rule_version": group["peer_rule_version"],
            "peer_config_hash": group["peer_config_hash"],
            "category": group["category"],
            "metric_name": "relative_price_position",
            "peer_median_price": median,
            "price_vs_peer_median_abs": delta_abs,
            "price_index_to_peer_median": index,
            "price_delta_pct_to_peer_median": delta_pct,
            "population_size": len(peer_ids),
        }
    ], issues
