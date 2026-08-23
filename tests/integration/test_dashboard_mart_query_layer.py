from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from retail_analytics.history import PeriodGrain, SourceLedgerEntry, source_artifact_id
from retail_analytics.mart import (
    ComparisonMode,
    DashboardMartQueryService,
    DashboardMetricQueryRequest,
    MartBuildMetadata,
    MartBuildStatus,
    PeriodMode,
    build_mart_metric_facts,
    load_public_metric_catalog,
    write_mart_metric_fact_dataset,
)


def test_dashboard_query_layer_reads_partitioned_mart_facts(tmp_path) -> None:
    metadata = _build()
    facts = build_mart_metric_facts(_metrics(), build_metadata=metadata, source_revision_id="revision_a")
    storage_root = tmp_path.parent / "dq"
    write_mart_metric_fact_dataset(facts, storage_root)
    public_catalog = load_public_metric_catalog("config/public/dashboard_metric_catalog.yaml")

    service = DashboardMartQueryService(
        storage_root / "mart_metric_facts",
        catalog=(),
        mart_builds=(metadata,),
        source_ledger=(_ledger(),),
    )
    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 2, 1),
            period_mode=PeriodMode.DATE_RANGE,
            period_grain="month",
            grain_id="sku",
            entity_ids=("SKU_A_001",),
            metric_concepts=("revenue", "retailer_margin_pct"),
            comparison_mode=ComparisonMode.NONE,
        )
    )

    assert len(public_catalog) > 0
    assert response.mart_build_id == "build_a"
    assert response.available_periods == (date(2025, 1, 1), date(2025, 2, 1))
    assert {result.metric_concept for result in response.metric_results} == {
        "revenue",
        "retailer_margin_pct",
    }
    assert response.metric_results[0].lineage is not None
    assert Path(storage_root / "mart_metric_facts").exists()


def _build() -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id="build_a",
        built_at=datetime(2026, 1, 15, tzinfo=UTC),
        build_version="mart.v1",
        code_version="test",
        retailer_id="retailer_a",
        source_ids=("source_a",),
        source_revision_ids=("revision_a",),
        analysis_run_ids=("analysis_a",),
        metric_config_hashes=("metric_hash_a",),
        rule_versions=("rules_v1",),
        status=MartBuildStatus.APPROVED,
        period_grain="month",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 2, 28),
    )


def _metrics() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["analysis_a", "analysis_a", "analysis_a", "analysis_a"],
            "retailer_id": ["retailer_a"] * 4,
            "source_id": ["source_a"] * 4,
            "period": ["2025-01", "2025-01", "2025-02", "2025-02"],
            "grain_id": ["sku"] * 4,
            "entity_id": ["SKU_A_001"] * 4,
            "concept": ["revenue", "retailer_margin_pct", "revenue", "retailer_margin_pct"],
            "name": ["revenue", "retailer_margin_pct", "revenue", "retailer_margin_pct"],
            "metric_definition_id": [
                "retailer_a.sku.revenue.v1",
                "retailer_a.sku.margin_pct.v1",
                "retailer_a.sku.revenue.v1",
                "retailer_a.sku.margin_pct.v1",
            ],
            "metric_definition_version": ["v1"] * 4,
            "metric_config_hash": ["metric_hash_a"] * 4,
            "metric_value": [100.0, 0.2, 200.0, 0.3],
            "numerator_value": [None, 20.0, None, 60.0],
            "denominator_value": [None, 100.0, None, 200.0],
            "aggregation": ["sum", "ratio_of_sums", "sum", "ratio_of_sums"],
            "rule_version": ["rules_v1"] * 4,
        }
    )


def _ledger() -> SourceLedgerEntry:
    return SourceLedgerEntry(
        source_revision_id="revision_a",
        source_artifact_id=source_artifact_id("retailer_a", "source_a", "hash_a"),
        retailer_id="retailer_a",
        source_id="source_a",
        source_type="monthly_workbook",
        source_version="v1",
        source_file_id="source.xlsx",
        source_hash="hash_a",
        raw_object_key="private/source/source.xlsx",
        size_bytes=100,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        registered_at=datetime(2026, 1, 2, tzinfo=UTC),
        period_grain=PeriodGrain.MONTH,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 2, 28),
        observed_periods=(date(2025, 1, 1), date(2025, 2, 1)),
        business_period_ids=("2025-01-01", "2025-02-01"),
        active_business_period_ids=("2025-01-01", "2025-02-01"),
        source_schema_version="schema_v1",
        mapping_config_hash="mapping_hash",
        rule_package_hash="rule_hash",
        revision_state="active",
        is_active_revision=True,
    )
