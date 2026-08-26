"""Long-format mart metric fact projection."""

from __future__ import annotations

import calendar
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl

from retail_analytics.mart.builds import MartBuildMetadata
from retail_analytics.mart.scopes import PrivateLabelScope


class RangeAggregationStrategy(StrEnum):
    """Declared future selected-range behavior for metric facts."""

    SUM_AVAILABLE_PERIODS = "sum_available_periods"
    RATIO_OF_SUMS = "ratio_of_sums"
    WEIGHTED_RATIO_OF_SUMS = "weighted_ratio_of_sums"
    RECOMPUTE_FROM_COMPONENTS = "recompute_from_components"
    RECOMPUTE_SHARE_SCOPE = "recompute_share_scope"
    PERIOD_ONLY = "period_only"
    UNSUPPORTED = "unsupported"


MART_METRIC_FACT_SCHEMA = {
    "retailer_id": pl.Utf8,
    "source_id": pl.Utf8,
    "source_revision_id": pl.Utf8,
    "analysis_run_id": pl.Utf8,
    "mart_build_id": pl.Utf8,
    "private_label_scope": pl.Utf8,
    "period_grain": pl.Utf8,
    "period_start": pl.Date,
    "period_end": pl.Date,
    "business_period_id": pl.Utf8,
    "grain_id": pl.Utf8,
    "entity_id": pl.Utf8,
    "parent_entity_ids": pl.Utf8,
    "metric_concept": pl.Utf8,
    "metric_name": pl.Utf8,
    "metric_definition_id": pl.Utf8,
    "metric_definition_version": pl.Utf8,
    "metric_config_hash": pl.Utf8,
    "semantic_family": pl.Utf8,
    "semantic_compatibility_version": pl.Utf8,
    "cross_retailer_comparable": pl.Boolean,
    "value": pl.Float64,
    "numerator_value": pl.Float64,
    "denominator_value": pl.Float64,
    "business_rule_id": pl.Utf8,
    "denominator_universe_type": pl.Utf8,
    "store_alias_mapping_version": pl.Utf8,
    "numerator_metric_name": pl.Utf8,
    "denominator_metric_name": pl.Utf8,
    "aggregation": pl.Utf8,
    "range_aggregation_strategy": pl.Utf8,
    "share_scope": pl.Utf8,
    "rule_version": pl.Utf8,
    "quality_status": pl.Utf8,
    "quality_flags": pl.Utf8,
    "created_at": pl.Datetime,
}


def metric_fact_semantic_identity_columns(*, include_mart_build_id: bool = True) -> tuple[str, ...]:
    """Return the uniqueness contract for mart metric facts."""

    lineage = ("mart_build_id", "analysis_run_id") if include_mart_build_id else ("analysis_run_id",)
    return (
        "retailer_id",
        "source_id",
        *lineage,
        "private_label_scope",
        "period_grain",
        "period_start",
        "period_end",
        "grain_id",
        "entity_id",
        "parent_entity_ids",
        "metric_definition_id",
        "metric_definition_version",
        "metric_config_hash",
        "rule_version",
    )


def range_strategy_for_metric(
    *,
    aggregation: str | None,
    metric_concept: str | None,
    metric_name: str | None = None,
) -> RangeAggregationStrategy:
    """Return conservative strategy when component availability is unknown."""

    concept = (metric_concept or "").lower()
    name = (metric_name or "").lower()
    aggregation_name = (aggregation or "").lower()
    combined = f"{concept} {name}"
    if "abc" in combined:
        return RangeAggregationStrategy.PERIOD_ONLY
    if concept.endswith("_share") or name.endswith("_share") or "share" in combined:
        return RangeAggregationStrategy.PERIOD_ONLY
    if "distribution" in combined or "velocity" in combined or "per_selling_store" in combined:
        return RangeAggregationStrategy.PERIOD_ONLY
    if aggregation_name == "sum":
        return RangeAggregationStrategy.SUM_AVAILABLE_PERIODS
    if aggregation_name == "ratio_of_sums":
        return RangeAggregationStrategy.RATIO_OF_SUMS
    if aggregation_name == "weighted_average":
        return RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS
    if aggregation_name == "distinct_count":
        return RangeAggregationStrategy.PERIOD_ONLY
    return RangeAggregationStrategy.UNSUPPORTED


def build_mart_metric_facts(
    metric_frame: pl.DataFrame,
    *,
    build_metadata: MartBuildMetadata,
    source_revision_id: str | Mapping[str, str] | None = None,
    created_at: datetime | None = None,
    quality_status: str = "valid",
    quality_flags: str | None = None,
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
) -> pl.DataFrame:
    """Project existing metric rows into mart metric facts without recalculation."""

    if metric_frame.is_empty():
        return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA)
    normalized_input = _normalize_metric_columns(metric_frame)
    missing = sorted(set(_REQUIRED_SOURCE_COLUMNS) - set(normalized_input.columns))
    if missing:
        raise ValueError(f"Metric frame missing required columns: {', '.join(missing)}")
    _validate_metric_rows_for_build(normalized_input, build_metadata)
    _validate_source_revision_mapping(normalized_input, source_revision_id, build_metadata)

    period_grain = build_metadata.period_grain or "month"
    resolved_private_label_scope = PrivateLabelScope(private_label_scope)
    timestamp = created_at or datetime.now(UTC)
    input_columns = frozenset(normalized_input.columns)
    projected = _with_optional_columns(normalized_input.clone())
    projected = projected.with_columns(
        _source_revision_expr(source_revision_id, input_columns).alias("source_revision_id"),
        pl.lit(build_metadata.mart_build_id).alias("mart_build_id"),
        _private_label_scope_expr(resolved_private_label_scope, input_columns).alias("private_label_scope"),
        _period_start_expr().alias("period_start"),
        pl.lit(period_grain).alias("period_grain"),
        pl.col("concept").alias("metric_concept"),
        pl.col("name").alias("metric_name"),
        pl.col("metric_value").cast(pl.Float64).alias("value"),
        _parent_entity_ids_expr(input_columns).alias("parent_entity_ids"),
        pl.lit(None, dtype=pl.Utf8).alias("semantic_family"),
        pl.lit(None, dtype=pl.Utf8).alias("semantic_compatibility_version"),
        pl.lit(False).alias("cross_retailer_comparable"),
        pl.lit(quality_status).alias("quality_status"),
        pl.lit(quality_flags).alias("quality_flags"),
        pl.lit(timestamp).alias("created_at"),
    )
    projected = projected.with_columns(
        pl.col("period_start").map_elements(lambda value: _period_end(value, period_grain), return_dtype=pl.Date).alias("period_end"),
        _business_period_expr(input_columns).alias("business_period_id"),
    )
    projected = projected.with_columns(
        pl.struct(["aggregation", "metric_concept", "metric_name", "numerator_value", "denominator_value", "share_scope"])
        .map_elements(lambda row: _range_strategy_for_row(row).value, return_dtype=pl.Utf8)
        .alias("range_aggregation_strategy")
    )
    facts = projected.select([pl.col(column).cast(dtype) for column, dtype in MART_METRIC_FACT_SCHEMA.items()])
    duplicates = duplicate_semantic_identities(facts)
    if not duplicates.is_empty():
        raise ValueError("Duplicate mart metric semantic identities detected")
    if facts.filter(pl.col("source_revision_id").is_null() | (pl.col("source_revision_id") == "")).height:
        raise ValueError("Mart metric facts require source_revision_id for every row")
    return facts


def duplicate_semantic_identities(frame: pl.DataFrame, *, include_mart_build_id: bool = True) -> pl.DataFrame:
    """Return duplicated semantic identity groups."""

    if frame.is_empty():
        return pl.DataFrame()
    columns = metric_fact_semantic_identity_columns(include_mart_build_id=include_mart_build_id)
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"Frame missing identity columns: {', '.join(missing)}")
    return frame.group_by(list(columns)).len().filter(pl.col("len") > 1)


def write_mart_metric_facts(frame: pl.DataFrame, path: str | Path) -> Path:
    """Persist mart metric facts as a single Parquet file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _with_optional_columns(frame).select([pl.col(column).cast(dtype) for column, dtype in MART_METRIC_FACT_SCHEMA.items()]).write_parquet(target)
    return target


def write_mart_metric_fact_dataset(frame: pl.DataFrame, storage_root: str | Path) -> tuple[Path, ...]:
    """Persist facts under the approved mart_metric_facts partition layout."""

    root = Path(storage_root) / "mart_metric_facts"
    written: list[Path] = []
    columns = ["retailer_id", "source_id", "period_grain", "period_start", "mart_build_id"]
    for values in frame.select(columns).unique().iter_rows(named=True):
        partition = frame
        for column, value in values.items():
            partition = partition.filter(pl.col(column) == value)
        path = root
        for column in columns:
            path = path / f"{column}={values[column]}"
        written.append(write_mart_metric_facts(partition, path / "facts.parquet"))
    return tuple(written)


def read_mart_metric_facts(path: str | Path) -> pl.DataFrame:
    """Read mart metric facts from Parquet with deterministic column order."""

    return _with_optional_columns(pl.read_parquet(Path(path))).select(
        [pl.col(column).cast(dtype) for column, dtype in MART_METRIC_FACT_SCHEMA.items()]
    )


_REQUIRED_SOURCE_COLUMNS = (
    "analysis_run_id",
    "retailer_id",
    "source_id",
    "period",
    "grain_id",
    "entity_id",
    "concept",
    "name",
    "metric_definition_id",
    "metric_definition_version",
    "metric_config_hash",
    "metric_value",
    "numerator_value",
    "denominator_value",
    "aggregation",
    "rule_version",
)


def _normalize_metric_columns(frame: pl.DataFrame) -> pl.DataFrame:
    result = frame
    if "name" not in result.columns and "metric_name" in result.columns:
        result = result.with_columns(pl.col("metric_name").alias("name"))
    return result


def _with_optional_columns(frame: pl.DataFrame) -> pl.DataFrame:
    result = frame
    if "share_scope" not in result.columns and "share_denominator_scope" in result.columns:
        result = result.with_columns(pl.col("share_denominator_scope").alias("share_scope"))
    elif "share_scope" not in result.columns:
        result = result.with_columns(pl.lit(None, dtype=pl.Utf8).alias("share_scope"))
    if "business_period_id" not in result.columns:
        result = result.with_columns(pl.lit(None, dtype=pl.Utf8).alias("business_period_id"))
    for column in (
        "business_rule_id",
        "denominator_universe_type",
        "store_alias_mapping_version",
        "numerator_metric_name",
        "denominator_metric_name",
    ):
        if column not in result.columns:
            result = result.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
    return result


def _validate_metric_rows_for_build(frame: pl.DataFrame, metadata: MartBuildMetadata) -> None:
    checks = {
        "retailer_id": (metadata.retailer_id,),
        "source_id": metadata.source_ids,
        "analysis_run_id": metadata.analysis_run_ids,
        "metric_config_hash": metadata.metric_config_hashes,
        "rule_version": metadata.rule_versions,
    }
    for column, allowed in checks.items():
        actual = set(frame.get_column(column).unique().to_list())
        unexpected = sorted(actual - set(allowed))
        if unexpected:
            raise ValueError(f"Metric rows contain {column} outside mart build metadata: {unexpected}")


def _validate_source_revision_mapping(
    frame: pl.DataFrame,
    source_revision_id: str | Mapping[str, str] | None,
    metadata: MartBuildMetadata,
) -> None:
    source_ids = set(frame.get_column("source_id").unique().to_list())
    allowed_revisions = set(metadata.source_revision_ids)
    if source_revision_id is None:
        if "source_revision_id" not in frame.columns:
            raise ValueError("source_revision_id must be supplied or present in metric rows")
        unexpected = sorted(set(frame.get_column("source_revision_id").unique().to_list()) - allowed_revisions)
        if unexpected:
            raise ValueError(f"Metric rows contain source_revision_id outside mart build metadata: {unexpected}")
        return
    if isinstance(source_revision_id, str):
        if len(source_ids) > 1:
            raise ValueError("Multi-source mart builds require source_id to source_revision_id mapping")
        if source_revision_id not in allowed_revisions:
            raise ValueError("source_revision_id is outside mart build metadata")
        return
    missing = sorted(source_ids - set(source_revision_id))
    if missing:
        raise ValueError(f"Source revision mapping missing source ids: {missing}")
    unexpected = sorted(set(source_revision_id.values()) - allowed_revisions)
    if unexpected:
        raise ValueError(f"Source revision mapping contains revisions outside mart build metadata: {unexpected}")


def _source_revision_expr(source_revision_id: str | Mapping[str, str] | None, input_columns: frozenset[str]) -> pl.Expr:
    if source_revision_id is None:
        if "source_revision_id" not in input_columns:
            raise ValueError("source_revision_id must be supplied or present in metric rows")
        return pl.col("source_revision_id").cast(pl.Utf8)
    if isinstance(source_revision_id, str):
        return pl.lit(source_revision_id)
    return pl.col("source_id").replace_strict(dict(source_revision_id), default=None).cast(pl.Utf8)


def _private_label_scope_expr(scope: PrivateLabelScope, input_columns: frozenset[str]) -> pl.Expr:
    if "private_label_scope" in input_columns:
        return pl.col("private_label_scope").cast(pl.Utf8)
    return pl.lit(scope.value)


def _range_strategy_for_row(row: dict[str, Any]) -> RangeAggregationStrategy:
    concept = (row.get("metric_concept") or "").lower()
    name = (row.get("metric_name") or "").lower()
    aggregation = row.get("aggregation")
    combined = f"{concept} {name}"
    has_components = row.get("numerator_value") is not None and row.get("denominator_value") is not None
    if concept.endswith("_share") or name.endswith("_share") or "share" in combined:
        return RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE if has_components and row.get("share_scope") else RangeAggregationStrategy.PERIOD_ONLY
    if "distribution" in combined or "velocity" in combined or "per_selling_store" in combined:
        return RangeAggregationStrategy.PERIOD_ONLY
    if aggregation == "ratio_of_sums":
        return RangeAggregationStrategy.RATIO_OF_SUMS if has_components else RangeAggregationStrategy.PERIOD_ONLY
    if aggregation == "weighted_average":
        return RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS if has_components else RangeAggregationStrategy.PERIOD_ONLY
    return range_strategy_for_metric(aggregation=aggregation, metric_concept=concept, metric_name=name)


def _parent_entity_ids_expr(input_columns: frozenset[str]) -> pl.Expr:
    parent_columns = ("category", "manufacturer", "brand", "canonical_product_id", "canonical_store_id")
    return pl.struct([_optional_parent(column, input_columns) for column in parent_columns]).map_elements(
        lambda row: json.dumps({key: value for key, value in row.items() if value is not None}, sort_keys=True),
        return_dtype=pl.Utf8,
    )


def _optional_parent(column: str, input_columns: frozenset[str]) -> pl.Expr:
    if column in input_columns:
        return pl.col(column).cast(pl.Utf8).alias(column)
    return pl.lit(None, dtype=pl.Utf8).alias(column)


def _business_period_expr(input_columns: frozenset[str]) -> pl.Expr:
    if "business_period_id" in input_columns:
        return pl.coalesce(pl.col("business_period_id").cast(pl.Utf8), pl.col("period_start").dt.strftime("%Y-%m-%d"))
    return pl.col("period_start").dt.strftime("%Y-%m-%d")


def _period_start_expr() -> pl.Expr:
    period_text = pl.col("period").cast(pl.Utf8)
    return pl.coalesce(
        period_text.str.to_date("%Y-%m-%d", strict=False),
        (period_text + pl.lit("-01")).str.to_date("%Y-%m-%d", strict=False),
    )


def _period_end(period_start: date, period_grain: str) -> date:
    if period_grain == "month":
        last_day = calendar.monthrange(period_start.year, period_start.month)[1]
        return date(period_start.year, period_start.month, last_day)
    return period_start

