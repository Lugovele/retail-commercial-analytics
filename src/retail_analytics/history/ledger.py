"""Append-oriented source ledger and revision state contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl


class PeriodGrain(StrEnum):
    """Supported source period grains."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class SourceProcessingStatus(StrEnum):
    """Processing lifecycle status for a source revision."""

    REGISTERED = "registered"
    VALIDATED = "validated"
    INGESTED = "ingested"
    ANALYZED = "analyzed"
    FAILED = "failed"


class SourceRevisionState(StrEnum):
    """Ledger revision state."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class SourceRegistrationClassification(StrEnum):
    """Registration outcome for a source artifact attempt."""

    NEW_ARTIFACT = "NEW_ARTIFACT"
    NEW_REVISION = "NEW_REVISION"
    IDENTICAL_DUPLICATE = "IDENTICAL_DUPLICATE"


@dataclass(frozen=True)
class SourceLedgerEntry:
    """Immutable source artifact revision metadata.

    Active-state fields are represented as new ledger snapshots by helper
    functions; source hash and revision identity remain immutable.
    """

    source_revision_id: str
    source_artifact_id: str
    retailer_id: str
    source_id: str
    source_type: str
    source_version: str
    source_file_id: str
    source_hash: str
    raw_object_key: str
    size_bytes: int
    received_at: datetime
    registered_at: datetime
    period_grain: str
    period_start: date
    period_end: date
    observed_periods: tuple[date, ...]
    business_period_ids: tuple[str, ...]
    source_schema_version: str
    mapping_config_hash: str
    rule_package_hash: str
    active_business_period_ids: tuple[str, ...] = ()
    row_count: int | None = None
    processing_status: str = SourceProcessingStatus.REGISTERED
    revision_state: str = SourceRevisionState.CANDIDATE
    supersedes_revision_id: str | None = None
    superseded_by_revision_id: str | None = None
    is_active_revision: bool = False
    status_reason: str | None = None
    processing_started_at: datetime | None = None
    processing_finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata_version: str = "source_ledger.v1"

    def __post_init__(self) -> None:
        required = {
            "source_revision_id": self.source_revision_id,
            "source_artifact_id": self.source_artifact_id,
            "retailer_id": self.retailer_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_version": self.source_version,
            "source_file_id": self.source_file_id,
            "source_hash": self.source_hash,
            "raw_object_key": self.raw_object_key,
            "period_grain": self.period_grain,
            "source_schema_version": self.source_schema_version,
            "mapping_config_hash": self.mapping_config_hash,
            "rule_package_hash": self.rule_package_hash,
            "metadata_version": self.metadata_version,
        }
        missing = [name for name, value in required.items() if value == ""]
        if missing:
            raise ValueError(f"Missing required source ledger fields: {', '.join(missing)}")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if self.row_count is not None and self.row_count < 0:
            raise ValueError("row_count must be non-negative when provided")
        if self.period_start > self.period_end:
            raise ValueError("period_start must be on or before period_end")
        if self.period_grain not in set(PeriodGrain):
            raise ValueError(f"Unsupported period_grain: {self.period_grain}")
        if self.processing_status not in set(SourceProcessingStatus):
            raise ValueError(f"Unsupported processing_status: {self.processing_status}")
        if self.revision_state not in set(SourceRevisionState):
            raise ValueError(f"Unsupported revision_state: {self.revision_state}")


@dataclass(frozen=True)
class SourceRegistrationResult:
    """Structured source registration outcome."""

    classification: SourceRegistrationClassification
    entry: SourceLedgerEntry
    ledger: tuple[SourceLedgerEntry, ...]
    duplicate_of_revision_id: str | None = None


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def file_sha256(path: str | Path) -> str:
    """Hash source bytes without using file names as identity."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_artifact_id(retailer_id: str, source_id: str, source_hash: str) -> str:
    """Deterministic duplicate identity for the same bytes and source scope."""

    return "source_artifact_" + _digest(
        {
            "retailer_id": retailer_id,
            "source_id": source_id,
            "source_hash": source_hash,
        }
    )


def source_revision_id(
    retailer_id: str,
    source_id: str,
    source_hash: str,
    source_version: str,
) -> str:
    """Deterministic source revision identity."""

    return "source_revision_" + _digest(
        {
            "retailer_id": retailer_id,
            "source_id": source_id,
            "source_hash": source_hash,
            "source_version": source_version,
        }
    )


def register_source_revision(
    ledger: tuple[SourceLedgerEntry, ...],
    entry: SourceLedgerEntry,
    *,
    activate: bool = False,
) -> SourceRegistrationResult:
    """Append a source revision registration and classify duplicate/reissue semantics."""

    duplicate = _find_identical_duplicate(ledger, entry)
    if duplicate is not None:
        duplicate_revision_id = _duplicate_revision_id(ledger, entry, duplicate)
        duplicate_entry = replace(
            entry,
            source_revision_id=duplicate_revision_id,
            revision_state=SourceRevisionState.DUPLICATE,
            is_active_revision=False,
            supersedes_revision_id=duplicate.source_revision_id,
            status_reason="identical_duplicate",
        )
        updated = (*ledger, duplicate_entry)
        return SourceRegistrationResult(
            classification=SourceRegistrationClassification.IDENTICAL_DUPLICATE,
            entry=duplicate_entry,
            ledger=updated,
            duplicate_of_revision_id=duplicate.source_revision_id,
        )

    classification = (
        SourceRegistrationClassification.NEW_REVISION
        if any(_same_source_scope(existing, entry) for existing in ledger)
        else SourceRegistrationClassification.NEW_ARTIFACT
    )
    candidate = replace(entry, revision_state=SourceRevisionState.CANDIDATE, is_active_revision=False)
    updated = (*ledger, candidate)
    if activate:
        updated = activate_source_revision(updated, candidate.source_revision_id)
        candidate = _find_by_revision_id(updated, candidate.source_revision_id)
    return SourceRegistrationResult(classification=classification, entry=candidate, ledger=updated)


def activate_source_revision(
    ledger: tuple[SourceLedgerEntry, ...],
    revision_id: str,
) -> tuple[SourceLedgerEntry, ...]:
    """Activate one revision per covered business period in the same source scope."""

    target = _find_by_revision_id(ledger, revision_id)
    if target.revision_state == SourceRevisionState.DUPLICATE:
        raise ValueError("Identical duplicate revisions cannot be activated")

    target_periods = set(_effective_active_period_ids(target))
    updated: list[SourceLedgerEntry] = []
    for entry in ledger:
        if entry.source_revision_id == revision_id:
            updated.append(
                replace(
                    entry,
                    revision_state=SourceRevisionState.ACTIVE,
                    is_active_revision=True,
                    active_business_period_ids=tuple(entry.business_period_ids),
                    superseded_by_revision_id=None,
                    status_reason="activated",
                )
            )
        elif entry.is_active_revision and _same_source_scope(entry, target):
            remaining_periods = tuple(
                period for period in _effective_active_period_ids(entry) if period not in target_periods
            )
            if remaining_periods:
                updated.append(
                    replace(
                        entry,
                        revision_state=SourceRevisionState.ACTIVE,
                        is_active_revision=True,
                        active_business_period_ids=remaining_periods,
                        status_reason="partially_superseded_by_new_active_revision",
                    )
                )
            else:
                updated.append(
                    replace(
                        entry,
                        revision_state=SourceRevisionState.SUPERSEDED,
                        is_active_revision=False,
                        active_business_period_ids=(),
                        superseded_by_revision_id=revision_id,
                        status_reason="superseded_by_new_active_revision",
                    )
                )
        else:
            updated.append(entry)
    return tuple(updated)


def active_revisions(ledger: tuple[SourceLedgerEntry, ...]) -> tuple[SourceLedgerEntry, ...]:
    """Return currently active revisions."""

    return tuple(entry for entry in ledger if entry.is_active_revision)


def ledger_entries_to_frame(entries: tuple[SourceLedgerEntry, ...]) -> pl.DataFrame:
    """Convert ledger entries into a deterministic Polars frame."""

    return pl.DataFrame([_entry_to_row(entry) for entry in entries], schema=SOURCE_LEDGER_SCHEMA)


def ledger_entries_from_frame(frame: pl.DataFrame) -> tuple[SourceLedgerEntry, ...]:
    """Restore ledger entries from a persisted frame."""

    return tuple(_entry_from_row(row) for row in frame.to_dicts())


def write_source_ledger(entries: tuple[SourceLedgerEntry, ...], path: str | Path) -> None:
    """Persist source ledger entries as Parquet."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ledger_entries_to_frame(entries).write_parquet(target)


def write_source_ledger_dataset(entries: tuple[SourceLedgerEntry, ...], storage_root: str | Path) -> tuple[Path, ...]:
    """Persist ledger entries under the approved mart_source_ledger partition layout."""

    frame = ledger_entries_to_frame(entries)
    if frame.is_empty():
        return ()
    root = Path(storage_root) / "mart_source_ledger"
    written: list[Path] = []
    for values in frame.select(["retailer_id", "source_id", "period_grain"]).unique().iter_rows(named=True):
        partition = frame
        for column, value in values.items():
            partition = partition.filter(pl.col(column) == value)
        path = root
        for column in ("retailer_id", "source_id", "period_grain"):
            path = path / f"{column}={values[column]}"
        path.mkdir(parents=True, exist_ok=True)
        output = path / "ledger.parquet"
        partition.write_parquet(output)
        written.append(output)
    return tuple(written)


def read_source_ledger(path: str | Path) -> tuple[SourceLedgerEntry, ...]:
    """Read source ledger entries from Parquet."""

    return ledger_entries_from_frame(pl.read_parquet(path))


SOURCE_LEDGER_SCHEMA = {
    "source_revision_id": pl.Utf8,
    "source_artifact_id": pl.Utf8,
    "retailer_id": pl.Utf8,
    "source_id": pl.Utf8,
    "source_type": pl.Utf8,
    "source_version": pl.Utf8,
    "source_file_id": pl.Utf8,
    "source_hash": pl.Utf8,
    "raw_object_key": pl.Utf8,
    "size_bytes": pl.Int64,
    "received_at": pl.Datetime,
    "registered_at": pl.Datetime,
    "period_grain": pl.Utf8,
    "period_start": pl.Date,
    "period_end": pl.Date,
    "observed_periods": pl.Utf8,
    "business_period_ids": pl.Utf8,
    "active_business_period_ids": pl.Utf8,
    "source_schema_version": pl.Utf8,
    "mapping_config_hash": pl.Utf8,
    "rule_package_hash": pl.Utf8,
    "row_count": pl.Int64,
    "processing_status": pl.Utf8,
    "revision_state": pl.Utf8,
    "supersedes_revision_id": pl.Utf8,
    "superseded_by_revision_id": pl.Utf8,
    "is_active_revision": pl.Boolean,
    "status_reason": pl.Utf8,
    "processing_started_at": pl.Datetime,
    "processing_finished_at": pl.Datetime,
    "error_code": pl.Utf8,
    "error_message": pl.Utf8,
    "metadata_version": pl.Utf8,
}


def _duplicate_revision_id(
    ledger: tuple[SourceLedgerEntry, ...],
    entry: SourceLedgerEntry,
    duplicate: SourceLedgerEntry,
) -> str:
    if not any(existing.source_revision_id == entry.source_revision_id for existing in ledger):
        return entry.source_revision_id
    return entry.source_revision_id + "_duplicate_" + _digest(
        {
            "duplicate_of": duplicate.source_revision_id,
            "registered_at": entry.registered_at.isoformat(),
            "ledger_size": len(ledger),
            "raw_object_key": entry.raw_object_key,
        }
    )


def _find_identical_duplicate(
    ledger: tuple[SourceLedgerEntry, ...],
    entry: SourceLedgerEntry,
) -> SourceLedgerEntry | None:
    for existing in ledger:
        if (
            existing.retailer_id == entry.retailer_id
            and existing.source_id == entry.source_id
            and existing.source_hash == entry.source_hash
            and existing.revision_state != SourceRevisionState.DUPLICATE
        ):
            return existing
    return None


def _find_by_revision_id(
    ledger: tuple[SourceLedgerEntry, ...],
    revision_id: str,
) -> SourceLedgerEntry:
    matches = [entry for entry in ledger if entry.source_revision_id == revision_id]
    if not matches:
        raise KeyError(f"Unknown source_revision_id: {revision_id}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate source_revision_id in ledger: {revision_id}")
    return matches[0]


def _same_source_scope(left: SourceLedgerEntry, right: SourceLedgerEntry) -> bool:
    return left.retailer_id == right.retailer_id and left.source_id == right.source_id


def _effective_active_period_ids(entry: SourceLedgerEntry) -> tuple[str, ...]:
    return entry.active_business_period_ids or entry.business_period_ids


def _periods_overlap(left: SourceLedgerEntry, right: SourceLedgerEntry) -> bool:
    return left.period_start <= right.period_end and right.period_start <= left.period_end


def _entry_to_row(entry: SourceLedgerEntry) -> dict[str, Any]:
    row = dict(entry.__dict__)
    for field in ("received_at", "registered_at", "processing_started_at", "processing_finished_at"):
        if row[field] is not None and row[field].tzinfo is not None:
            row[field] = row[field].replace(tzinfo=None)
    row["observed_periods"] = json.dumps([period.isoformat() for period in entry.observed_periods])
    row["business_period_ids"] = json.dumps(list(entry.business_period_ids))
    row["active_business_period_ids"] = json.dumps(list(entry.active_business_period_ids))
    return row


def _entry_from_row(row: dict[str, Any]) -> SourceLedgerEntry:
    parsed = dict(row)
    for field in ("received_at", "registered_at", "processing_started_at", "processing_finished_at"):
        if parsed[field] is not None and parsed[field].tzinfo is None:
            parsed[field] = parsed[field].replace(tzinfo=UTC)
    return SourceLedgerEntry(
        **{
            **parsed,
            "observed_periods": tuple(date.fromisoformat(value) for value in json.loads(row["observed_periods"])),
            "business_period_ids": tuple(json.loads(row["business_period_ids"])),
            "active_business_period_ids": tuple(json.loads(row["active_business_period_ids"])),
        }
    )



def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]





