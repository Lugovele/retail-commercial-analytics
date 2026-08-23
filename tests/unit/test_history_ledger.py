from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from retail_analytics.history import (
    PeriodGrain,
    SourceLedgerEntry,
    SourceRegistrationClassification,
    SourceRevisionState,
    activate_source_revision,
    active_revisions,
    register_source_revision,
    source_artifact_id,
    source_revision_id,
)


def test_new_artifact_registration() -> None:
    entry = _entry("hash_a", "v1")

    result = register_source_revision((), entry)

    assert result.classification == SourceRegistrationClassification.NEW_ARTIFACT
    assert result.entry.revision_state == SourceRevisionState.CANDIDATE
    assert len(result.ledger) == 1


def test_identical_duplicate_classification() -> None:
    first = register_source_revision((), _entry("hash_a", "v1"))
    duplicate = register_source_revision(first.ledger, _entry("hash_a", "duplicate_attempt"))

    assert duplicate.classification == SourceRegistrationClassification.IDENTICAL_DUPLICATE
    assert duplicate.entry.revision_state == SourceRevisionState.DUPLICATE
    assert duplicate.entry.is_active_revision is False
    assert duplicate.duplicate_of_revision_id == first.entry.source_revision_id


def test_corrected_reissued_revision_is_new_revision() -> None:
    first = register_source_revision((), _entry("hash_a", "v1"), activate=True)
    corrected = register_source_revision(first.ledger, _entry("hash_b", "v2"))

    assert corrected.classification == SourceRegistrationClassification.NEW_REVISION
    assert corrected.entry.source_hash == "hash_b"
    assert first.ledger[0].source_hash == "hash_a"


def test_active_revision_transition_supersedes_old_revision() -> None:
    first = register_source_revision((), _entry("hash_a", "v1"), activate=True)
    second = register_source_revision(first.ledger, _entry("hash_b", "v2"))

    ledger = activate_source_revision(second.ledger, second.entry.source_revision_id)

    assert len(active_revisions(ledger)) == 1
    old = next(entry for entry in ledger if entry.source_hash == "hash_a")
    new = next(entry for entry in ledger if entry.source_hash == "hash_b")
    assert old.revision_state == SourceRevisionState.SUPERSEDED
    assert old.superseded_by_revision_id == new.source_revision_id
    assert new.revision_state == SourceRevisionState.ACTIVE


def test_multiple_periods_per_artifact_are_preserved() -> None:
    entry = _entry("hash_a", "v1")

    assert entry.observed_periods == (date(2025, 1, 1), date(2025, 2, 1))
    assert entry.business_period_ids == ("2025-01", "2025-02")


def test_multiple_sources_under_one_retailer_do_not_collide() -> None:
    source_a = _entry("same_hash", "v1", source_id="source_a")
    source_b = _entry("same_hash", "v1", source_id="source_b")

    result_a = register_source_revision((), source_a)
    result_b = register_source_revision(result_a.ledger, source_b)

    assert result_b.classification == SourceRegistrationClassification.NEW_ARTIFACT
    assert source_a.source_artifact_id != source_b.source_artifact_id


def test_two_retailers_with_same_filename_do_not_collide() -> None:
    retailer_a = _entry("same_hash", "v1", retailer_id="retailer_a", source_file_id="source.xlsx")
    retailer_b = _entry("same_hash", "v1", retailer_id="retailer_b", source_file_id="source.xlsx")

    assert retailer_a.source_artifact_id != retailer_b.source_artifact_id
    assert retailer_a.source_revision_id != retailer_b.source_revision_id


def test_source_hash_participates_in_identity() -> None:
    first = _entry("hash_a", "v1")
    second = _entry("hash_b", "v1")

    assert first.source_artifact_id != second.source_artifact_id
    assert first.source_revision_id != second.source_revision_id


def test_filename_is_not_primary_identity() -> None:
    first = _entry("hash_a", "v1", source_file_id="same_name.xlsx")
    second = _entry("hash_b", "v1", source_file_id="same_name.xlsx")

    assert first.source_artifact_id != second.source_artifact_id


def _entry(
    source_hash: str,
    source_version: str,
    *,
    retailer_id: str = "retailer_a",
    source_id: str = "source_a",
    source_file_id: str = "source_a.xlsx",
) -> SourceLedgerEntry:
    artifact = source_artifact_id(retailer_id, source_id, source_hash)
    revision = source_revision_id(retailer_id, source_id, source_hash, source_version)
    return SourceLedgerEntry(
        source_revision_id=revision,
        source_artifact_id=artifact,
        retailer_id=retailer_id,
        source_id=source_id,
        source_type="monthly_workbook",
        source_version=source_version,
        source_file_id=source_file_id,
        source_hash=source_hash,
        raw_object_key=f"private/source/{source_file_id}",
        size_bytes=128,
        received_at=datetime(2026, 1, 10, tzinfo=UTC),
        registered_at=datetime(2026, 1, 11, tzinfo=UTC),
        period_grain=PeriodGrain.MONTH,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 2, 28),
        observed_periods=(date(2025, 1, 1), date(2025, 2, 1)),
        business_period_ids=("2025-01", "2025-02"),
        source_schema_version="schema_v1",
        mapping_config_hash="mapping_hash_a",
        rule_package_hash="rules_hash_a",
        row_count=10,
    )




def test_identical_duplicate_with_same_revision_id_does_not_corrupt_ledger() -> None:
    entry = _entry("hash_a", "v1")
    first = register_source_revision((), entry)
    duplicate = register_source_revision(first.ledger, entry)

    revision_ids = [row.source_revision_id for row in duplicate.ledger]
    assert duplicate.classification == SourceRegistrationClassification.IDENTICAL_DUPLICATE
    assert len(revision_ids) == len(set(revision_ids))


def test_partial_active_revision_preserves_unaffected_periods() -> None:
    first = register_source_revision((), _entry("hash_a", "v1"), activate=True)
    feb_revision = _entry("hash_b", "v2")
    feb_revision = replace(
        feb_revision,
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
        observed_periods=(date(2025, 2, 1),),
        business_period_ids=("2025-02",),
    )

    registered = register_source_revision(first.ledger, feb_revision)
    ledger = activate_source_revision(registered.ledger, feb_revision.source_revision_id)

    old = next(entry for entry in ledger if entry.source_hash == "hash_a")
    new = next(entry for entry in ledger if entry.source_hash == "hash_b")
    assert old.is_active_revision is True
    assert old.active_business_period_ids == ("2025-01",)
    assert new.is_active_revision is True
    assert new.active_business_period_ids == ("2025-02",)

