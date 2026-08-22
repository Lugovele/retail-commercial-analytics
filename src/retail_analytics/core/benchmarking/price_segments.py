"""Price segmentation over Slice 2 representative price metrics."""
from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from retail_analytics.core.benchmarking.contracts import (
    BenchmarkRequest,
    PriceSegmentResult,
    PriceSegmentRule,
)
from retail_analytics.core.benchmarking.periods import select_benchmark_period
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport


def build_price_segments(
    metric_frame: pl.DataFrame,
    product_frame: pl.DataFrame,
    rules: tuple[PriceSegmentRule, ...],
    context: AnalysisContext,
    request: BenchmarkRequest,
    *,
    config_hash: str = "",
) -> PriceSegmentResult:
    rows: list[dict[str, Any]] = []
    issues: list[QualityIssue] = []
    products = _scoped_products(product_frame, context)
    metrics = _scoped_metrics(metric_frame, context)
    scoped_rules = tuple(
        rule
        for rule in rules
        if rule.retailer_id == context.retailer_id
        and (rule.source_id is None or rule.source_id == context.source_id)
        and rule.rule_version == context.rule_version
    )
    for rule in scoped_rules:
        period = select_benchmark_period(metrics, request, rule.price_metric_name)
        if period is None:
            issues.append(QualityIssue("MISSING_PRICE_FOR_SEGMENT", "WARNING", 0, (), "No representative price metric rows."))
            continue
        price_rows = _price_rows(metrics, products, rule, period)
        categories = sorted(price_rows.get_column("category").unique().to_list()) if not price_rows.is_empty() else []
        for category in categories:
            category_rows = price_rows.filter(pl.col("category") == category)
            segment_rows, segment_issues = _segment_category(category_rows, rule, context, period, request, config_hash)
            rows.extend(segment_rows)
            issues.extend(segment_issues)
    return PriceSegmentResult(pl.DataFrame(rows), QualityReport(tuple(issues)), config_hash)


def _segment_category(
    frame: pl.DataFrame,
    rule: PriceSegmentRule,
    context: AnalysisContext,
    period: date,
    request: BenchmarkRequest,
    config_hash: str,
) -> tuple[list[dict[str, Any]], list[QualityIssue]]:
    output: list[dict[str, Any]] = []
    issues: list[QualityIssue] = []
    valid = frame.filter(pl.col("representative_price").is_not_null() & (pl.col("representative_price") > 0))
    valid_count = valid.height
    null_count = frame.filter(pl.col("representative_price").is_null()).height
    invalid_count = frame.filter(pl.col("representative_price").is_not_null() & (pl.col("representative_price") <= 0)).height
    if null_count:
        issues.append(QualityIssue("MISSING_PRICE_FOR_SEGMENT", "WARNING", null_count, (), "Some products have no representative price."))
    if invalid_count:
        issues.append(QualityIssue("INVALID_PRICE_FOR_SEGMENT", "WARNING", invalid_count, (), "Some products have non-positive representative price."))
    if 0 < valid_count < rule.min_segment_population:
        issues.append(QualityIssue("INSUFFICIENT_PRICE_SEGMENT_POPULATION", "WARNING", valid_count, (), "Valid price population is below configured minimum."))
    assignments = _valid_assignments(valid, rule) if valid_count >= rule.min_segment_population else {}
    for row in frame.sort("entity_id").to_dicts():
        price = row["representative_price"]
        if price is None:
            segment = "UNCLASSIFIED_PRICE_NULL"
        elif price <= 0:
            segment = "UNCLASSIFIED_PRICE_INVALID"
        elif valid_count < rule.min_segment_population:
            segment = "INSUFFICIENT_POPULATION"
        else:
            segment = assignments[row["entity_id"]]
        output.append(
            {
                "analysis_run_id": context.analysis_run_id,
                "retailer_id": context.retailer_id,
                "source_id": context.source_id,
                "rule_version": context.rule_version,
                "reference_period": period,
                "period_selection_mode": request.period_selection_mode,
                "category": row["category"],
                "entity_id": row["entity_id"],
                "price_metric_definition_id": row["metric_definition_id"],
                "price_metric_definition_version": row["metric_definition_version"],
                "representative_price": price,
                "price_segment": segment,
                "price_segment_rule_id": rule.rule_id,
                "price_segment_rule_version": rule.rule_version,
                "price_segment_config_hash": config_hash,
                "price_rank": row["price_rank"],
                "segment_population": valid_count,
            }
        )
    return output, issues


def _valid_assignments(frame: pl.DataFrame, rule: PriceSegmentRule) -> dict[str, str]:
    ordered = frame.sort(["representative_price", "entity_id"])
    total = ordered.height
    assignments: dict[str, str] = {}
    assigned = 0
    for group in ordered.group_by("representative_price", maintain_order=True).agg(pl.col("entity_id")).to_dicts():
        bucket_index = min(int(assigned * len(rule.segments) / total), len(rule.segments) - 1)
        for entity_id in group["entity_id"]:
            assignments[entity_id] = rule.segments[bucket_index]
        assigned += len(group["entity_id"])
    return assignments


def _price_rows(
    metric_frame: pl.DataFrame,
    products: pl.DataFrame,
    rule: PriceSegmentRule,
    period: date,
) -> pl.DataFrame:
    prices = metric_frame.filter(
        (pl.col("period") == period) & (pl.col("metric_name") == rule.price_metric_name)
    ).select(
        "analysis_run_id",
        "retailer_id",
        "source_id",
        "period",
        "entity_id",
        pl.col("metric_value").alias("representative_price"),
        "metric_definition_id",
        "metric_definition_version",
    )
    joined = products.join(prices, on=["analysis_run_id", "retailer_id", "source_id", "entity_id"], how="left")
    return joined.with_columns(
        pl.col("representative_price").rank("min").over("category").alias("price_rank")
    )


def _scoped_metrics(metric_frame: pl.DataFrame, context: AnalysisContext) -> pl.DataFrame:
    return metric_frame.filter(
        (pl.col("analysis_run_id") == context.analysis_run_id)
        & (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
    )


def _scoped_products(product_frame: pl.DataFrame, context: AnalysisContext) -> pl.DataFrame:
    return product_frame.filter(
        (pl.col("analysis_run_id") == context.analysis_run_id)
        & (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
    )
