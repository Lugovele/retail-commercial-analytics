from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import cast

import polars as pl
import pytest

from retail_analytics.mart import (
    ComparisonMode,
    DashboardMartQueryService,
    MartBuildMetadata,
    MartBuildStatus,
    PeriodMode,
    PortfolioConceptStatus,
    PortfolioMarketQueryRequest,
    PortfolioMarketService,
    PrivateLabelScope,
    RangeAggregationStrategy,
    write_mart_metric_facts,
)
from retail_analytics.mart import portfolio_market as portfolio_market_module
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA

_DEFAULT_ENTITY_FILTERS = object()


def test_portfolio_market_requires_concept_ids(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    with pytest.raises(ValueError, match="requires concept_ids"):
        service.query(_request(concept_ids=()))


def test_manufacturer_rank_is_category_scoped_with_projection_provenance(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(_request(concept_ids=("manufacturer_rank_revenue",)))

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.READY
    assert item.rows[0]["manufacturer"] == "manufacturer_b"
    assert item.rows[0]["rank"] == 1
    assert item.rows[1]["rank"] == 2
    assert item.rows[0]["category"] == "category_a"
    assert item.provenance is not None
    assert item.provenance["projection"]["projection_semantics"] == "competition_rank_by_summed_additive_metric"
    assert item.provenance["projection"]["population_scope"] == {
        "ranking_scope": "CATEGORY",
        "category": "category_a",
    }
    assert item.provenance["run_lineage"]["mart_build_id"] == "build_a"


def test_manufacturer_rank_rejects_uncategorized_scope(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(concept_ids=("manufacturer_rank_revenue",), entity_filters={}, grain_id="network")
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("manufacturer_rank_requires_category_scope",)


def test_manufacturer_rank_rejects_multi_category_scope(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            concept_ids=("manufacturer_rank_revenue", "manufacturer_population_count"),
            entity_filters={"category": ("category_a", "category_b")},
            grain_id="network",
        )
    )

    assert {item.status for item in response.items} == {PortfolioConceptStatus.NOT_APPLICABLE}
    assert {item.limitations for item in response.items} == {("portfolio_requires_single_category",)}


def test_manufacturer_rank_uses_user_category_after_execution_filter_resolution(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            concept_ids=("manufacturer_rank_revenue",),
            entity_filters={"sku": ("sku_a",)},
            user_entity_filters={"category": ("category_a",), "brand": ("brand_a",)},
            grain_id="network",
        )
    )

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.READY
    assert item.rows
    assert item.provenance is not None
    assert item.provenance["current_analytical_scope"]["entity_filters"] == {"sku": ("sku_a",)}
    assert item.provenance["current_analytical_scope"]["user_entity_filters"] == {
        "category": ("category_a",),
        "brand": ("brand_a",),
    }

def test_manufacturer_rank_preserves_store_scope(tmp_path) -> None:
    service = _service(tmp_path, _store_scope_portfolio_facts())
    request = _request(
        concept_ids=("manufacturer_rank_revenue", "manufacturer_population_count"),
        entity_filters={"category": ("category_a",), "store": ("store_a",)},
    )

    assert portfolio_market_module._projection_entity_filters(request, category="category_a") == {
        "category": ("category_a",),
        "store": ("store_a",),
    }

    response = service.query(request)

    rank_item = response.items[0]
    population_item = response.items[1]
    assert rank_item.status == PortfolioConceptStatus.PARTIAL
    assert rank_item.rows == ()
    assert rank_item.limitations == ("no_manufacturer_metric_facts",)
    assert population_item.status == PortfolioConceptStatus.PARTIAL
    assert rank_item.provenance is not None
    assert rank_item.provenance["current_analytical_scope"]["entity_filters"] == {
        "category": ("category_a",),
        "store": ("store_a",),
    }

def test_active_sku_uses_available_history_and_private_label_scope(tmp_path) -> None:
    facts = pl.concat(
        [
            _portfolio_facts(private_label_scope=PrivateLabelScope.INCLUDE),
            _portfolio_facts(private_label_scope=PrivateLabelScope.EXCLUDE, current_active_skus=("sku_a",)),
            _portfolio_facts(private_label_scope=PrivateLabelScope.ONLY, current_active_skus=("sku_b",)),
        ]
    )
    service = _service(tmp_path, facts)

    response = service.query(
        _request(
            concept_ids=("active_sku_count", "historical_peak_active_sku_count", "active_sku_change_pct"),
            private_label_scope=PrivateLabelScope.EXCLUDE,
        )
    )

    values = {item.concept_id: item.value for item in response.items}
    assert values["active_sku_count"] == 1
    assert values["historical_peak_active_sku_count"] == 2
    assert values["active_sku_change_pct"] == pytest.approx(-0.5)
    assert response.items[0].provenance is not None
    assert response.items[0].provenance["current_analytical_scope"]["private_label_scope"] == "EXCLUDE"


def test_active_sku_records_zero_active_period_as_evaluated(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts(current_active_skus=()))

    response = service.query(_request(concept_ids=("active_sku_count", "historical_peak_active_sku_count")))

    values = {item.concept_id: item.value for item in response.items}
    assert values["active_sku_count"] == 0
    assert values["historical_peak_active_sku_count"] == 2
    assert response.items[0].provenance is not None
    assert response.items[0].provenance["projection"]["evaluated_periods"] == (
        date(2025, 1, 1),
        date(2026, 1, 1),
    )


def test_active_sku_scalar_is_not_defined_for_date_range(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            period_mode=PeriodMode.DATE_RANGE,
            concept_ids=("active_sku_count",),
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("active_sku_scalar_not_defined_for_range",)


def test_brand_category_delta_gap_is_compare_only(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            grain_id="brand",
            entity_filters={"category": ("category_a",), "brand": ("brand_a",)},
            concept_ids=("brand_delta_pct", "category_delta_pct", "brand_category_delta_gap_pp"),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    values = {item.concept_id: item.value for item in response.items}
    assert values["brand_delta_pct"] == pytest.approx(0.2)
    assert values["category_delta_pct"] == pytest.approx(0.1)
    assert values["brand_category_delta_gap_pp"] == pytest.approx(0.1)
    assert response.items[2].provenance is not None
    assert response.items[2].provenance["projection"]["projection_semantics"] == (
        "brand_percentage_delta_minus_category_percentage_delta"
    )
    assert response.items[2].provenance["projection"]["evaluated_periods"] == (
        date(2025, 1, 1),
        date(2026, 1, 1),
    )
    assert response.items[2].provenance["input_metric_facts"]["fact_count"] == 4


def test_brand_category_delta_rejects_multi_select_denominators(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    category_response = service.query(
        _request(
            grain_id="brand",
            entity_filters={"category": ("category_a", "category_b"), "brand": ("brand_a",)},
            concept_ids=("brand_category_delta_gap_pp",),
            comparison_mode=ComparisonMode.YOY,
        )
    )
    brand_response = service.query(
        _request(
            grain_id="brand",
            entity_filters={"category": ("category_a",), "brand": ("brand_a", "brand_b")},
            concept_ids=("brand_category_delta_gap_pp",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert category_response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert category_response.items[0].limitations == ("portfolio_requires_single_category",)
    assert brand_response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert brand_response.items[0].limitations == ("brand_vs_category_requires_single_brand",)


def test_brand_category_delta_uses_user_brand_after_execution_filter_resolution(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            grain_id="network",
            entity_filters={"sku": ("sku_a",)},
            user_entity_filters={"category": ("category_a",), "brand": ("brand_a",)},
            concept_ids=("brand_category_delta_gap_pp",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.READY
    assert item.value == pytest.approx(0.1)
    assert item.provenance is not None
    assert item.provenance["current_analytical_scope"]["entity_filters"] == {"sku": ("sku_a",)}
    assert item.provenance["current_analytical_scope"]["user_entity_filters"] == {
        "category": ("category_a",),
        "brand": ("brand_a",),
    }

def test_brand_category_delta_preserves_store_scope(tmp_path) -> None:
    service = _service(tmp_path, _store_scope_portfolio_facts())
    request = _request(
        grain_id="brand",
        entity_filters={"category": ("category_a",), "brand": ("brand_a",), "store": ("store_a",)},
        concept_ids=("brand_delta_pct", "category_delta_pct", "brand_category_delta_gap_pp"),
        comparison_mode=ComparisonMode.YOY,
    )

    assert portfolio_market_module._projection_entity_filters(request, category="category_a") == {
        "category": ("category_a",),
        "store": ("store_a",),
    }

    response = service.query(request)

    values = {item.concept_id: item.value for item in response.items}
    assert values["brand_delta_pct"] is None
    assert values["category_delta_pct"] is None
    assert values["brand_category_delta_gap_pp"] is None
    assert response.items[2].status == PortfolioConceptStatus.PARTIAL
    assert response.items[2].provenance is not None
    assert response.items[2].provenance["input_metric_facts"]["fact_count"] == 0
    assert response.items[2].provenance["current_analytical_scope"]["entity_filters"] == {
        "category": ("category_a",),
        "brand": ("brand_a",),
        "store": ("store_a",),
    }

def test_brand_category_delta_is_not_range_safe(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            period_mode=PeriodMode.DATE_RANGE,
            grain_id="brand",
            entity_filters={"category": ("category_a",), "brand": ("brand_a",)},
            concept_ids=("brand_category_delta_gap_pp",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("brand_vs_category_requires_compare_mode",)


def test_share_items_inherit_metric_fact_provenance(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_ids=("manufacturer_a",),
            concept_ids=("category_revenue_share",),
            comparison_mode=ComparisonMode.NONE,
        )
    )

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.READY
    assert item.value == pytest.approx(0.3)
    assert item.numerator_value == pytest.approx(150.0)
    assert item.denominator_value == pytest.approx(500.0)
    assert item.provenance is not None
    assert item.provenance["metric"]["metric_definition_id"] == "manufacturer_a.category_revenue_share"


def test_share_comparison_missing_downgrades_to_partial(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_ids=("manufacturer_a",),
            concept_ids=("category_revenue_share",),
            comparison_mode=ComparisonMode.MOM,
        )
    )

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.PARTIAL
    assert item.reference_value is None
    assert "comparison_period_unavailable" in item.limitations


def test_share_null_value_downgrades_to_partial(tmp_path) -> None:
    facts = _portfolio_facts().with_columns(
        pl.when(
            (pl.col("metric_concept") == "category_revenue_share")
            & (pl.col("entity_id") == "manufacturer_a")
            & (pl.col("period_start") == date(2026, 1, 1))
        )
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("value"))
        .alias("value")
    )
    service = _service(tmp_path, facts)

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_ids=("manufacturer_a",),
            concept_ids=("category_revenue_share",),
            comparison_mode=ComparisonMode.NONE,
        )
    )

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.PARTIAL
    assert item.value is None


def test_share_comparison_matches_by_entity_not_shared_definition(tmp_path) -> None:
    facts = _portfolio_facts().with_columns(
        pl.when(pl.col("metric_concept") == "category_revenue_share")
        .then(pl.lit("shared.category_share.definition"))
        .otherwise(pl.col("metric_definition_id"))
        .alias("metric_definition_id")
    )
    service = _service(tmp_path, facts)

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_ids=("manufacturer_a", "manufacturer_b"),
            concept_ids=("category_revenue_share",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    by_entity = {item.entity_id: item for item in response.items}
    assert by_entity["manufacturer_a"].current_value == pytest.approx(0.3)
    assert by_entity["manufacturer_b"].current_value == pytest.approx(0.5)
    assert by_entity["manufacturer_a"].reference_value == pytest.approx(0.2)
    assert by_entity["manufacturer_b"].reference_value == pytest.approx(0.4)
    assert by_entity["manufacturer_a"].delta == pytest.approx(0.1)
    assert by_entity["manufacturer_b"].delta == pytest.approx(0.1)


def test_gated_market_and_competitor_concepts_are_honest(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            concept_ids=(
                "market_segment_delta_pct",
                "broad_competitors",
                "direct_peers",
                "abc",
                "recommendations",
            )
        )
    )

    assert {item.status for item in response.items} == {PortfolioConceptStatus.NOT_AVAILABLE}
    limitations = {item.limitations[0] for item in response.items}
    assert "market_universe_identity_not_materialized" in limitations
    assert "broad_competitor_projection_not_route_ready" in limitations
    assert "direct_peer_flavor_semantics_unresolved" in limitations


def _service(tmp_path, facts: pl.DataFrame) -> PortfolioMarketService:
    path = tmp_path / "portfolio_facts.parquet"
    write_mart_metric_facts(facts, path)
    return PortfolioMarketService(DashboardMartQueryService(path, mart_builds=(_build(),)))


def _request(
    *,
    concept_ids: tuple[str, ...],
    period_mode: PeriodMode = PeriodMode.SINGLE_PERIOD,
    comparison_mode: ComparisonMode = ComparisonMode.NONE,
    grain_id: str = "category",
    entity_ids: tuple[str, ...] = (),
    entity_filters: dict[str, tuple[str, ...]] | object | None = _DEFAULT_ENTITY_FILTERS,
    user_entity_filters: dict[str, tuple[str, ...]] | None = None,
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
) -> PortfolioMarketQueryRequest:
    default_filters: dict[str, tuple[str, ...]] = {"category": ("category_a",)}
    filters = default_filters if entity_filters is _DEFAULT_ENTITY_FILTERS else cast(
        dict[str, tuple[str, ...]] | None,
        entity_filters,
    )
    return PortfolioMarketQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 1),
        period_mode=period_mode,
        period_grain="month",
        grain_id=grain_id,
        entity_ids=entity_ids,
        entity_filters=filters,
        user_entity_filters=user_entity_filters,
        concept_ids=concept_ids,
        comparison_mode=comparison_mode,
        private_label_scope=private_label_scope,
    )


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
        metric_config_hashes=("hash_a",),
        rule_versions=("rules_v1",),
        status=MartBuildStatus.APPROVED,
        period_grain="month",
        period_start=date(2025, 1, 1),
        period_end=date(2026, 1, 31),
    )


def _portfolio_facts(
    *,
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
    current_active_skus: tuple[str, ...] = ("sku_a", "sku_b"),
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for period, category_revenue, brand_revenue in (
        (date(2025, 1, 1), 400.0, 100.0),
        (date(2026, 1, 1), 440.0, 120.0),
    ):
        rows.append(
            _fact(
                period,
                "category",
                "category_a",
                "category_revenue_share",
                category_revenue / 1100.0,
                "share",
                private_label_scope,
                numerator=category_revenue,
                denominator=1100.0,
                share_scope="network",
                parent_entity_ids={"category": "category_a"},
            )
        )
        rows.append(
            _fact(
                period,
                "category",
                "category_a",
                "revenue",
                category_revenue,
                "sum",
                private_label_scope,
                parent_entity_ids={"category": "category_a"},
            )
        )
        rows.append(
            _fact(
                period,
                "brand",
                "brand_a",
                "revenue",
                brand_revenue,
                "sum",
                private_label_scope,
                parent_entity_ids={"category": "category_a", "brand": "brand_a"},
            )
        )
    for manufacturer, value in (("manufacturer_a", 150.0), ("manufacturer_b", 250.0)):
        previous_share = 0.2 if manufacturer == "manufacturer_a" else 0.4
        current_share = 0.3 if manufacturer == "manufacturer_a" else 0.5
        rows.append(
            _fact(
                date(2026, 1, 1),
                "manufacturer",
                manufacturer,
                "revenue",
                value,
                "sum",
                private_label_scope,
                parent_entity_ids={"category": "category_a", "manufacturer": manufacturer},
            )
        )
        rows.append(
            _fact(
                date(2025, 1, 1),
                "manufacturer",
                manufacturer,
                "category_revenue_share",
                previous_share,
                "share",
                private_label_scope,
                numerator=value - 50.0,
                denominator=500.0,
                share_scope="category",
                parent_entity_ids={"category": "category_a", "manufacturer": manufacturer},
            )
        )
        rows.append(
            _fact(
                date(2026, 1, 1),
                "manufacturer",
                manufacturer,
                "category_revenue_share",
                current_share,
                "share",
                private_label_scope,
                numerator=value,
                denominator=500.0,
                share_scope="category",
                parent_entity_ids={"category": "category_a", "manufacturer": manufacturer},
            )
        )
        rows.append(
            _fact(
                date(2026, 1, 1),
                "manufacturer",
                manufacturer,
                "units",
                value / 10,
                "sum",
                private_label_scope,
                parent_entity_ids={"category": "category_a", "manufacturer": manufacturer},
            )
        )
    for period, active_skus in (
        (date(2025, 1, 1), ("sku_a", "sku_b")),
        (date(2026, 1, 1), current_active_skus),
    ):
        for sku in ("sku_a", "sku_b"):
            rows.append(
                _fact(
                    period,
                    "sku",
                    sku,
                    "units",
                    1.0 if sku in active_skus else 0.0,
                    "sum",
                    private_label_scope,
                    parent_entity_ids={"category": "category_a", "sku": sku},
                )
            )
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)


def _store_scope_portfolio_facts() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for manufacturer, value in (("manufacturer_a", 500.0), ("manufacturer_b", 50.0)):
        rows.append(
            _fact(
                date(2026, 1, 1),
                "manufacturer",
                manufacturer,
                "revenue",
                value,
                "sum",
                PrivateLabelScope.INCLUDE,
                parent_entity_ids={
                    "category": "category_a",
                    "manufacturer": manufacturer,
                    "canonical_store_id": "store_a",
                },
            )
        )
    for period, category_revenue, brand_revenue in (
        (date(2025, 1, 1), 100.0, 50.0),
        (date(2026, 1, 1), 50.0, 90.0),
    ):
        rows.append(
            _fact(
                period,
                "category",
                "category_a",
                "revenue",
                category_revenue,
                "sum",
                PrivateLabelScope.INCLUDE,
                parent_entity_ids={"category": "category_a", "canonical_store_id": "store_a"},
            )
        )
        rows.append(
            _fact(
                period,
                "brand",
                "brand_a",
                "revenue",
                brand_revenue,
                "sum",
                PrivateLabelScope.INCLUDE,
                parent_entity_ids={
                    "category": "category_a",
                    "brand": "brand_a",
                    "canonical_store_id": "store_a",
                },
            )
        )
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)

def _fact(
    period: date,
    grain_id: str,
    entity_id: str,
    concept: str,
    value: float | None,
    aggregation: str,
    private_label_scope: PrivateLabelScope,
    *,
    numerator: float | None = None,
    denominator: float | None = None,
    share_scope: str | None = None,
    parent_entity_ids: dict[str, str] | None = None,
) -> dict[str, object]:
    strategy = {
        "sum": RangeAggregationStrategy.SUM_AVAILABLE_PERIODS,
        "share": RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
    }[aggregation]
    return {
        "retailer_id": "retailer_a",
        "source_id": "source_a",
        "source_revision_id": "revision_a",
        "analysis_run_id": "analysis_a",
        "mart_build_id": "build_a",
        "private_label_scope": private_label_scope.value,
        "period_grain": "month",
        "period_start": period,
        "period_end": date(period.year, period.month, 28),
        "business_period_id": period.strftime("%Y-%m"),
        "grain_id": grain_id,
        "entity_id": entity_id,
        "parent_entity_ids": json.dumps(parent_entity_ids or {}, sort_keys=True),
        "metric_concept": concept,
        "metric_name": concept,
        "metric_definition_id": f"{entity_id}.{concept}",
        "metric_definition_version": "v1",
        "metric_config_hash": "hash_a",
        "semantic_family": concept,
        "semantic_compatibility_version": "v1",
        "cross_retailer_comparable": False,
        "value": value,
        "numerator_value": numerator,
        "denominator_value": denominator,
        "aggregation": aggregation,
        "range_aggregation_strategy": strategy,
        "share_scope": share_scope,
        "rule_version": "rules_v1",
        "quality_status": "valid",
        "quality_flags": None,
        "created_at": datetime(2026, 1, 15, tzinfo=UTC),
    }
