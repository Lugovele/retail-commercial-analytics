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
    assert item.provenance["projection"]["population_scope"]["ranking_scope"] == "CATEGORY"
    assert item.provenance["projection"]["population_scope"]["ranking_universe_type"] == "selected_category_entities"
    assert item.provenance["projection"]["population_scope"]["rank_entity_type"] == "manufacturer"
    assert item.provenance["projection"]["population_scope"]["rank_basis_metric"] == "revenue"
    assert item.provenance["projection"]["population_scope"]["current_universe_size"] == 3
    assert item.provenance["projection"]["deterministic_secondary_sort"] == "entity_id_ascending"
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


def test_manufacturer_rank_rejects_multi_category_entity_ids(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            concept_ids=("manufacturer_rank_revenue",),
            entity_filters={},
            entity_ids=("category_a", "category_b"),
            grain_id="category",
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("portfolio_requires_single_category",)


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
    assert rank_item.status == PortfolioConceptStatus.NOT_APPLICABLE
    assert rank_item.rows == ()
    assert rank_item.limitations == ("rank_scope_filter_unsupported",)
    assert population_item.status == PortfolioConceptStatus.PARTIAL
    assert rank_item.provenance is not None
    assert rank_item.provenance["current_analytical_scope"]["entity_filters"] == {
        "category": ("category_a",),
        "store": ("store_a",),
    }


def test_rank_rejects_unsupported_scope_in_user_filters(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            concept_ids=("manufacturer_rank_revenue",),
            entity_filters={"sku": ("sku_a",)},
            user_entity_filters={"category": ("category_a",), "store": ("store_a",)},
            grain_id="network",
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("rank_scope_filter_unsupported",)


def test_manufacturer_rank_movement_uses_inverted_rank_delta(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(concept_ids=("manufacturer_rank_revenue",), comparison_mode=ComparisonMode.YOY)
    )

    rows = {row["entity_id"]: row for row in response.items[0].rows}
    assert rows["manufacturer_b"]["current_rank"] == 1
    assert rows["manufacturer_b"]["reference_rank"] == 2
    assert rows["manufacturer_b"]["rank_movement_positions"] == 1
    assert rows["manufacturer_b"]["rank_movement_state"] == "IMPROVED"
    assert rows["manufacturer_a"]["rank_movement_positions"] == -1
    assert rows["manufacturer_a"]["rank_movement_state"] == "DECLINED"
    assert response.items[0].provenance is not None
    assert response.items[0].provenance["projection"]["rank_movement_semantics"] == (
        "reference_rank_minus_current_rank"
    )


def test_rank_movement_marks_new_and_exited_entities_without_fake_ranks(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(concept_ids=("manufacturer_rank_revenue",), comparison_mode=ComparisonMode.YOY)
    )

    rows = {row["entity_id"]: row for row in response.items[0].rows}
    assert rows["manufacturer_c"]["rank_movement_state"] == "NEW_IN_RANK_UNIVERSE"
    assert rows["manufacturer_c"]["reference_rank"] is None
    assert rows["manufacturer_c"]["rank_movement_positions"] is None
    assert rows["manufacturer_d"]["rank_movement_state"] == "EXITED_RANK_UNIVERSE"
    assert rows["manufacturer_d"]["current_rank"] is None
    assert rows["manufacturer_d"]["rank_movement_positions"] is None
    assert {row["current_universe_size"] for row in rows.values()} == {3}
    assert {row["reference_universe_size"] for row in rows.values()} == {3}


def test_rank_movement_respects_focal_entity_selection_after_universe_ranking(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            concept_ids=("manufacturer_rank_revenue",),
            comparison_mode=ComparisonMode.YOY,
            entity_filters={"category": ("category_a",), "manufacturer": ("manufacturer_a",)},
        )
    )

    assert [row["entity_id"] for row in response.items[0].rows] == ["manufacturer_a"]
    assert response.items[0].rows[0]["current_universe_size"] == 3


def test_rank_range_semantics_fail_closed_without_averaging(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(period_mode=PeriodMode.DATE_RANGE, concept_ids=("manufacturer_rank_revenue",))
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("rank_range_semantics_unsupported",)


def test_rank_movement_missing_reference_period_fails_closed(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(concept_ids=("manufacturer_rank_revenue",), comparison_mode=ComparisonMode.MOM)
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].rows == ()
    assert response.items[0].limitations == ("comparison_period_unavailable",)


def test_rank_null_metric_value_is_not_zero_filled(tmp_path) -> None:
    facts = _portfolio_facts().with_columns(
        pl.when(
            (pl.col("metric_concept") == "revenue")
            & (pl.col("entity_id") == "manufacturer_c")
            & (pl.col("period_start") == date(2026, 1, 1))
        )
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("value"))
        .alias("value")
    )
    service = _service(tmp_path, facts)

    response = service.query(_request(concept_ids=("manufacturer_rank_revenue",)))

    assert "manufacturer_c" not in {row["entity_id"] for row in response.items[0].rows}


def test_manufacturer_abc_requires_explicit_ownership_universe(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(_request(grain_id="manufacturer", concept_ids=("manufacturer_abc_revenue",)))

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("abc_ownership_universe_required",)


def test_manufacturer_abc_reuses_rank_share_cumulative_rows(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts(private_label_scope=PrivateLabelScope.ONLY))

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    item = response.items[0]
    rows = {row["entity_id"]: row for row in item.rows}
    assert item.status == PortfolioConceptStatus.READY
    assert [row["entity_id"] for row in item.rows] == ["manufacturer_b", "manufacturer_a", "manufacturer_c"]
    assert rows["manufacturer_b"]["abc_class"] == "A"
    assert rows["manufacturer_a"]["abc_class"] == "B"
    assert rows["manufacturer_c"]["abc_class"] == "C"
    assert rows["manufacturer_a"]["share"] == pytest.approx(150.0 / 450.0)
    assert rows["manufacturer_a"]["cumulative_share"] == pytest.approx(400.0 / 450.0)
    assert item.provenance is not None
    assert item.provenance["projection"]["projection_semantics"] == (
        "abc_classification_from_cumulative_share_projection"
    )
    assert item.provenance["projection"]["population_scope"]["ownership_universe"] == "OWN_PORTFOLIO_CATEGORY"
    assert item.provenance["projection"]["population_scope"]["threshold_crossing_policy"] == (
        "class_by_cumulative_share_after_entity"
    )


def test_abc_threshold_crossing_uses_after_row_cumulative_share(tmp_path) -> None:
    service = _service(tmp_path, _abc_facts(("entity_a", 79.0), ("entity_b", 15.0), ("entity_c", 3.0), ("entity_d", 3.0)))

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    rows = {row["entity_id"]: row for row in response.items[0].rows}
    assert rows["entity_a"]["abc_class"] == "A"
    assert rows["entity_b"]["abc_class"] == "B"
    assert rows["entity_c"]["abc_class"] == "C"
    assert rows["entity_b"]["cumulative_share"] == pytest.approx(0.94)
    assert rows["entity_c"]["cumulative_share"] == pytest.approx(0.97)


def test_abc_first_row_remains_a_when_it_crosses_eighty_percent(tmp_path) -> None:
    service = _service(tmp_path, _abc_facts(("entity_a", 84.0), ("entity_b", 10.0), ("entity_c", 6.0)))

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    rows = {row["entity_id"]: row for row in response.items[0].rows}
    assert rows["entity_a"]["abc_class"] == "A"
    assert rows["entity_b"]["abc_class"] == "B"
    assert rows["entity_c"]["abc_class"] == "C"


def test_abc_ties_use_stable_order_and_may_split_at_threshold(tmp_path) -> None:
    service = _service(tmp_path, _abc_facts(("entity_a", 50.0), ("entity_b", 30.0), ("entity_c", 30.0)))

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    rows = response.items[0].rows
    assert [row["entity_id"] for row in rows] == ["entity_a", "entity_b", "entity_c"]
    assert rows[1]["rank"] == rows[2]["rank"] == 2
    assert rows[1]["abc_class"] == "A"
    assert rows[2]["abc_class"] == "C"
    assert response.items[0].provenance is not None
    assert response.items[0].provenance["projection"]["tie_policy"] == (
        "competition_rank_with_entity_id_secondary_order_may_split_ties"
    )


def test_abc_first_row_policy_is_position_based_not_rank_based_for_top_ties(tmp_path) -> None:
    service = _service(tmp_path, _abc_facts(("entity_a", 50.0), ("entity_b", 50.0), ("entity_c", 10.0)))

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    rows = response.items[0].rows
    assert [row["entity_id"] for row in rows] == ["entity_a", "entity_b", "entity_c"]
    assert rows[0]["rank"] == rows[1]["rank"] == 1
    assert rows[0]["abc_class"] == "A"
    assert rows[1]["abc_class"] == "B"
    assert rows[1]["cumulative_share"] == pytest.approx(100.0 / 110.0)


def test_abc_zero_values_are_classified_c_when_universe_is_positive(tmp_path) -> None:
    service = _service(tmp_path, _abc_facts(("entity_a", 100.0), ("entity_b", 0.0)))

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    rows = {row["entity_id"]: row for row in response.items[0].rows}
    assert rows["entity_b"]["share"] == pytest.approx(0.0)
    assert rows["entity_b"]["abc_class"] == "C"


def test_abc_negative_margin_fails_closed(tmp_path) -> None:
    service = _service(
        tmp_path,
        _abc_facts(("entity_a", 100.0), ("entity_b", -5.0), concept="retailer_margin_abs"),
    )

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_margin_abs",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("abc_negative_contribution_semantics_unsupported",)


def test_abc_zero_denominator_fails_closed(tmp_path) -> None:
    service = _service(tmp_path, _abc_facts(("entity_a", 0.0), ("entity_b", 0.0)))

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("abc_positive_universe_required",)


def test_abc_focal_selection_happens_after_full_universe_classification(tmp_path) -> None:
    service = _service(tmp_path, _abc_facts(("entity_a", 79.0), ("entity_b", 15.0), ("entity_c", 3.0), ("entity_d", 3.0)))

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_filters={"category": ("category_a",), "manufacturer": ("entity_b",)},
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    assert [row["entity_id"] for row in response.items[0].rows] == ["entity_b"]
    assert response.items[0].rows[0]["abc_class"] == "B"
    assert response.items[0].rows[0]["universe_metric_value"] == pytest.approx(100.0)


def test_abc_own_and_competitor_universes_are_separate(tmp_path) -> None:
    facts = pl.concat(
        [
            _abc_facts(("entity_a", 70.0), ("entity_b", 30.0), private_label_scope=PrivateLabelScope.ONLY),
            _abc_facts(("entity_a", 20.0), ("entity_b", 80.0), private_label_scope=PrivateLabelScope.EXCLUDE),
        ]
    )
    service = _service(tmp_path, facts)

    own = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )
    competitor = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.EXCLUDE,
        )
    )

    assert own.items[0].rows[0]["entity_id"] == "entity_a"
    assert competitor.items[0].rows[0]["entity_id"] == "entity_b"
    assert own.items[0].provenance["projection"]["population_scope"]["ownership_universe"] == "OWN_PORTFOLIO_CATEGORY"
    assert competitor.items[0].provenance["projection"]["population_scope"]["ownership_universe"] == (
        "COMPETITOR_CATEGORY"
    )


def test_sku_abc_supports_three_bases_without_composite_score(tmp_path) -> None:
    facts = pl.concat(
        [
            _abc_facts(("sku_a", 60.0), ("sku_b", 40.0), grain_id="sku", concept="revenue"),
            _abc_facts(("sku_a", 40.0), ("sku_b", 60.0), grain_id="sku", concept="units"),
            _abc_facts(("sku_a", 50.0), ("sku_b", 50.0), grain_id="sku", concept="retailer_margin_abs"),
        ]
    )
    service = _service(tmp_path, facts)

    responses = [
        service.query(
            _request(grain_id="sku", concept_ids=(concept,), private_label_scope=PrivateLabelScope.ONLY)
        ).items[0]
        for concept in ("sku_abc_revenue", "sku_abc_units", "sku_abc_margin_abs")
    ]

    assert [item.provenance["projection"]["component_metric_concepts"][0] for item in responses] == [
        "revenue",
        "units",
        "retailer_margin_abs",
    ]
    assert all("composite" not in item.provenance["projection"]["projection_semantics"] for item in responses)


def test_abc_rejects_range_multi_category_and_store_scopes(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts(private_label_scope=PrivateLabelScope.ONLY))

    range_response = service.query(
        _request(
            grain_id="manufacturer",
            period_mode=PeriodMode.DATE_RANGE,
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )
    category_response = service.query(
        _request(
            grain_id="manufacturer",
            entity_filters={"category": ("category_a", "category_b")},
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )
    store_response = service.query(
        _request(
            grain_id="manufacturer",
            entity_filters={"category": ("category_a",), "store": ("store_a",)},
            concept_ids=("manufacturer_abc_revenue",),
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    assert range_response.items[0].limitations == ("abc_range_semantics_unsupported",)
    assert category_response.items[0].limitations == ("portfolio_requires_single_category",)
    assert store_response.items[0].limitations == ("abc_scope_filter_unsupported",)


def test_entity_share_recomputes_denominator_from_additive_metric_values(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(_request(grain_id="manufacturer", concept_ids=("entity_revenue_share",)))

    item = response.items[0]
    rows = {row["entity_id"]: row for row in item.rows}
    assert item.status == PortfolioConceptStatus.READY
    assert rows["manufacturer_b"]["share"] == pytest.approx(250.0 / 450.0)
    assert rows["manufacturer_a"]["share"] == pytest.approx(150.0 / 450.0)
    assert {row["universe_metric_value"] for row in item.rows} == {450.0}
    assert item.provenance is not None
    assert item.provenance["projection"]["projection_semantics"] == "share_of_defined_universe_from_additive_metric"
    assert item.provenance["projection"]["component_metric_concepts"] == ("revenue",)
    assert item.provenance["projection"]["population_scope"]["share_entity_type"] == "manufacturer"
    assert item.provenance["projection"]["population_scope"]["universe_type"] == "selected_category_entities"


def test_entity_share_supports_units_and_absolute_margin_bases(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    sku_response = service.query(_request(grain_id="sku", concept_ids=("entity_units_share",)))
    brand_response = service.query(_request(grain_id="brand", concept_ids=("entity_margin_share",)))

    sku_rows = {row["entity_id"]: row for row in sku_response.items[0].rows}
    brand_rows = {row["entity_id"]: row for row in brand_response.items[0].rows}
    assert sku_rows["sku_a"]["share"] == pytest.approx(0.5)
    assert sku_rows["sku_b"]["share"] == pytest.approx(0.5)
    assert brand_rows["brand_a"]["share"] == pytest.approx(40.0 / 120.0)
    assert brand_rows["brand_b"]["share"] == pytest.approx(80.0 / 120.0)
    assert brand_response.items[0].provenance is not None
    assert brand_response.items[0].provenance["projection"]["component_metric_concepts"] == ("retailer_margin_abs",)


def test_entity_share_does_not_query_precomputed_share_metric_facts(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, _portfolio_facts())
    requested_metric_concepts: list[tuple[str, ...]] = []
    original_query = service.query_service.query

    def capture_query(request):
        requested_metric_concepts.append(request.metric_concepts)
        return original_query(request)

    monkeypatch.setattr(service.query_service, "query", capture_query)

    service.query(_request(grain_id="manufacturer", concept_ids=("entity_revenue_share",)))

    assert requested_metric_concepts == [("revenue",)]
    assert all(
        "share" not in metric_concept
        for metric_concepts in requested_metric_concepts
        for metric_concept in metric_concepts
    )


def test_category_entity_share_uses_network_universe(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(grain_id="category", entity_filters={}, concept_ids=("entity_revenue_share",))
    )

    rows = {row["entity_id"]: row for row in response.items[0].rows}
    assert rows["category_a"]["share"] == pytest.approx(440.0 / 940.0)
    assert rows["category_b"]["share"] == pytest.approx(500.0 / 940.0)
    assert {row["universe_type"] for row in response.items[0].rows} == {"network_entities"}


def test_entity_share_applies_focal_selection_after_universe_calculation(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_filters={"category": ("category_a",), "manufacturer": ("manufacturer_a",)},
            concept_ids=("entity_revenue_share",),
        )
    )

    assert [row["entity_id"] for row in response.items[0].rows] == ["manufacturer_a"]
    assert response.items[0].rows[0]["share"] == pytest.approx(150.0 / 450.0)
    assert response.items[0].rows[0]["universe_metric_value"] == pytest.approx(450.0)


def test_entity_share_supports_multi_select_focal_entities_with_common_denominator(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_filters={"category": ("category_a",), "manufacturer": ("manufacturer_a", "manufacturer_b")},
            concept_ids=("entity_revenue_share",),
        )
    )

    assert [row["entity_id"] for row in response.items[0].rows] == ["manufacturer_b", "manufacturer_a"]
    assert {row["universe_metric_value"] for row in response.items[0].rows} == {450.0}


def test_entity_share_uses_stm_scope_for_numerator_and_denominator(tmp_path) -> None:
    facts = pl.concat(
        [
            _portfolio_facts(private_label_scope=PrivateLabelScope.INCLUDE),
            _portfolio_facts(private_label_scope=PrivateLabelScope.EXCLUDE).with_columns(
                pl.when(
                    (pl.col("metric_concept") == "revenue")
                    & (pl.col("grain_id") == "manufacturer")
                    & (pl.col("period_start") == date(2026, 1, 1))
                )
                .then(pl.col("value") * 2.0)
                .otherwise(pl.col("value"))
                .alias("value")
            ),
        ]
    )
    service = _service(tmp_path, facts)

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("entity_revenue_share",),
            private_label_scope=PrivateLabelScope.EXCLUDE,
        )
    )

    assert {row["universe_metric_value"] for row in response.items[0].rows} == {900.0}
    assert response.items[0].provenance is not None
    assert response.items[0].provenance["projection"]["population_scope"]["private_label_scope_applies_to"] == (
        "numerator_and_denominator"
    )


def test_entity_cumulative_share_reuses_rank_order_and_underlying_values(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    rank_response = service.query(_request(grain_id="manufacturer", concept_ids=("manufacturer_rank_revenue",)))
    share_response = service.query(
        _request(grain_id="manufacturer", concept_ids=("entity_cumulative_revenue_share",))
    )

    rank_rows = rank_response.items[0].rows
    share_rows = share_response.items[0].rows
    assert [row["entity_id"] for row in share_rows] == [row["entity_id"] for row in rank_rows]
    assert [row["rank"] for row in share_rows] == [row["rank"] for row in rank_rows]
    assert share_rows[0]["cumulative_share"] == pytest.approx(250.0 / 450.0)
    assert share_rows[-1]["cumulative_share"] == pytest.approx(1.0)
    assert share_response.items[0].provenance is not None
    assert share_response.items[0].provenance["projection"]["tie_policy"] == "competition_rank"


def test_cumulative_share_ties_are_deterministic_by_entity_id(tmp_path) -> None:
    facts = _portfolio_facts().with_columns(
        pl.when(
            (pl.col("metric_concept") == "revenue")
            & (pl.col("grain_id") == "manufacturer")
            & (pl.col("period_start") == date(2026, 1, 1))
            & (pl.col("entity_id").is_in(["manufacturer_a", "manufacturer_b"]))
        )
        .then(pl.lit(200.0))
        .otherwise(pl.col("value"))
        .alias("value")
    )
    service = _service(tmp_path, facts)

    response = service.query(
        _request(grain_id="manufacturer", concept_ids=("entity_cumulative_revenue_share",))
    )

    rows = response.items[0].rows
    assert [row["entity_id"] for row in rows[:2]] == ["manufacturer_a", "manufacturer_b"]
    assert rows[0]["rank"] == rows[1]["rank"] == 1
    assert rows[0]["tie_count"] == rows[1]["tie_count"] == 2
    assert rows[0]["cumulative_share"] == pytest.approx(200.0 / 450.0)
    assert rows[1]["cumulative_share"] == pytest.approx(400.0 / 450.0)


def test_share_movement_uses_percentage_points_not_relative_percent(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_filters={"category": ("category_a",), "manufacturer": ("manufacturer_a",)},
            concept_ids=("entity_revenue_share",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    row = response.items[0].rows[0]
    assert row["current_share"] == pytest.approx(150.0 / 450.0)
    assert row["reference_share"] == pytest.approx(300.0 / 600.0)
    assert row["share_delta_pp"] == pytest.approx((150.0 / 450.0) - (300.0 / 600.0))
    assert "pct_delta" not in row
    assert response.items[0].provenance is not None
    assert response.items[0].provenance["projection"]["population_scope"]["share_delta_unit"] == "percentage_points"


def test_entity_share_zero_denominator_returns_null_with_limitation(tmp_path) -> None:
    facts = _portfolio_facts().with_columns(
        pl.when(
            (pl.col("metric_concept") == "revenue")
            & (pl.col("grain_id") == "manufacturer")
            & (pl.col("period_start") == date(2026, 1, 1))
        )
        .then(pl.lit(0.0))
        .otherwise(pl.col("value"))
        .alias("value")
    )
    service = _service(tmp_path, facts)

    response = service.query(_request(grain_id="manufacturer", concept_ids=("entity_revenue_share",)))

    assert response.items[0].status == PortfolioConceptStatus.PARTIAL
    assert {row["share"] for row in response.items[0].rows} == {None}
    assert "zero_share_universe_denominator" in response.items[0].limitations


def test_entity_share_range_and_multi_category_scopes_fail_closed(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    range_response = service.query(
        _request(
            grain_id="manufacturer",
            period_mode=PeriodMode.DATE_RANGE,
            concept_ids=("entity_revenue_share",),
        )
    )
    multi_category_response = service.query(
        _request(
            grain_id="manufacturer",
            entity_filters={"category": ("category_a", "category_b")},
            concept_ids=("entity_revenue_share",),
        )
    )

    assert range_response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert range_response.items[0].limitations == ("share_range_semantics_unsupported",)
    assert multi_category_response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert multi_category_response.items[0].limitations == ("portfolio_requires_single_category",)


def test_entity_share_rejects_store_scope_without_denominator_contract(tmp_path) -> None:
    service = _service(tmp_path, _store_scope_portfolio_facts())

    response = service.query(
        _request(
            grain_id="manufacturer",
            entity_filters={"category": ("category_a",), "store": ("store_a",)},
            concept_ids=("entity_revenue_share",),
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("share_scope_filter_unsupported",)


def test_cumulative_share_comparison_fails_closed(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            grain_id="manufacturer",
            concept_ids=("entity_cumulative_revenue_share",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert response.items[0].status == PortfolioConceptStatus.NOT_APPLICABLE
    assert response.items[0].limitations == ("cumulative_share_comparison_semantics_unsupported",)


def test_category_rank_uses_network_universe(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    response = service.query(
        _request(
            concept_ids=("category_rank_revenue",),
            entity_filters=None,
            grain_id="network",
        )
    )

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.READY
    assert [row["entity_id"] for row in item.rows] == ["category_b", "category_a"]
    assert item.rows[0]["ranking_scope"] == "NETWORK"
    assert item.rows[0]["universe_size"] == 2


def test_brand_and_sku_rank_support_approved_additive_bases(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts())

    brand_response = service.query(_request(concept_ids=("brand_rank_margin_abs",)))
    sku_response = service.query(_request(concept_ids=("sku_rank_units",)))

    assert brand_response.items[0].status == PortfolioConceptStatus.READY
    assert brand_response.items[0].rows[0]["entity_id"] == "brand_b"
    assert brand_response.items[0].rows[0]["rank_basis_metric"] == "retailer_margin_abs"
    assert sku_response.items[0].status == PortfolioConceptStatus.READY
    assert sku_response.items[0].rows[0]["entity_type"] == "sku"
    assert sku_response.items[0].rows[0]["universe_size"] == 2


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


def test_active_sku_yoy_exposes_backend_comparison_fields(tmp_path) -> None:
    service = _service(tmp_path, _portfolio_facts(current_active_skus=("sku_a",)))

    response = service.query(
        _request(
            concept_ids=("active_sku_count",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    item = response.items[0]
    assert item.status == PortfolioConceptStatus.READY
    assert item.value == 1
    assert item.current_value == 1
    assert item.reference_value == 2
    assert item.delta == -1
    assert item.pct_delta == pytest.approx(-0.5)
    assert item.rows == (
        {"period_start": date(2025, 1, 1), "value": 2, "source": "backend_active_sku_count"},
        {"period_start": date(2026, 1, 1), "value": 1, "source": "backend_active_sku_count"},
    )
    assert item.provenance["projection"]["reference_period"] == date(2025, 1, 1)


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
                "category",
                "category_b",
                "revenue",
                500.0 if period == date(2026, 1, 1) else 300.0,
                "sum",
                private_label_scope,
                parent_entity_ids={"category": "category_b"},
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
        for brand, margin in (("brand_a", 40.0), ("brand_b", 80.0)):
            rows.append(
                _fact(
                    period,
                    "brand",
                    brand,
                    "retailer_margin_abs",
                    margin if period == date(2026, 1, 1) else margin / 2,
                    "sum",
                    private_label_scope,
                    parent_entity_ids={"category": "category_a", "brand": brand},
                )
            )
    for manufacturer, value in (
        ("manufacturer_a", 300.0),
        ("manufacturer_b", 200.0),
        ("manufacturer_d", 100.0),
    ):
        rows.append(
            _fact(
                date(2025, 1, 1),
                "manufacturer",
                manufacturer,
                "revenue",
                value,
                "sum",
                private_label_scope,
                parent_entity_ids={"category": "category_a", "manufacturer": manufacturer},
            )
        )
    for manufacturer, value in (("manufacturer_a", 150.0), ("manufacturer_b", 250.0), ("manufacturer_c", 50.0)):
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
            rows.append(
                _fact(
                    period,
                    "sku",
                    sku,
                    "revenue",
                    200.0 if sku == "sku_b" else 100.0,
                    "sum",
                    private_label_scope,
                    parent_entity_ids={"category": "category_a", "sku": sku},
                )
            )
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)


def _abc_facts(
    *values: tuple[str, float],
    grain_id: str = "manufacturer",
    concept: str = "revenue",
    private_label_scope: PrivateLabelScope = PrivateLabelScope.ONLY,
) -> pl.DataFrame:
    rows = [
        _fact(
            date(2026, 1, 1),
            grain_id,
            entity_id,
            concept,
            value,
            "sum",
            private_label_scope,
            parent_entity_ids={"category": "category_a", grain_id: entity_id},
        )
        for entity_id, value in values
    ]
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
