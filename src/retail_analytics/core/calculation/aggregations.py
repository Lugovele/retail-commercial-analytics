"""Metric aggregation primitives."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from retail_analytics.metrics.registry import MetricDefinition
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport


@dataclass(frozen=True)
class MetricsResult:
    metrics: pl.DataFrame
    quality_report: QualityReport


def calculate_metrics(
    frame: pl.DataFrame,
    definitions: Sequence[MetricDefinition],
    context: AnalysisContext,
    *,
    metric_config_hash: str = "",
) -> MetricsResult:
    """Calculate configured metrics as a long lineage-preserving table."""
    metric_frames: list[pl.DataFrame] = []
    issues: list[QualityIssue] = []
    scoped = frame.filter(
        (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
        & (pl.col("analysis_run_id") == context.analysis_run_id)
    )
    pending = list(definitions)
    while pending:
        progressed = False
        for definition in tuple(pending):
            if not _definition_inputs_available(scoped, definition, metric_frames):
                continue
            pending.remove(definition)
            progressed = True
            metric_frame, metric_issues = _calculate_one(
                scoped,
                definition,
                context,
                metric_config_hash,
                metric_frames,
            )
            metric_frames.append(metric_frame)
            issues.extend(metric_issues)
        if not progressed:
            missing = ", ".join(definition.name for definition in pending)
            issues.append(QualityIssue("MISSING_METRIC_DEPENDENCY", "FATAL", 0, (), f"Metric dependencies could not be resolved: {missing}."))
            break
    if not metric_frames:
        return MetricsResult(pl.DataFrame(), QualityReport(tuple(issues)))
    return MetricsResult(pl.concat(metric_frames, how="diagonal"), QualityReport(tuple(issues)))


def calculate_metric_share(
    metric_frame: pl.DataFrame,
    *,
    value_concepts: Sequence[str] = ("revenue", "units", "retailer_margin_abs"),
) -> MetricsResult:
    """Calculate configured denominator-scope shares for metric rows."""
    if metric_frame.is_empty():
        return MetricsResult(pl.DataFrame(), QualityReport())
    base = metric_frame.filter(pl.col("concept").is_in(list(value_concepts)))
    if "share_denominator_scope" in base.columns:
        base = base.filter(pl.col("share_denominator_scope").is_not_null())
    else:
        base = base.filter(pl.col("entity_type").is_in(["sku", "brand", "manufacturer"]))
        base = base.with_columns(pl.lit("category").alias("share_denominator_scope"))
    if base.is_empty():
        return MetricsResult(pl.DataFrame(), QualityReport())

    frames: list[pl.DataFrame] = []
    issues: list[QualityIssue] = []
    for scope in sorted(base.get_column("share_denominator_scope").drop_nulls().unique().to_list()):
        scoped = base.filter(pl.col("share_denominator_scope") == scope)
        total_keys = _share_total_keys(scoped, str(scope))
        if not total_keys:
            continue
        totals = scoped.group_by(total_keys).agg(pl.col("metric_value").sum().alias("share_total"))
        joined = scoped.join(
            totals,
            on=total_keys,
            how="left",
        )
        zero_count = joined.filter(pl.col("share_total") == 0).height
        if zero_count:
            issues.append(
                QualityIssue(
                    "ZERO_SHARE_DENOMINATOR",
                    "WARNING",
                    zero_count,
                    (),
                    f"{scope} share denominator is zero.",
                )
            )
        frames.append(_share_rows(joined, str(scope)))
    if not frames:
        return MetricsResult(pl.DataFrame(), QualityReport(tuple(issues)))
    return MetricsResult(pl.concat(frames, how="diagonal"), QualityReport(tuple(issues)))


def _share_total_keys(frame: pl.DataFrame, scope: str) -> list[str]:
    keys = [
        "analysis_run_id",
        "retailer_id",
        "source_id",
        "period",
        "entity_type",
        "concept",
        "metric_definition_id",
        "metric_definition_version",
        "grain_id",
    ]
    if scope == "category":
        keys.append("category")
    return [key for key in keys if key in frame.columns]


def _share_rows(joined: pl.DataFrame, scope: str) -> pl.DataFrame:
    share = joined.with_columns(
        pl.when(pl.col("share_total") == 0)
        .then(None)
        .otherwise(pl.col("metric_value") / pl.col("share_total"))
        .alias("metric_value"),
        pl.col("metric_value").alias("numerator_value"),
        pl.col("share_total").alias("denominator_value"),
        pl.col("concept").replace({"retailer_margin_abs": "margin"}).alias("__share_base_concept"),
    ).with_columns(
        (pl.lit(scope) + pl.lit("_") + pl.col("__share_base_concept") + pl.lit("_share")).alias("concept"),
        (pl.col("metric_definition_id") + pl.lit(".share")).alias("metric_definition_id"),
        pl.lit("share").alias("aggregation"),
    ).drop(["share_total", "__share_base_concept"])
    return share


def _calculate_one(
    frame: pl.DataFrame,
    definition: MetricDefinition,
    context: AnalysisContext,
    metric_config_hash: str,
    prior_metrics: Sequence[pl.DataFrame],
) -> tuple[pl.DataFrame, list[QualityIssue]]:
    group_cols = _group_columns(definition)
    issues: list[QualityIssue] = []
    if definition.aggregation == "sum":
        aggregated = frame.group_by(group_cols).agg(pl.col(definition.source_column or definition.name).sum().alias("metric_value"))
        aggregated = aggregated.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("numerator_value"),
            pl.lit(None, dtype=pl.Float64).alias("denominator_value"),
        )
    elif definition.aggregation == "ratio_of_sums":
        if (definition.numerator or "") in frame.columns and (definition.denominator or "") in frame.columns:
            aggregated = frame.group_by(group_cols).agg(
                pl.col(definition.numerator or "").sum().alias("numerator_value"),
                pl.col(definition.denominator or "").sum().alias("denominator_value"),
            )
        else:
            aggregated = _derived_ratio_from_metrics(definition, group_cols, prior_metrics)
        zero_count = aggregated.filter(pl.col("denominator_value") == 0).height
        if zero_count:
            issue_code = _zero_denominator_code(definition)
            issues.append(QualityIssue(issue_code, "WARNING", zero_count, (), f"Zero denominator for {definition.name}."))
        aggregated = aggregated.with_columns(
            pl.when((pl.col("denominator_value") == 0) | pl.col("denominator_value").is_null())
            .then(None)
            .otherwise(pl.col("numerator_value") / pl.col("denominator_value"))
            .alias("metric_value")
        )
    elif definition.aggregation == "weighted_average":
        value_col = definition.value_column or definition.name
        weight_col = definition.weight_column or "units"
        weighted = frame.with_columns(
            pl.when((pl.col(weight_col) > 0) & pl.col(value_col).is_not_null())
            .then(pl.col(weight_col))
            .otherwise(0.0)
            .alias("__metric_weight"),
            pl.when((pl.col(weight_col) > 0) & pl.col(value_col).is_not_null())
            .then(pl.col(value_col) * pl.col(weight_col))
            .otherwise(0.0)
            .alias("__metric_weighted_value"),
        )
        aggregated = weighted.group_by(group_cols).agg(
            pl.col("__metric_weighted_value").sum().alias("numerator_value"),
            pl.col("__metric_weight").sum().alias("denominator_value"),
        )
        zero_count = aggregated.filter(pl.col("denominator_value") == 0).height
        if zero_count:
            issues.append(QualityIssue("ZERO_METRIC_DENOMINATOR", "WARNING", zero_count, (), f"Zero weight denominator for {definition.name}."))
        aggregated = aggregated.with_columns(
            pl.when(pl.col("denominator_value") == 0)
            .then(None)
            .otherwise(pl.col("numerator_value") / pl.col("denominator_value"))
            .alias("metric_value")
        )
    elif definition.aggregation == "distinct_count":
        source = _apply_condition(frame, definition.condition)
        calculation_cols = _calculation_group_columns(definition)
        universe = frame.select(group_cols).unique()
        counts = source.group_by(calculation_cols).agg(
            pl.col(definition.distinct_column or "").n_unique().cast(pl.Float64).alias("metric_value")
        )
        aggregated = universe.join(counts, on=calculation_cols, how="left").with_columns(
            pl.col("metric_value").fill_null(0.0)
        )
        aggregated = aggregated.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("numerator_value"),
            pl.lit(None, dtype=pl.Float64).alias("denominator_value"),
        )
    else:
        raise ValueError(f"Unsupported aggregation: {definition.aggregation}")

    return _add_metadata(aggregated, definition, context, metric_config_hash), issues


def _apply_condition(frame: pl.DataFrame, condition: dict[str, Any] | None) -> pl.DataFrame:
    if not condition:
        return frame
    result = frame
    for column, expected in condition.items():
        if isinstance(expected, dict) and "gt" in expected:
            result = result.filter(pl.col(column) > expected["gt"])
        elif isinstance(expected, dict) and "ge" in expected:
            result = result.filter(pl.col(column) >= expected["ge"])
        else:
            result = result.filter(pl.col(column) == expected)
    return result


def _group_columns(definition: MetricDefinition) -> list[str]:
    return ["analysis_run_id", "retailer_id", "source_id", *definition.grain]


def _calculation_group_columns(definition: MetricDefinition) -> list[str]:
    grain = definition.broadcast_grain or definition.grain
    return ["analysis_run_id", "retailer_id", "source_id", *grain]


def _add_metadata(
    frame: pl.DataFrame,
    definition: MetricDefinition,
    context: AnalysisContext,
    metric_config_hash: str,
) -> pl.DataFrame:
    result = frame.with_columns(
        pl.lit(definition.name).alias("metric_name"),
        pl.lit(definition.definition_id).alias("metric_definition_id"),
        pl.lit(definition.definition_version).alias("metric_definition_version"),
        pl.lit(metric_config_hash).alias("metric_config_hash"),
        pl.lit(definition.concept).alias("concept"),
        pl.lit(definition.aggregation).alias("aggregation"),
        pl.lit(context.rule_version).alias("rule_version"),
        pl.lit(definition.entity_type).alias("entity_type"),
        pl.lit(definition.grain_id or _default_grain_id(definition)).alias("grain_id"),
        pl.lit(_share_denominator_scope(definition), dtype=pl.Utf8).alias("share_denominator_scope"),
    )
    if "canonical_product_id" in result.columns:
        result = result.with_columns(pl.col("canonical_product_id").alias("entity_id"))
    elif "brand" in result.columns:
        result = result.with_columns(pl.col("brand").alias("entity_id"))
    elif "manufacturer" in result.columns:
        result = result.with_columns(pl.col("manufacturer").alias("entity_id"))
    elif "category" in result.columns:
        result = result.with_columns(pl.col("category").alias("entity_id"))
    elif "canonical_store_id" in result.columns:
        result = result.with_columns(pl.col("canonical_store_id").alias("entity_id"))
    else:
        result = result.with_columns(pl.lit("ALL").alias("entity_id"))
    return result


def _default_grain_id(definition: MetricDefinition) -> str:
    if definition.entity_type:
        return definition.entity_type
    return "__".join(definition.grain)


def _share_denominator_scope(definition: MetricDefinition) -> str | None:
    if definition.share_denominator_scope is not None:
        return definition.share_denominator_scope
    if definition.entity_type in {"sku", "brand", "manufacturer"}:
        return "category"
    return None


def _derived_ratio_from_metrics(
    definition: MetricDefinition,
    group_cols: list[str],
    prior_metrics: Sequence[pl.DataFrame],
) -> pl.DataFrame:
    prior = pl.concat(prior_metrics, how="diagonal") if prior_metrics else pl.DataFrame()
    if prior.is_empty():
        return pl.DataFrame({column: [] for column in [*group_cols, "numerator_value", "denominator_value"]})
    numerator = _metric_values(prior, definition.numerator or "", group_cols, "numerator_value")
    denominator = _metric_values(prior, definition.denominator or "", group_cols, "denominator_value")
    return denominator.join(numerator, on=group_cols, how="left").with_columns(
        pl.col("numerator_value").fill_null(0.0)
    )


def _metric_values(frame: pl.DataFrame, metric_name: str, group_cols: list[str], value_alias: str) -> pl.DataFrame:
    return frame.filter(pl.col("metric_name") == metric_name).select(
        [*group_cols, pl.col("metric_value").alias(value_alias)]
    )


def _zero_denominator_code(definition: MetricDefinition) -> str:
    if definition.concept == "distribution":
        return "ZERO_DISTRIBUTION_DENOMINATOR"
    if definition.concept == "velocity":
        return "ZERO_VELOCITY_DENOMINATOR"
    return "ZERO_METRIC_DENOMINATOR"


def _definition_inputs_available(
    frame: pl.DataFrame,
    definition: MetricDefinition,
    prior_metrics: Sequence[pl.DataFrame],
) -> bool:
    if definition.aggregation != "ratio_of_sums":
        return True
    if (definition.numerator or "") in frame.columns and (definition.denominator or "") in frame.columns:
        return True
    available = set()
    for metrics in prior_metrics:
        if "metric_name" in metrics.columns:
            available.update(metrics["metric_name"].unique().to_list())
    return (definition.numerator or "") in available and (definition.denominator or "") in available
