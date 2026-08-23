from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl

from retail_analytics.history import (
    PeriodGrain,
    SourceLedgerEntry,
    ledger_entries_to_frame,
    read_source_ledger,
    source_artifact_id,
    write_source_ledger,
    write_source_ledger_dataset,
)
from retail_analytics.mart import (
    MartBuildMetadata,
    build_mart_metric_facts,
    query_metric_facts,
    read_mart_build_metadata,
    read_mart_metric_facts,
    write_mart_build_metadata,
    write_mart_build_metadata_dataset,
    write_mart_metric_fact_dataset,
    write_mart_metric_facts,
)


def test_ledger_parquet_roundtrip_preserves_types(tmp_path) -> None:
    entry = _ledger_entry("retailer_a", "source_a", "hash_a", "revision_a")
    path = tmp_path / "mart_source_ledger" / "ledger.parquet"

    write_source_ledger((entry,), path)
    restored = read_source_ledger(path)

    assert restored == (entry,)
    frame = ledger_entries_to_frame(restored)
    assert frame.schema["period_start"] == pl.Date
    assert frame.schema["is_active_revision"] == pl.Boolean


def test_mart_build_metadata_roundtrip(tmp_path) -> None:
    metadata = _build("build_a", "retailer_a", "source_a", "revision_a")
    path = tmp_path / "mart_run_metadata" / "build.parquet"

    write_mart_build_metadata(metadata, path)
    restored = read_mart_build_metadata(path)

    assert restored == (metadata,)


def test_metric_fact_parquet_roundtrip_preserves_null_components(tmp_path) -> None:
    facts = build_mart_metric_facts(
        _metrics("retailer_a", "source_a", "analysis_a", "SKU_A_001"),
        build_metadata=_build("build_a", "retailer_a", "source_a", "revision_a"),
        source_revision_id="revision_a",
    )
    path = tmp_path / "mart_metric_facts" / "facts.parquet"

    write_mart_metric_facts(facts, path)
    restored = read_mart_metric_facts(path)

    assert restored.schema == facts.schema
    assert restored["numerator_value"].null_count() == 2
    assert restored["value"].to_list() == facts["value"].to_list()


def test_duckdb_filters_do_not_mix_scope_data(tmp_path) -> None:
    first = build_mart_metric_facts(
        _metrics("retailer_a", "source_a", "analysis_a", "SKU_A_001"),
        build_metadata=_build("build_a", "retailer_a", "source_a", "revision_a"),
        source_revision_id="revision_a",
    )
    second = build_mart_metric_facts(
        _metrics("retailer_b", "source_b", "analysis_b", "SKU_B_001"),
        build_metadata=_build("build_b", "retailer_b", "source_b", "revision_b"),
        source_revision_id="revision_b",
    )
    path = tmp_path / "mart_metric_facts" / "facts.parquet"
    write_mart_metric_facts(pl.concat([first, second]), path)

    result = query_metric_facts(
        path,
        retailer_id="retailer_a",
        source_id="source_a",
        period_start="2025-01-01",
        period_end="2025-01-31",
        grain_id="sku",
        metric_concept="revenue",
        metric_definition_id="retailer_a.revenue.v1",
        mart_build_id="build_a",
    )

    assert result.height == 1
    assert result["retailer_id"].to_list() == ["retailer_a"]
    assert result["source_id"].to_list() == ["source_a"]
    assert result["entity_id"].to_list() == ["SKU_A_001"]
    assert result["metric_concept"].to_list() == ["revenue"]


def _ledger_entry(retailer_id: str, source_id: str, source_hash: str, revision: str) -> SourceLedgerEntry:
    return SourceLedgerEntry(
        source_revision_id=revision,
        source_artifact_id=source_artifact_id(retailer_id, source_id, source_hash),
        retailer_id=retailer_id,
        source_id=source_id,
        source_type="monthly_workbook",
        source_version="v1",
        source_file_id="source.xlsx",
        source_hash=source_hash,
        raw_object_key="private/source/source.xlsx",
        size_bytes=100,
        received_at=datetime(2026, 1, 10, tzinfo=UTC),
        registered_at=datetime(2026, 1, 11, tzinfo=UTC),
        period_grain=PeriodGrain.MONTH,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        observed_periods=(date(2025, 1, 1),),
        business_period_ids=("2025-01",),
        source_schema_version="schema_v1",
        mapping_config_hash="mapping_hash_a",
        rule_package_hash="rules_hash_a",
        row_count=10,
    )


def _build(build_id: str, retailer_id: str, source_id: str, revision: str) -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id=build_id,
        built_at=datetime(2026, 1, 15, tzinfo=UTC),
        build_version="mart.v1",
        code_version="test_code_version",
        retailer_id=retailer_id,
        source_ids=(source_id,),
        source_revision_ids=(revision,),
        analysis_run_ids=(f"analysis_{retailer_id[-1]}",),
        metric_config_hashes=(f"metric_hash_{retailer_id[-1]}",),
        rule_versions=("rules_v1",),
        period_grain="month",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
    )


def _metrics(retailer_id: str, source_id: str, analysis_run_id: str, entity_id: str) -> pl.DataFrame:
    suffix = retailer_id[-1]
    return pl.DataFrame(
        {
            "analysis_run_id": [analysis_run_id, analysis_run_id],
            "retailer_id": [retailer_id, retailer_id],
            "source_id": [source_id, source_id],
            "period": ["2025-01", "2025-02"],
            "grain_id": ["sku", "brand"],
            "entity_id": [entity_id, f"BRAND_{suffix.upper()}"],
            "concept": ["revenue", "units"],
            "name": ["revenue", "units"],
            "metric_definition_id": [f"{retailer_id}.revenue.v1", f"{retailer_id}.units.v1"],
            "metric_definition_version": ["v1", "v1"],
            "metric_config_hash": [f"metric_hash_{suffix}", f"metric_hash_{suffix}"],
            "metric_value": [100.0, 10.0],
            "numerator_value": [None, None],
            "denominator_value": [None, None],
            "aggregation": ["sum", "sum"],
            "rule_version": ["rules_v1", "rules_v1"],
        }
    )





def test_partition_dataset_writers_use_approved_layout(tmp_path) -> None:
    entry = _ledger_entry("retailer_a", "source_a", "hash_a", "revision_a")
    metadata = _build("build_a", "retailer_a", "source_a", "revision_a")
    facts = build_mart_metric_facts(
        _metrics("retailer_a", "source_a", "analysis_a", "SKU_A_001"),
        build_metadata=metadata,
        source_revision_id="revision_a",
    )

    ledger_paths = write_source_ledger_dataset((entry,), tmp_path)
    build_paths = write_mart_build_metadata_dataset(metadata, tmp_path)
    fact_paths = write_mart_metric_fact_dataset(facts, tmp_path)

    assert ledger_paths[0].as_posix().endswith(
        "mart_source_ledger/retailer_id=retailer_a/source_id=source_a/period_grain=month/ledger.parquet"
    )
    assert build_paths[0].as_posix().endswith(
        "mart_run_metadata/retailer_id=retailer_a/mart_build_id=build_a/build.parquet"
    )
    assert any("mart_metric_facts/retailer_id=retailer_a/source_id=source_a/period_grain=month" in path.as_posix() for path in fact_paths)


