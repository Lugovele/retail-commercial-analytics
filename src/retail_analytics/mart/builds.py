"""Mart build identity and metadata persistence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl


class MartBuildStatus(StrEnum):
    """Minimal mart build lifecycle."""

    BUILT = "built"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    FAILED = "failed"


@dataclass(frozen=True)
class MartBuildMetadata:
    """Auditable mart build identity over approved analysis outputs."""

    mart_build_id: str
    built_at: datetime
    build_version: str
    code_version: str | None
    retailer_id: str
    source_ids: tuple[str, ...]
    source_revision_ids: tuple[str, ...]
    analysis_run_ids: tuple[str, ...]
    metric_config_hashes: tuple[str, ...]
    rule_versions: tuple[str, ...]
    status: str = MartBuildStatus.BUILT
    period_grain: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    input_row_count: int | None = None
    fact_row_count: int | None = None
    metadata_version: str = "mart_build.v1"

    def __post_init__(self) -> None:
        required = {
            "mart_build_id": self.mart_build_id,
            "build_version": self.build_version,
            "retailer_id": self.retailer_id,
            "metadata_version": self.metadata_version,
        }
        missing = [name for name, value in required.items() if value == ""]
        if missing:
            raise ValueError(f"Missing required mart build fields: {', '.join(missing)}")
        if self.status not in set(MartBuildStatus):
            raise ValueError(f"Unsupported mart build status: {self.status}")
        if not self.source_ids:
            raise ValueError("source_ids must not be empty")
        if not self.source_revision_ids:
            raise ValueError("source_revision_ids must not be empty")
        if not self.analysis_run_ids:
            raise ValueError("analysis_run_ids must not be empty")
        if self.period_start is not None and self.period_end is not None and self.period_start > self.period_end:
            raise ValueError("period_start must be on or before period_end")
        if self.input_row_count is not None and self.input_row_count < 0:
            raise ValueError("input_row_count must be non-negative when provided")
        if self.fact_row_count is not None and self.fact_row_count < 0:
            raise ValueError("fact_row_count must be non-negative when provided")


def mart_build_id(
    *,
    retailer_id: str,
    source_revision_ids: tuple[str, ...],
    analysis_run_ids: tuple[str, ...],
    metric_config_hashes: tuple[str, ...],
    rule_versions: tuple[str, ...],
    build_version: str,
) -> str:
    """Create deterministic build identity from semantic inputs, not timestamps."""

    return "mart_build_" + _digest(
        {
            "retailer_id": retailer_id,
            "source_revision_ids": sorted(source_revision_ids),
            "analysis_run_ids": sorted(analysis_run_ids),
            "metric_config_hashes": sorted(metric_config_hashes),
            "rule_versions": sorted(rule_versions),
            "build_version": build_version,
        }
    )


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def mart_build_metadata_to_frame(metadata: MartBuildMetadata | tuple[MartBuildMetadata, ...]) -> pl.DataFrame:
    """Convert mart build metadata to a deterministic frame."""

    rows = metadata if isinstance(metadata, tuple) else (metadata,)
    return pl.DataFrame([_metadata_to_row(row) for row in rows], schema=MART_BUILD_SCHEMA)


def mart_build_metadata_from_frame(frame: pl.DataFrame) -> tuple[MartBuildMetadata, ...]:
    """Restore mart build metadata from a persisted frame."""

    return tuple(_metadata_from_row(row) for row in frame.to_dicts())


def write_mart_build_metadata(metadata: MartBuildMetadata | tuple[MartBuildMetadata, ...], path: str | Path) -> Path:
    """Persist mart build metadata as Parquet."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mart_build_metadata_to_frame(metadata).write_parquet(target)
    return target


def write_mart_build_metadata_dataset(
    metadata: MartBuildMetadata | tuple[MartBuildMetadata, ...],
    storage_root: str | Path,
) -> tuple[Path, ...]:
    """Persist build metadata under the approved mart_run_metadata partition layout."""

    frame = mart_build_metadata_to_frame(metadata)
    if frame.is_empty():
        return ()
    root = Path(storage_root) / "mart_run_metadata"
    written: list[Path] = []
    for values in frame.select(["retailer_id", "mart_build_id"]).unique().iter_rows(named=True):
        partition = frame
        for column, value in values.items():
            partition = partition.filter(pl.col(column) == value)
        path = root / f"retailer_id={values['retailer_id']}" / f"mart_build_id={values['mart_build_id']}"
        path.mkdir(parents=True, exist_ok=True)
        output = path / "build.parquet"
        partition.write_parquet(output)
        written.append(output)
    return tuple(written)


def read_mart_build_metadata(path: str | Path) -> tuple[MartBuildMetadata, ...]:
    """Read mart build metadata from Parquet."""

    return mart_build_metadata_from_frame(pl.read_parquet(path))


MART_BUILD_SCHEMA = {
    "mart_build_id": pl.Utf8,
    "built_at": pl.Datetime,
    "build_version": pl.Utf8,
    "code_version": pl.Utf8,
    "retailer_id": pl.Utf8,
    "source_ids": pl.Utf8,
    "source_revision_ids": pl.Utf8,
    "analysis_run_ids": pl.Utf8,
    "metric_config_hashes": pl.Utf8,
    "rule_versions": pl.Utf8,
    "status": pl.Utf8,
    "period_grain": pl.Utf8,
    "period_start": pl.Date,
    "period_end": pl.Date,
    "input_row_count": pl.Int64,
    "fact_row_count": pl.Int64,
    "metadata_version": pl.Utf8,
}


def _metadata_to_row(metadata: MartBuildMetadata) -> dict[str, Any]:
    row = dict(metadata.__dict__)
    if row["built_at"].tzinfo is not None:
        row["built_at"] = row["built_at"].replace(tzinfo=None)
    for field in ("source_ids", "source_revision_ids", "analysis_run_ids", "metric_config_hashes", "rule_versions"):
        row[field] = json.dumps(list(row[field]), sort_keys=True)
    return row


def _metadata_from_row(row: dict[str, Any]) -> MartBuildMetadata:
    parsed = dict(row)
    if parsed["built_at"].tzinfo is None:
        parsed["built_at"] = parsed["built_at"].replace(tzinfo=UTC)
    for field in ("source_ids", "source_revision_ids", "analysis_run_ids", "metric_config_hashes", "rule_versions"):
        parsed[field] = tuple(json.loads(parsed[field]))
    return MartBuildMetadata(**parsed)


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]





