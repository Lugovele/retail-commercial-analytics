"""Deterministic monthly store-universe mart artifacts."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from retail_analytics.mart.builds import MartBuildMetadata

STORE_UNIVERSE_VERSION = "store_universe.v1"
MONTHLY_NETWORK_UNIVERSE = "monthly_file_store_universe"
MONTHLY_STORE_FORMAT_UNIVERSE = "monthly_store_format_universe"

STORE_UNIVERSE_SCHEMA = {
    "retailer_id": pl.Utf8,
    "source_id": pl.Utf8,
    "source_revision_id": pl.Utf8,
    "analysis_run_id": pl.Utf8,
    "mart_build_id": pl.Utf8,
    "period_grain": pl.Utf8,
    "period_start": pl.Date,
    "period_end": pl.Date,
    "business_period_id": pl.Utf8,
    "canonical_store_id": pl.Utf8,
    "store_format": pl.Utf8,
    "region": pl.Utf8,
    "universe_type": pl.Utf8,
    "store_alias_mapping_version": pl.Utf8,
    "universe_build_version": pl.Utf8,
    "created_at": pl.Datetime,
}

_REQUIRED_COLUMNS = {
    "retailer_id",
    "source_id",
    "analysis_run_id",
    "period",
    "canonical_store_id",
}


def build_monthly_store_universe(
    frame: pl.DataFrame,
    *,
    build_metadata: MartBuildMetadata,
    source_revision_id: str | None = None,
    store_alias_mapping_version: str | None = None,
    created_at: datetime | None = None,
    business_period_id_format: str = "%Y-%m",
) -> pl.DataFrame:
    """Build monthly canonical-store membership after alias normalization."""

    if frame.is_empty():
        return pl.DataFrame(schema=STORE_UNIVERSE_SCHEMA)
    missing = sorted(_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"Store universe input missing required columns: {', '.join(missing)}")
    _validate_context(frame, build_metadata)
    revision_id = _resolve_source_revision_id(frame, build_metadata, source_revision_id)
    period_grain = build_metadata.period_grain or "month"
    timestamp = created_at or datetime.now(UTC)
    with_optional = frame
    for optional in ("store_format", "region"):
        if optional not in with_optional.columns:
            with_optional = with_optional.with_columns(pl.lit(None, dtype=pl.Utf8).alias(optional))
    with_periods = with_optional.with_columns(
        pl.col("period").cast(pl.Date).alias("period_start"),
        pl.col("period").cast(pl.Date).map_elements(lambda value: _period_end(value, period_grain), return_dtype=pl.Date).alias("period_end"),
        pl.col("period").cast(pl.Date).dt.strftime(business_period_id_format).alias("business_period_id"),
        pl.col("canonical_store_id").cast(pl.Utf8).alias("canonical_store_id"),
        pl.col("store_format").cast(pl.Utf8).alias("store_format"),
        pl.col("region").cast(pl.Utf8).alias("region"),
    )
    result = (
        with_periods.select(
            "retailer_id",
            "source_id",
            "analysis_run_id",
            "period_start",
            "period_end",
            "business_period_id",
            "canonical_store_id",
            "store_format",
            "region",
        )
        .unique()
        .with_columns(
            pl.lit(revision_id).alias("source_revision_id"),
            pl.lit(build_metadata.mart_build_id).alias("mart_build_id"),
            pl.lit(period_grain).alias("period_grain"),
            pl.lit(MONTHLY_NETWORK_UNIVERSE).alias("universe_type"),
            pl.lit(store_alias_mapping_version).alias("store_alias_mapping_version"),
            pl.lit(STORE_UNIVERSE_VERSION).alias("universe_build_version"),
            pl.lit(timestamp).alias("created_at"),
        )
        .select([pl.col(column).cast(dtype) for column, dtype in STORE_UNIVERSE_SCHEMA.items()])
        .sort(["period_start", "canonical_store_id", "store_format"])
    )
    _reject_ambiguous_store_format(result)
    return result


def write_monthly_store_universe(frame: pl.DataFrame, path: str | Path) -> Path:
    """Persist monthly store-universe membership as a Parquet file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.select([pl.col(column).cast(dtype) for column, dtype in STORE_UNIVERSE_SCHEMA.items()]).write_parquet(target)
    return target


def read_monthly_store_universe(path: str | Path) -> pl.DataFrame:
    """Read monthly store-universe membership with deterministic column order."""

    return pl.read_parquet(Path(path)).select([pl.col(column).cast(dtype) for column, dtype in STORE_UNIVERSE_SCHEMA.items()])


def _validate_context(frame: pl.DataFrame, metadata: MartBuildMetadata) -> None:
    checks = {
        "retailer_id": (metadata.retailer_id,),
        "source_id": metadata.source_ids,
        "analysis_run_id": metadata.analysis_run_ids,
    }
    for column, allowed in checks.items():
        actual = set(frame.get_column(column).unique().to_list())
        unexpected = sorted(actual - set(allowed))
        if unexpected:
            raise ValueError(f"Store universe rows contain {column} outside mart build metadata: {unexpected}")


def _resolve_source_revision_id(
    frame: pl.DataFrame,
    build_metadata: MartBuildMetadata,
    source_revision_id: str | None,
) -> str:
    revisions = tuple(str(item) for item in frame.get_column("source_revision_id").drop_nulls().unique().to_list()) if "source_revision_id" in frame.columns else ()
    if len(revisions) > 1:
        raise ValueError("Store universe requires one active source_revision_id per build input")
    if source_revision_id is not None and revisions and revisions[0] != source_revision_id:
        raise ValueError("Store universe source_revision_id does not match input rows")
    revision_id = source_revision_id or (revisions[0] if revisions else None)
    if revision_id is None:
        if len(build_metadata.source_revision_ids) != 1:
            raise ValueError("Store universe requires source_revision_id for multi-revision builds")
        revision_id = build_metadata.source_revision_ids[0]
    if revision_id not in build_metadata.source_revision_ids:
        raise ValueError("Store universe source_revision_id is outside mart build metadata")
    return revision_id


def _reject_ambiguous_store_format(frame: pl.DataFrame) -> None:
    ambiguous = (
        frame.group_by(["retailer_id", "source_id", "source_revision_id", "business_period_id", "canonical_store_id"])
        .agg(pl.col("store_format").drop_nulls().n_unique().alias("store_format_count"))
        .filter(pl.col("store_format_count") > 1)
    )
    if not ambiguous.is_empty():
        raise ValueError("Store universe has ambiguous store_format for a canonical store in one business period")


def _period_end(value: date, period_grain: str) -> date:
    if period_grain == "month":
        return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])
    return value
