from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from retail_analytics.mart import (
    PrivateLabelScope,
    RangeAggregationStrategy,
    build_mart_metric_facts,
    duplicate_semantic_identities,
    metric_fact_semantic_identity_columns,
    range_strategy_for_metric,
)
from retail_analytics.mart.builds import MartBuildMetadata, mart_build_id


def test_deterministic_metric_row_projects_to_mart_fact() -> None:
    facts = build_mart_metric_facts(_metrics(), build_metadata=_build(), source_revision_id="revision_a")

    assert facts.height == 2
    assert facts["value"].to_list() == [100.0, 0.25]
    assert facts["period_start"].to_list() == [date(2025, 1, 1), date(2025, 1, 1)]
    assert facts["period_end"].to_list() == [date(2025, 1, 31), date(2025, 1, 31)]


def test_lineage_and_metric_identity_are_preserved() -> None:
    facts = build_mart_metric_facts(_metrics(), build_metadata=_build(), source_revision_id="revision_a")
    row = facts.filter(pl.col("metric_concept") == "revenue").row(0, named=True)

    assert row["retailer_id"] == "retailer_a"
    assert row["source_id"] == "source_a"
    assert row["source_revision_id"] == "revision_a"
    assert row["analysis_run_id"] == "analysis_a"
    assert row["mart_build_id"] == _build().mart_build_id
    assert row["private_label_scope"] == PrivateLabelScope.INCLUDE
    assert row["metric_definition_id"] == "retailer_a.revenue.v1"
    assert row["metric_definition_version"] == "v1"
    assert row["metric_config_hash"] == "metric_hash_a"
    assert row["rule_version"] == "rules_v1"


def test_numerator_denominator_grain_and_period_are_preserved() -> None:
    facts = build_mart_metric_facts(_metrics(), build_metadata=_build(), source_revision_id="revision_a")
    margin = facts.filter(pl.col("metric_concept") == "retailer_margin_pct").row(0, named=True)

    assert margin["numerator_value"] == 25.0
    assert margin["denominator_value"] == 100.0
    assert margin["grain_id"] == "sku"
    assert margin["entity_id"] == "SKU_A_001"
    assert margin["business_period_id"] == "2025-01-01"


def test_range_strategy_assigned_correctly() -> None:
    assert range_strategy_for_metric(aggregation="sum", metric_concept="revenue") == RangeAggregationStrategy.SUM_AVAILABLE_PERIODS
    assert range_strategy_for_metric(aggregation="ratio_of_sums", metric_concept="retailer_margin_pct") == RangeAggregationStrategy.RATIO_OF_SUMS
    assert range_strategy_for_metric(aggregation="weighted_average", metric_concept="shelf_price") == RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS
    assert range_strategy_for_metric(aggregation="ratio_of_sums", metric_concept="numeric_distribution") == RangeAggregationStrategy.PERIOD_ONLY
    assert range_strategy_for_metric(aggregation="ratio_of_sums", metric_concept="units_per_selling_store") == RangeAggregationStrategy.PERIOD_ONLY
    assert range_strategy_for_metric(aggregation="share", metric_concept="category_revenue_share") == RangeAggregationStrategy.PERIOD_ONLY
    assert range_strategy_for_metric(aggregation="distinct_count", metric_concept="selling_store_count") == RangeAggregationStrategy.PERIOD_ONLY


def test_builder_does_not_recalculate_formula_values() -> None:
    metrics = _metrics().with_columns(
        pl.when(pl.col("concept") == "retailer_margin_pct")
        .then(pl.lit(999.0))
        .otherwise(pl.col("metric_value"))
        .alias("metric_value")
    )

    facts = build_mart_metric_facts(metrics, build_metadata=_build(), source_revision_id="revision_a")

    assert facts.filter(pl.col("metric_concept") == "retailer_margin_pct")["value"].to_list() == [999.0]


def test_duplicate_semantic_identity_is_rejected() -> None:
    duplicate = pl.concat([_metrics(), _metrics()])

    with pytest.raises(ValueError, match="Duplicate mart metric semantic identities"):
        build_mart_metric_facts(duplicate, build_metadata=_build(), source_revision_id="revision_a")


def test_semantic_identity_includes_definition_and_build_lineage() -> None:
    columns = metric_fact_semantic_identity_columns()

    assert "mart_build_id" in columns
    assert "private_label_scope" in columns
    assert "metric_definition_id" in columns
    assert "metric_definition_version" in columns
    assert "metric_config_hash" in columns
    assert "rule_version" in columns


def test_old_and_new_source_revision_facts_remain_distinguishable() -> None:
    first = build_mart_metric_facts(_metrics(), build_metadata=_build("build_a"), source_revision_id="revision_a")
    second_build = MartBuildMetadata(**{**_build("build_b").__dict__, "source_revision_ids": ("revision_b",)})
    second = build_mart_metric_facts(_metrics(), build_metadata=second_build, source_revision_id="revision_b")
    combined = pl.concat([first, second])

    assert duplicate_semantic_identities(combined).is_empty()
    assert set(combined["source_revision_id"].to_list()) == {"revision_a", "revision_b"}
    assert set(combined["mart_build_id"].to_list()) == {"build_a", "build_b"}


def test_private_label_scoped_facts_do_not_collide() -> None:
    include = build_mart_metric_facts(
        _metrics(),
        build_metadata=_build(),
        source_revision_id="revision_a",
        private_label_scope=PrivateLabelScope.INCLUDE,
    )
    exclude = build_mart_metric_facts(
        _metrics(),
        build_metadata=_build(),
        source_revision_id="revision_a",
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )
    combined = pl.concat([include, exclude])

    assert duplicate_semantic_identities(combined).is_empty()
    assert set(combined["private_label_scope"].to_list()) == {"INCLUDE", "EXCLUDE"}


def _build(build_id: str | None = None) -> MartBuildMetadata:
    resolved_build_id = build_id or mart_build_id(
        retailer_id="retailer_a",
        source_revision_ids=("revision_a",),
        analysis_run_ids=("analysis_a",),
        metric_config_hashes=("metric_hash_a",),
        rule_versions=("rules_v1",),
        build_version="mart.v1",
    )
    return MartBuildMetadata(
        mart_build_id=resolved_build_id,
        built_at=datetime(2026, 1, 15, tzinfo=UTC),
        build_version="mart.v1",
        code_version="test_code_version",
        retailer_id="retailer_a",
        source_ids=("source_a",),
        source_revision_ids=("revision_a",),
        analysis_run_ids=("analysis_a",),
        metric_config_hashes=("metric_hash_a",),
        rule_versions=("rules_v1",),
        period_grain="month",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        input_row_count=2,
        fact_row_count=2,
    )


def _metrics() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["analysis_a", "analysis_a"],
            "retailer_id": ["retailer_a", "retailer_a"],
            "source_id": ["source_a", "source_a"],
            "period": ["2025-01", "2025-01"],
            "grain_id": ["sku", "sku"],
            "entity_id": ["SKU_A_001", "SKU_A_001"],
            "concept": ["revenue", "retailer_margin_pct"],
            "name": ["revenue", "retailer_margin_pct"],
            "metric_definition_id": ["retailer_a.revenue.v1", "retailer_a.margin_pct.v1"],
            "metric_definition_version": ["v1", "v1"],
            "metric_config_hash": ["metric_hash_a", "metric_hash_a"],
            "metric_value": [100.0, 0.25],
            "numerator_value": [None, 25.0],
            "denominator_value": [None, 100.0],
            "aggregation": ["sum", "ratio_of_sums"],
            "rule_version": ["rules_v1", "rules_v1"],
            "share_scope": [None, None],
        }
    )



def test_distribution_without_components_is_period_only() -> None:
    metrics = _metrics().filter(pl.col("concept") == "revenue").with_columns(
        pl.lit("distribution").alias("concept"),
        pl.lit("numeric_distribution").alias("name"),
        pl.lit("retailer_a.distribution.v1").alias("metric_definition_id"),
        pl.lit("ratio_of_sums").alias("aggregation"),
        pl.lit(None, dtype=pl.Float64).alias("numerator_value"),
        pl.lit(None, dtype=pl.Float64).alias("denominator_value"),
    )

    facts = build_mart_metric_facts(metrics, build_metadata=_build(), source_revision_id="revision_a")

    assert facts["range_aggregation_strategy"].to_list() == [RangeAggregationStrategy.PERIOD_ONLY]


def test_distribution_with_components_is_recompute_from_components() -> None:
    metrics = _metrics().filter(pl.col("concept") == "revenue").with_columns(
        pl.lit("distribution").alias("concept"),
        pl.lit("numeric_distribution").alias("name"),
        pl.lit("retailer_a.distribution.v1").alias("metric_definition_id"),
        pl.lit("ratio_of_sums").alias("aggregation"),
        pl.lit(2.0).alias("numerator_value"),
        pl.lit(4.0).alias("denominator_value"),
    )

    facts = build_mart_metric_facts(metrics, build_metadata=_build(), source_revision_id="revision_a")

    assert facts["range_aggregation_strategy"].to_list() == [RangeAggregationStrategy.PERIOD_ONLY]


def test_business_period_id_is_preserved_when_available() -> None:
    metrics = _metrics().with_columns(pl.lit("2025-01").alias("business_period_id"))

    facts = build_mart_metric_facts(metrics, build_metadata=_build(), source_revision_id="revision_a")

    assert set(facts["business_period_id"].to_list()) == {"2025-01"}


def test_build_metadata_scope_is_validated() -> None:
    metrics = _metrics().with_columns(pl.lit("retailer_b").alias("retailer_id"))

    with pytest.raises(ValueError, match="retailer_id outside mart build metadata"):
        build_mart_metric_facts(metrics, build_metadata=_build(), source_revision_id="revision_a")


def test_multi_source_build_requires_source_revision_mapping() -> None:
    source_b = _metrics().with_columns(
        pl.lit("source_b").alias("source_id"),
        pl.lit("SKU_A_002").alias("entity_id"),
    )
    metrics = pl.concat([_metrics(), source_b])
    build = MartBuildMetadata(
        **{
            **_build().__dict__,
            "source_ids": ("source_a", "source_b"),
            "source_revision_ids": ("revision_a", "revision_b"),
        }
    )

    with pytest.raises(ValueError, match="Multi-source mart builds require"):
        build_mart_metric_facts(metrics, build_metadata=build, source_revision_id="revision_a")

    facts = build_mart_metric_facts(
        metrics,
        build_metadata=build,
        source_revision_id={"source_a": "revision_a", "source_b": "revision_b"},
    )
    assert set(facts.filter(pl.col("source_id") == "source_b")["source_revision_id"].to_list()) == {"revision_b"}





def test_source_revision_mapping_must_match_build_metadata() -> None:
    with pytest.raises(ValueError, match="outside mart build metadata"):
        build_mart_metric_facts(_metrics(), build_metadata=_build(), source_revision_id="revision_b")


def test_row_source_revision_must_match_build_metadata() -> None:
    metrics = _metrics().with_columns(pl.lit("revision_b").alias("source_revision_id"))

    with pytest.raises(ValueError, match="source_revision_id outside mart build metadata"):
        build_mart_metric_facts(metrics, build_metadata=_build(), source_revision_id=None)


