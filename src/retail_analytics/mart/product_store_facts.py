"""Filterable SKU x store serving facts for dashboard intersections."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from retail_analytics.mart.builds import MartBuildMetadata
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA, RangeAggregationStrategy
from retail_analytics.mart.scopes import PrivateLabelScope

PRODUCT_STORE_SERVING_FACT_GRAIN = "sku_store"
PRODUCT_STORE_SERVING_VERSION = "product_store_serving.v1"
PRODUCT_STORE_SUPPORTED_CONCEPTS = frozenset(
    {
        "revenue_vat",
        "revenue",
        "units",
        "retailer_margin_abs",
        "retailer_margin_pct",
        "weighted_shelf_price_vat",
        "weighted_input_price_vat",
    }
)
PRODUCT_STORE_FACT_SCHEMA = {
    **MART_METRIC_FACT_SCHEMA,
    "category": pl.Utf8,
    "manufacturer": pl.Utf8,
    "brand": pl.Utf8,
    "canonical_product_id": pl.Utf8,
    "canonical_store_id": pl.Utf8,
    "sku_name": pl.Utf8,
    "package": pl.Utf8,
    "volume_l": pl.Float64,
    "store_format": pl.Utf8,
    "region": pl.Utf8,
    "serving_fact_grain": pl.Utf8,
    "serving_projection_version": pl.Utf8,
}

_REQUIRED_COLUMNS = {
    "retailer_id",
    "source_id",
    "analysis_run_id",
    "period",
    "category",
    "manufacturer",
    "brand",
    "canonical_product_id",
    "canonical_store_id",
    "units",
    "revenue_vat",
    "revenue_net",
    "retailer_margin_abs",
    "shelf_price_vat",
    "input_price_vat",
}


def build_product_store_metric_facts(
    enriched_frame: pl.DataFrame,
    *,
    build_metadata: MartBuildMetadata,
    source_revision_id: str | None = None,
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
    created_at: datetime | None = None,
    business_period_id_format: str = "%Y-%m",
) -> pl.DataFrame:
    """Materialize period x SKU x store facts without changing metric formulas."""

    if enriched_frame.is_empty():
        return pl.DataFrame(schema=PRODUCT_STORE_FACT_SCHEMA)
    missing = sorted(_REQUIRED_COLUMNS - set(enriched_frame.columns))
    if missing:
        raise ValueError(f"Product-store serving input missing required columns: {', '.join(missing)}")
    scope = PrivateLabelScope(private_label_scope)
    frame = enriched_frame
    if "source_revision_id" in frame.columns:
        revisions = tuple(str(item) for item in frame.get_column("source_revision_id").drop_nulls().unique().to_list())
        if len(revisions) > 1:
            raise ValueError("Product-store serving facts require one source_revision_id per build input")
        if source_revision_id is not None and revisions and revisions[0] != source_revision_id:
            raise ValueError("Product-store serving source_revision_id does not match input rows")
        if source_revision_id is None and revisions:
            source_revision_id = revisions[0]
    if scope != PrivateLabelScope.INCLUDE:
        if "private_label_flag" not in frame.columns:
            return pl.DataFrame(schema=PRODUCT_STORE_FACT_SCHEMA)
        frame = frame.filter(pl.col("private_label_flag") == (scope == PrivateLabelScope.ONLY))
    if frame.is_empty():
        return pl.DataFrame(schema=PRODUCT_STORE_FACT_SCHEMA)

    period_grain = build_metadata.period_grain or "month"
    revision_id = source_revision_id or _single_source_revision(build_metadata)
    timestamp = created_at or datetime.now(UTC)
    with_periods = frame.with_columns(
        pl.col("period").cast(pl.Date).alias("period_start"),
        pl.col("period").cast(pl.Date).map_elements(lambda value: _period_end(value, period_grain), return_dtype=pl.Date).alias("period_end"),
        pl.col("period").cast(pl.Date).dt.strftime(business_period_id_format).alias("business_period_id"),
        (pl.col("shelf_price_vat").cast(pl.Float64) * pl.col("units").cast(pl.Float64)).alias("shelf_price_vat_numerator"),
        (pl.col("input_price_vat").cast(pl.Float64) * pl.col("units").cast(pl.Float64)).alias("input_price_vat_numerator"),
    )
    dimension_columns = [
        "retailer_id",
        "source_id",
        "analysis_run_id",
        "period_start",
        "period_end",
        "business_period_id",
        "category",
        "manufacturer",
        "brand",
        "canonical_product_id",
        "canonical_store_id",
        "sku_name",
    ]
    if "package" not in with_periods.columns:
        with_periods = with_periods.with_columns(pl.lit(None, dtype=pl.Utf8).alias("package"))
    if "volume_l" not in with_periods.columns:
        with_periods = with_periods.with_columns(pl.lit(None, dtype=pl.Float64).alias("volume_l"))
    dimension_columns.extend(["package", "volume_l"])
    for optional in ("store_format", "region"):
        if optional not in with_periods.columns:
            with_periods = with_periods.with_columns(pl.lit(None, dtype=pl.Utf8).alias(optional))
        dimension_columns.append(optional)

    grouped = with_periods.group_by(dimension_columns).agg(
        pl.col("units").cast(pl.Float64).sum().alias("units"),
        pl.col("revenue_vat").cast(pl.Float64).sum().alias("revenue_vat"),
        pl.col("revenue_net").cast(pl.Float64).sum().alias("revenue"),
        pl.col("retailer_margin_abs").cast(pl.Float64).sum().alias("retailer_margin_abs"),
        pl.col("shelf_price_vat_numerator").cast(pl.Float64).sum().alias("weighted_shelf_price_vat_numerator"),
        pl.col("input_price_vat_numerator").cast(pl.Float64).sum().alias("weighted_input_price_vat_numerator"),
    )

    rows: list[dict[str, Any]] = []
    for row in grouped.to_dicts():
        rows.extend(_metric_rows(row, build_metadata, revision_id, scope, timestamp, period_grain))
    return pl.DataFrame(rows, schema=PRODUCT_STORE_FACT_SCHEMA)


def write_product_store_metric_facts(frame: pl.DataFrame, path: str | Path) -> Path:
    """Persist product-store serving facts as a single parquet file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.select([pl.col(column).cast(dtype) for column, dtype in PRODUCT_STORE_FACT_SCHEMA.items()]).write_parquet(target)
    return target


def read_product_store_metric_facts(path: str | Path) -> pl.DataFrame:
    """Read product-store serving facts with deterministic column order."""

    frame = pl.read_parquet(Path(path))
    for column, dtype in PRODUCT_STORE_FACT_SCHEMA.items():
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=dtype).alias(column))
    return frame.select([pl.col(column).cast(dtype) for column, dtype in PRODUCT_STORE_FACT_SCHEMA.items()])


def _metric_rows(
    row: dict[str, Any],
    build: MartBuildMetadata,
    source_revision_id: str,
    scope: PrivateLabelScope,
    created_at: datetime,
    period_grain: str,
) -> list[dict[str, Any]]:
    denominator_units = _float(row["units"])
    revenue = _float(row["revenue"])
    margin = _float(row["retailer_margin_abs"])
    specs = (
        ("revenue_vat", "sum", RangeAggregationStrategy.SUM_AVAILABLE_PERIODS, _float(row["revenue_vat"]), None, None),
        ("revenue", "sum", RangeAggregationStrategy.SUM_AVAILABLE_PERIODS, revenue, None, None),
        ("units", "sum", RangeAggregationStrategy.SUM_AVAILABLE_PERIODS, denominator_units, None, None),
        ("retailer_margin_abs", "sum", RangeAggregationStrategy.SUM_AVAILABLE_PERIODS, margin, None, None),
        (
            "retailer_margin_pct",
            "ratio_of_sums",
            RangeAggregationStrategy.RATIO_OF_SUMS,
            None if revenue == 0 else margin / revenue,
            margin,
            revenue,
        ),
        (
            "weighted_shelf_price_vat",
            "weighted_average",
            RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
            None if denominator_units == 0 else _float(row["weighted_shelf_price_vat_numerator"]) / denominator_units,
            _float(row["weighted_shelf_price_vat_numerator"]),
            denominator_units,
        ),
        (
            "weighted_input_price_vat",
            "weighted_average",
            RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
            None if denominator_units == 0 else _float(row["weighted_input_price_vat_numerator"]) / denominator_units,
            _float(row["weighted_input_price_vat_numerator"]),
            denominator_units,
        ),
    )
    parent_ids = json.dumps(
        {
            "category": row.get("category"),
            "manufacturer": row.get("manufacturer"),
            "brand": row.get("brand"),
            "canonical_product_id": row.get("canonical_product_id"),
            "canonical_store_id": row.get("canonical_store_id"),
            "package": row.get("package"),
            "volume_l": row.get("volume_l"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    result: list[dict[str, Any]] = []
    for concept, aggregation, strategy, value, numerator, denominator in specs:
        result.append(
            {
                "retailer_id": row["retailer_id"],
                "source_id": row["source_id"],
                "source_revision_id": source_revision_id,
                "analysis_run_id": row["analysis_run_id"],
                "mart_build_id": build.mart_build_id,
                "private_label_scope": scope.value,
                "period_grain": period_grain,
                "period_start": row["period_start"],
                "period_end": row["period_end"],
                "business_period_id": row["business_period_id"],
                "grain_id": PRODUCT_STORE_SERVING_FACT_GRAIN,
                "entity_id": f"{row['canonical_product_id']}|{row['canonical_store_id']}",
                "parent_entity_ids": parent_ids,
                "metric_concept": concept,
                "metric_name": concept,
                "metric_definition_id": f"{row['retailer_id']}.{PRODUCT_STORE_SERVING_FACT_GRAIN}.{concept}.v1",
                "metric_definition_version": "v1",
                "metric_config_hash": next(iter(build.metric_config_hashes), ""),
                "semantic_family": concept,
                "semantic_compatibility_version": "v1",
                "cross_retailer_comparable": False,
                "value": value,
                "numerator_value": numerator,
                "denominator_value": denominator,
                "business_rule_id": None,
                "denominator_universe_type": None,
                "store_alias_mapping_version": None,
                "numerator_metric_name": None,
                "denominator_metric_name": None,
                "aggregation": aggregation,
                "range_aggregation_strategy": strategy.value,
                "share_scope": None,
                "rule_version": next(iter(build.rule_versions), None),
                "quality_status": "valid",
                "quality_flags": None,
                "created_at": created_at,
                "category": row.get("category"),
                "manufacturer": row.get("manufacturer"),
                "brand": row.get("brand"),
                "canonical_product_id": row.get("canonical_product_id"),
                "canonical_store_id": row.get("canonical_store_id"),
                "sku_name": row.get("sku_name"),
                "package": row.get("package"),
                "volume_l": _optional_float(row.get("volume_l")),
                "store_format": row.get("store_format"),
                "region": row.get("region"),
                "serving_fact_grain": PRODUCT_STORE_SERVING_FACT_GRAIN,
                "serving_projection_version": PRODUCT_STORE_SERVING_VERSION,
            }
        )
    return result


def _single_source_revision(build: MartBuildMetadata) -> str:
    if len(build.source_revision_ids) != 1:
        raise ValueError("Product-store serving facts require an explicit source_revision_id for multi-revision builds")
    return build.source_revision_ids[0]


def _float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return _float(value)


def _period_end(value: date, period_grain: str) -> date:
    if period_grain == "month":
        import calendar

        return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])
    return value
