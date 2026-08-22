"""Peer group and competitor pool construction."""
from __future__ import annotations

from typing import Any

import polars as pl

from retail_analytics.core.benchmarking.contracts import (
    BenchmarkRequest,
    PeerGroupResult,
    PeerRule,
)
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport


def build_peer_groups(
    metric_frame: pl.DataFrame,
    product_frame: pl.DataFrame,
    peer_rules: tuple[PeerRule, ...],
    price_segments: pl.DataFrame,
    context: AnalysisContext,
    request: BenchmarkRequest,
    *,
    config_hash: str = "",
) -> PeerGroupResult:
    benchmark_period = _benchmark_period(price_segments, request)
    products = _product_scope(product_frame, context)
    if not price_segments.is_empty():
        products = products.join(
            price_segments.select("entity_id", "price_segment", "reference_period"),
            on="entity_id",
            how="left",
        )
    rows: list[dict[str, Any]] = []
    issues: list[QualityIssue] = []
    scoped_rules = tuple(
        rule
        for rule in peer_rules
        if rule.retailer_id == context.retailer_id
        and (rule.source_id is None or rule.source_id == context.source_id)
        and rule.rule_version == context.rule_version
    )
    for rule in scoped_rules:
        unknown = [dimension for dimension in rule.required_dimensions if dimension not in products.columns]
        if unknown:
            issues.append(QualityIssue("UNKNOWN_PEER_DIMENSION", "FATAL", len(unknown), (), f"Unknown peer dimensions: {','.join(unknown)}."))
            continue
        if not rule.required_dimensions:
            issues.append(QualityIssue("UNKNOWN_PEER_DIMENSION", "FATAL", 1, (), "Peer rule requires at least one dimension."))
            continue
        if rule.direct_peer_mode != "DIRECT_ONLY":
            issues.append(
                QualityIssue(
                    "UNSUPPORTED_DIRECT_PEER_MODE",
                    "ERROR",
                    1,
                    (),
                    f"Unsupported direct peer mode: {rule.direct_peer_mode}.",
                )
            )
            continue
        if rule.peer_level == "BROAD_CATEGORY":
            rows.extend(_broad_rows(products, metric_frame, rule, context, benchmark_period, config_hash))
        else:
            direct_rows = _direct_rows(products, rule, context, benchmark_period, config_hash)
            rows.extend(direct_rows)
            empty_targets = products.height - len({row["target_entity_id"] for row in direct_rows})
            if empty_targets:
                issues.append(QualityIssue("EMPTY_DIRECT_PEER_GROUP", "WARNING", empty_targets, (), "Direct peer group is empty for some targets."))
    return PeerGroupResult(pl.DataFrame(rows), QualityReport(tuple(issues)), config_hash)


def _broad_rows(
    products: pl.DataFrame,
    metric_frame: pl.DataFrame,
    rule: PeerRule,
    context: AnalysisContext,
    benchmark_period: object,
    config_hash: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    broad_pairs = _pairs(products, ("category",), include_self=True)
    for row in broad_pairs:
        output.append(_peer_row(row, rule, context, benchmark_period, "BROAD_CATEGORY", "CATEGORY_POOL", config_hash))
    for metric_name in rule.ranking_metrics:
        top_entities = _top_entities(metric_frame, products, context, benchmark_period, metric_name, rule.top_n)
        for row in broad_pairs:
            if row["peer_entity_id"] in top_entities:
                output.append(_peer_row(row, rule, context, benchmark_period, "TOP_N", metric_name, config_hash))
    return _dedupe(output)


def _direct_rows(
    products: pl.DataFrame,
    rule: PeerRule,
    context: AnalysisContext,
    benchmark_period: object,
    config_hash: str,
) -> list[dict[str, Any]]:
    dimensions = tuple(rule.required_dimensions)
    include_self = rule.self_inclusion == "INCLUDE_SELF"
    rows = [
        _peer_row(row, rule, context, benchmark_period, "DIRECT_PEER_GROUP", "DIRECT_DIMENSIONS", config_hash)
        for row in _pairs(products, dimensions, include_self=include_self)
    ]
    return _dedupe(rows)


def _pairs(products: pl.DataFrame, dimensions: tuple[str, ...], *, include_self: bool) -> list[dict[str, Any]]:
    left = products.rename({column: f"target_{column}" for column in products.columns})
    right = products.rename({column: f"peer_{column}" for column in products.columns})
    joined = left.join(
        right,
        left_on=[f"target_{dimension}" for dimension in dimensions],
        right_on=[f"peer_{dimension}" for dimension in dimensions],
        how="inner",
    )
    if not include_self:
        joined = joined.filter(pl.col("target_entity_id") != pl.col("peer_entity_id"))
    return joined.select(
        "target_entity_id",
        "peer_entity_id",
        "target_category",
        "peer_is_own_product",
    ).to_dicts()


def _top_entities(
    metric_frame: pl.DataFrame,
    products: pl.DataFrame,
    context: AnalysisContext,
    benchmark_period: object,
    metric_name: str,
    top_n: int,
) -> set[str]:
    metrics = metric_frame.filter(
        (pl.col("analysis_run_id") == context.analysis_run_id)
        & (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
        & (pl.col("metric_name") == metric_name)
    )
    if benchmark_period is not None:
        metrics = metrics.filter(pl.col("period") == benchmark_period)
    if metrics.is_empty():
        return set()
    ranked = products.select("entity_id", "category").join(metrics.select("entity_id", "metric_value"), on="entity_id", how="inner")
    ranked = ranked.sort(["category", "metric_value", "entity_id"], descending=[False, True, False])
    ranked = ranked.with_columns(pl.col("metric_value").rank("ordinal", descending=True).over("category").alias("__rank"))
    return set(ranked.filter(pl.col("__rank") <= top_n).get_column("entity_id").to_list())


def _peer_row(
    row: dict[str, Any],
    rule: PeerRule,
    context: AnalysisContext,
    benchmark_period: object,
    scope: str,
    source: str,
    config_hash: str,
) -> dict[str, Any]:
    return {
        "analysis_run_id": context.analysis_run_id,
        "retailer_id": context.retailer_id,
        "source_id": context.source_id,
        "rule_version": context.rule_version,
        "reference_period": benchmark_period,
        "target_entity_id": row["target_entity_id"],
        "peer_entity_id": row["peer_entity_id"],
        "category": row["target_category"],
        "benchmark_scope": scope,
        "pool_source": source,
        "benchmark_scope_id": f"{rule.rule_id}:{scope}:{source}:{row['target_category']}:{row['target_entity_id']}",
        "peer_rule_id": rule.rule_id,
        "peer_rule_version": rule.rule_version,
        "peer_config_hash": config_hash,
        "is_own_product": bool(row["peer_is_own_product"]),
        "is_competitor_product": not bool(row["peer_is_own_product"]),
    }


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        key = (row["target_entity_id"], row["peer_entity_id"], row["benchmark_scope"], row["pool_source"])
        if key not in seen:
            seen.add(key)
            output.append(row)
    return output


def _benchmark_period(price_segments: pl.DataFrame, request: BenchmarkRequest) -> object:
    if request.benchmark_period is not None:
        return request.benchmark_period
    if price_segments.is_empty():
        return None
    return price_segments.get_column("reference_period").max()


def _product_scope(product_frame: pl.DataFrame, context: AnalysisContext) -> pl.DataFrame:
    scoped = product_frame.filter(
        (pl.col("analysis_run_id") == context.analysis_run_id)
        & (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
    )
    if "is_own_product" not in scoped.columns:
        scoped = scoped.with_columns(pl.lit(False).alias("is_own_product"))
    return scoped
