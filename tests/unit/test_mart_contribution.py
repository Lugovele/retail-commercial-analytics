from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from retail_analytics.mart import (
    AdditiveContributionService,
    ContributionQueryRequest,
    ContributionStatus,
    MartBuildMetadata,
    MartBuildStatus,
    PrivateLabelScope,
    write_mart_metric_facts,
)
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA


def test_contribution_preserves_signed_offsetting_shares(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(_request())

    assert response.status == ContributionStatus.READY
    assert response.parent_delta == pytest.approx(-10.0)
    assert [row.child_entity_id for row in response.rows] == ["CAT_A", "CAT_B"]
    assert response.rows[0].delta == pytest.approx(-15.0)
    assert response.rows[0].contribution_share == pytest.approx(1.5)
    assert response.rows[1].delta == pytest.approx(5.0)
    assert response.rows[1].contribution_share == pytest.approx(-0.5)
    assert response.quality_flags == ()
    assert response.rows[0].provenance["calculation"]["formula"] == "child_delta / parent_delta"
    assert response.rows[0].provenance["metric"]["parent_definition"]["metric_definition_id"] == "retailer_a.network.revenue.v1"
    assert response.rows[0].provenance["metric"]["child_definition"]["metric_definition_id"] == "retailer_a.category.revenue.v1"
    assert response.rows[0].provenance["run_lineage"]["mart_build_id"] == "build_a"
    assert response.rows[0].provenance["run_lineage"]["analysis_run_ids"] == ("analysis_a",)
    assert response.rows[0].provenance["source_evidence"]["status"] == "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS"


def test_contribution_total_delta_zero_returns_undefined_share(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = _facts(parent_current=100.0, child_current=(40.0, 60.0))
    write_mart_metric_facts(facts, path)
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(_request())

    assert response.status == ContributionStatus.TOTAL_DELTA_ZERO
    assert response.parent_delta == 0.0
    assert {row.contribution_share for row in response.rows} == {None}


def test_contribution_one_child_new_and_disappeared_children_reconcile(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(
        _facts(parent_current=25.0, parent_reference=50.0, child_current=(25.0, 0.0), child_reference=(0.0, 50.0)),
        path,
    )
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(_request())

    assert response.parent_delta == pytest.approx(-25.0)
    assert {row.child_entity_id: row.delta for row in response.rows} == {"CAT_A": 25.0, "CAT_B": -50.0}
    assert sum(row.delta for row in response.rows) == pytest.approx(response.parent_delta)
    assert sum(row.contribution_share or 0 for row in response.rows) == pytest.approx(1.0)


def test_contribution_handles_one_child_and_negative_metric_values(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(
        _facts(parent_current=-20.0, parent_reference=-10.0, child_current=(-20.0, 0.0), child_reference=(-10.0, 0.0)),
        path,
    )
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(_request())

    assert response.rows[0].child_entity_id == "CAT_A"
    assert response.rows[0].delta == pytest.approx(-10.0)
    assert response.rows[0].contribution_share == pytest.approx(1.0)


def test_contribution_rejects_non_additive_metrics_structurally(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(_request(metric_concept="retailer_margin_pct"))

    assert response.status == ContributionStatus.NOT_APPLICABLE
    assert response.rows == ()
    assert "contribution_supported_for_additive_metrics_only" in response.limitations


def test_contribution_rejects_unsupported_parent_child_scope(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(_facts(), path)
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(
        _request(parent_grain_id="manufacturer", parent_entity_id="MANUFACTURER_A", child_grain_id="brand")
    )

    assert response.status == ContributionStatus.NOT_APPLICABLE_PARENT_CHILD_SCOPE
    assert response.rows == ()


def test_contribution_respects_private_label_scope(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    write_mart_metric_facts(
        pl.concat(
            [
                _facts(scope=PrivateLabelScope.INCLUDE),
                _facts(scope=PrivateLabelScope.EXCLUDE, parent_current=70.0, parent_reference=60.0, child_current=(70.0, 0.0), child_reference=(60.0, 0.0)),
            ],
            how="vertical",
        ),
        path,
    )
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(_request(private_label_scope=PrivateLabelScope.EXCLUDE))

    assert response.parent_delta == pytest.approx(10.0)
    assert response.rows[0].child_entity_id == "CAT_A"
    assert response.rows[0].contribution_share == pytest.approx(1.0)


def test_contribution_category_to_manufacturer_uses_parent_json_scope(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    rows = [
        _fact(date(2025, 6, 1), "category", "CAT_A", 100.0, "retailer_a.category.revenue.v1", {"category": "CAT_A"}),
        _fact(date(2026, 6, 1), "category", "CAT_A", 120.0, "retailer_a.category.revenue.v1", {"category": "CAT_A"}),
        _fact(date(2025, 6, 1), "manufacturer", "MANUFACTURER_A", 80.0, "retailer_a.manufacturer.revenue.v1", {"category": "CAT_A", "manufacturer": "MANUFACTURER_A"}),
        _fact(date(2026, 6, 1), "manufacturer", "MANUFACTURER_A", 110.0, "retailer_a.manufacturer.revenue.v1", {"category": "CAT_A", "manufacturer": "MANUFACTURER_A"}),
        _fact(date(2025, 6, 1), "manufacturer", "MANUFACTURER_B", 20.0, "retailer_a.manufacturer.revenue.v1", {"category": "CAT_A", "manufacturer": "MANUFACTURER_B"}),
        _fact(date(2026, 6, 1), "manufacturer", "MANUFACTURER_B", 10.0, "retailer_a.manufacturer.revenue.v1", {"category": "CAT_A", "manufacturer": "MANUFACTURER_B"}),
        _fact(date(2025, 6, 1), "manufacturer", "OTHER", 999.0, "retailer_a.manufacturer.revenue.v1", {"category": "CAT_B", "manufacturer": "OTHER"}),
        _fact(date(2026, 6, 1), "manufacturer", "OTHER", 999.0, "retailer_a.manufacturer.revenue.v1", {"category": "CAT_B", "manufacturer": "OTHER"}),
    ]
    write_mart_metric_facts(pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA), path)
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(
        _request(parent_grain_id="category", parent_entity_id="CAT_A", child_grain_id="manufacturer")
    )

    assert [row.child_entity_id for row in response.rows] == ["MANUFACTURER_A", "MANUFACTURER_B"]
    assert response.parent_delta == pytest.approx(20.0)
    assert response.rows[0].contribution_share == pytest.approx(1.5)


def test_contribution_ambiguous_child_definition_is_structured_status(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    extra = _fact(
        period=date(2026, 6, 1),
        grain="category",
        entity="CAT_A",
        value=1.0,
        definition_id="retailer_a.category.revenue.v2",
        parent={"category": "CAT_A"},
    )
    write_mart_metric_facts(pl.concat([_facts(), pl.DataFrame([extra], schema=MART_METRIC_FACT_SCHEMA)], how="vertical"), path)
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(_request())

    assert response.status == ContributionStatus.AMBIGUOUS_METRIC_DEFINITION
    assert "ambiguous_metric_definition" in response.limitations


def test_contribution_missing_parent_reference_is_structured_status(tmp_path) -> None:
    path = tmp_path / "facts.parquet"
    facts = _facts().filter(
        ~(
            (pl.col("grain_id") == "network")
            & (pl.col("entity_id") == "network")
            & (pl.col("period_start") == date(2025, 6, 1))
        )
    )
    write_mart_metric_facts(facts, path)
    service = AdditiveContributionService(path, mart_builds=(_build(),))

    response = service.contribution(_request())

    assert response.status == ContributionStatus.INSUFFICIENT_COMPARISON
    assert response.rows == ()
    assert "parent_current_or_reference_period_missing" in response.limitations


def _request(
    *,
    metric_concept: str = "revenue",
    parent_grain_id: str = "network",
    parent_entity_id: str = "network",
    child_grain_id: str = "category",
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
) -> ContributionQueryRequest:
    return ContributionQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        current_period=date(2026, 6, 1),
        reference_period=date(2025, 6, 1),
        period_grain="month",
        parent_grain_id=parent_grain_id,
        parent_entity_id=parent_entity_id,
        child_grain_id=child_grain_id,
        metric_concept=metric_concept,
        comparison_mode="YOY",
        private_label_scope=private_label_scope,
        mart_build_id="build_a",
    )


def _build() -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id="build_a",
        built_at=datetime(2026, 7, 1, tzinfo=UTC),
        build_version="test",
        code_version="test",
        retailer_id="retailer_a",
        source_ids=("source_a",),
        source_revision_ids=("revision_a",),
        analysis_run_ids=("analysis_a",),
        metric_config_hashes=("metric_hash_a",),
        rule_versions=("rules_v1",),
        status=MartBuildStatus.APPROVED,
        period_grain="month",
        period_start=date(2025, 6, 1),
        period_end=date(2026, 6, 30),
    )


def _facts(
    *,
    scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
    parent_current: float = 90.0,
    parent_reference: float = 100.0,
    child_current: tuple[float, float] = (35.0, 55.0),
    child_reference: tuple[float, float] = (50.0, 50.0),
) -> pl.DataFrame:
    rows = [
        _fact(date(2025, 6, 1), "network", "network", parent_reference, "retailer_a.network.revenue.v1", {}, scope),
        _fact(date(2026, 6, 1), "network", "network", parent_current, "retailer_a.network.revenue.v1", {}, scope),
        _fact(date(2025, 6, 1), "category", "CAT_A", child_reference[0], "retailer_a.category.revenue.v1", {"category": "CAT_A"}, scope),
        _fact(date(2026, 6, 1), "category", "CAT_A", child_current[0], "retailer_a.category.revenue.v1", {"category": "CAT_A"}, scope),
        _fact(date(2025, 6, 1), "category", "CAT_B", child_reference[1], "retailer_a.category.revenue.v1", {"category": "CAT_B"}, scope),
        _fact(date(2026, 6, 1), "category", "CAT_B", child_current[1], "retailer_a.category.revenue.v1", {"category": "CAT_B"}, scope),
    ]
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)


def _fact(
    period: date,
    grain: str,
    entity: str,
    value: float,
    definition_id: str,
    parent: dict[str, str],
    scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
) -> dict[str, object]:
    import json

    return {
        "retailer_id": "retailer_a",
        "source_id": "source_a",
        "source_revision_id": "revision_a",
        "analysis_run_id": "analysis_a",
        "mart_build_id": "build_a",
        "private_label_scope": scope.value,
        "period_grain": "month",
        "period_start": period,
        "period_end": date(period.year, period.month, 30),
        "business_period_id": period.strftime("%Y-%m"),
        "grain_id": grain,
        "entity_id": entity,
        "parent_entity_ids": json.dumps(parent, sort_keys=True),
        "metric_concept": "revenue",
        "metric_name": "revenue",
        "metric_definition_id": definition_id,
        "metric_definition_version": "v1",
        "metric_config_hash": "metric_hash_a",
        "semantic_family": "revenue",
        "semantic_compatibility_version": "v1",
        "cross_retailer_comparable": False,
        "value": value,
        "numerator_value": None,
        "denominator_value": None,
        "aggregation": "sum",
        "range_aggregation_strategy": "sum_available_periods",
        "share_scope": None,
        "rule_version": "rules_v1",
        "quality_status": "valid",
        "quality_flags": None,
        "created_at": datetime(2026, 7, 1, tzinfo=UTC),
    }
