"""Product-safe portfolio and market dashboard route over mart facts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Final, cast

import duckdb
import polars as pl

from retail_analytics.mart.metric_facts import RangeAggregationStrategy
from retail_analytics.mart.query import (
    PARENT_ENTITY_JSON_KEYS,
    ComparisonMode,
    ComparisonResult,
    DashboardMartQueryService,
    DashboardMetricQueryRequest,
    DashboardMetricQueryResponse,
    MetricQueryResult,
    PeriodMode,
    QualityPolicy,
    _duckdb_path,
    _reject_duplicate_fact_contributors,
    _reject_source_revision_ambiguity,
)
from retail_analytics.mart.scopes import PrivateLabelScope, scope_identity_hash


class PortfolioConceptStatus(StrEnum):
    """Product readiness for one portfolio-market concept in one request."""

    READY = "READY"
    PARTIAL = "PARTIAL"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


ACTIVE_SKU_FILTER_COLUMNS: Final = {
    "category": "category",
    "manufacturer": "manufacturer",
    "brand": "brand",
    "sku": "canonical_product_id",
    "store": "canonical_store_id",
}
NO_MATCHING_ACTIVE_SKU_FILTER: Final = "__NO_MATCHING_ACTIVE_SKU_FILTER__"


@dataclass(frozen=True)
class PortfolioMarketQueryRequest:
    """Concept-explicit dashboard request for portfolio-market analytics."""

    retailer_id: str
    source_id: str
    date_from: date | None
    date_to: date | None
    period_mode: PeriodMode
    period_grain: str
    grain_id: str
    concept_ids: tuple[str, ...]
    entity_ids: tuple[str, ...] = ()
    entity_filters: dict[str, tuple[str, ...]] | None = None
    user_entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: ComparisonMode = ComparisonMode.NONE
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None
    quality_policy: QualityPolicy = QualityPolicy.INCLUDE_ALL
    include_lineage: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "period_mode", PeriodMode(self.period_mode))
        object.__setattr__(self, "comparison_mode", ComparisonMode(self.comparison_mode))
        object.__setattr__(self, "private_label_scope", PrivateLabelScope(self.private_label_scope))
        object.__setattr__(self, "quality_policy", QualityPolicy(self.quality_policy))


@dataclass(frozen=True)
class PortfolioMarketItem:
    """One product-ready or honestly gated portfolio-market object."""

    concept_id: str
    status: PortfolioConceptStatus
    block_id: str
    grain_id: str | None
    entity_id: str | None
    label: str | None
    value: float | int | str | None
    unit: str | None
    current_value: float | int | None = None
    reference_value: float | int | None = None
    delta: float | None = None
    pct_delta: float | None = None
    numerator_value: float | None = None
    denominator_value: float | None = None
    rows: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = ()
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActiveSkuRollup:
    """Period-level active SKU projection metadata derived without materializing SKU rows."""

    counts: dict[date, int]
    fact_count: int
    source_revision_ids: tuple[str, ...]
    analysis_run_ids: tuple[str, ...]
    metric_definition_ids: tuple[str, ...]
    quality_statuses: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioMarketResponse:
    """Portfolio-market route response."""

    request_scope: dict[str, Any]
    items: tuple[PortfolioMarketItem, ...]
    limitations: tuple[str, ...]
    mart_build_id: str | None
    private_label_scope: PrivateLabelScope


class PortfolioMarketService:
    """Route deterministic portfolio-market analytics through mart facts."""

    _SHARE_CONCEPTS: ClassVar[set[str]] = {
        "category_revenue_share",
        "category_units_share",
        "category_margin_share",
    }
    _RANK_CONCEPTS: ClassVar[dict[str, tuple[str, str]]] = {
        "category_rank_revenue": ("category", "revenue"),
        "category_rank_units": ("category", "units"),
        "category_rank_margin_abs": ("category", "retailer_margin_abs"),
        "manufacturer_rank_revenue": ("manufacturer", "revenue"),
        "manufacturer_rank_units": ("manufacturer", "units"),
        "manufacturer_rank_margin_abs": ("manufacturer", "retailer_margin_abs"),
        "brand_rank_revenue": ("brand", "revenue"),
        "brand_rank_units": ("brand", "units"),
        "brand_rank_margin_abs": ("brand", "retailer_margin_abs"),
        "sku_rank_revenue": ("sku", "revenue"),
        "sku_rank_units": ("sku", "units"),
        "sku_rank_margin_abs": ("sku", "retailer_margin_abs"),
    }
    _SHARE_PROJECTION_CONCEPTS: ClassVar[dict[str, tuple[str, bool]]] = {
        "entity_revenue_share": ("revenue", False),
        "entity_units_share": ("units", False),
        "entity_margin_share": ("retailer_margin_abs", False),
        "entity_cumulative_revenue_share": ("revenue", True),
        "entity_cumulative_units_share": ("units", True),
        "entity_cumulative_margin_share": ("retailer_margin_abs", True),
    }
    _ABC_CONCEPTS: ClassVar[dict[str, tuple[str, str]]] = {
        "manufacturer_abc_revenue": ("manufacturer", "revenue"),
        "manufacturer_abc_units": ("manufacturer", "units"),
        "manufacturer_abc_margin_abs": ("manufacturer", "retailer_margin_abs"),
        "sku_abc_revenue": ("sku", "revenue"),
        "sku_abc_units": ("sku", "units"),
        "sku_abc_margin_abs": ("sku", "retailer_margin_abs"),
    }
    _ACTIVE_SKU_CONCEPTS: ClassVar[set[str]] = {
        "active_sku_count",
        "historical_peak_active_sku_count",
        "active_sku_change_pct",
    }
    _BRAND_CATEGORY_CONCEPTS: ClassVar[set[str]] = {
        "brand_delta_pct",
        "category_delta_pct",
        "brand_category_delta_gap_pp",
    }
    _GATED_CONCEPTS: ClassVar[dict[str, str]] = {
        "market_segment_delta_pct": "market_universe_identity_not_materialized",
        "decline_speed_ratio": "market_universe_identity_not_materialized",
        "private_label_growth_while_portfolio_declines": "signal_feed_route_required",
        "broad_competitors": "broad_competitor_projection_not_route_ready",
        "direct_peers": "direct_peer_flavor_semantics_unresolved",
        "abc": "scope_aware_abc_projection_not_ready",
        "recommendations": "recommendation_backend_not_implemented",
    }

    def __init__(self, query_service: DashboardMartQueryService) -> None:
        self.query_service = query_service
        self.metric_facts_path = Path(query_service.metric_facts_path)

    def query(self, request: PortfolioMarketQueryRequest) -> PortfolioMarketResponse:
        """Return concept-explicit portfolio-market objects."""

        if not request.concept_ids:
            raise ValueError("portfolio-market request requires concept_ids")
        mart_build_id = self.query_service._resolve_build_id(
            DashboardMetricQueryRequest(
                retailer_id=request.retailer_id,
                source_id=request.source_id,
                date_from=request.date_from,
                date_to=request.date_to,
                period_mode=request.period_mode,
                period_grain=request.period_grain,
                grain_id=request.grain_id,
                mart_build_id=request.mart_build_id,
                private_label_scope=request.private_label_scope,
            )
        )
        effective_request = replace(request, mart_build_id=mart_build_id)
        items: list[PortfolioMarketItem] = []
        limitations: list[str] = []
        for concept_id in effective_request.concept_ids:
            if concept_id in self._SHARE_CONCEPTS:
                items.extend(self._share_items(effective_request, concept_id))
            elif concept_id in self._SHARE_PROJECTION_CONCEPTS:
                items.append(self._share_projection_item(effective_request, concept_id))
            elif concept_id in self._RANK_CONCEPTS:
                items.append(self._rank_item(effective_request, concept_id))
            elif concept_id in self._ABC_CONCEPTS:
                items.append(self._abc_item(effective_request, concept_id))
            elif concept_id == "manufacturer_population_count":
                items.append(self._manufacturer_population_item(effective_request))
            elif concept_id in self._ACTIVE_SKU_CONCEPTS:
                items.append(self._active_sku_item(effective_request, concept_id))
            elif concept_id in self._BRAND_CATEGORY_CONCEPTS:
                items.append(self._brand_category_item(effective_request, concept_id))
            elif concept_id in self._GATED_CONCEPTS:
                items.append(self._gated_item(effective_request, concept_id, self._GATED_CONCEPTS[concept_id]))
            else:
                items.append(self._gated_item(effective_request, concept_id, "concept_not_allowlisted"))
        return PortfolioMarketResponse(
            request_scope=_request_scope(effective_request),
            items=tuple(items),
            limitations=tuple(dict.fromkeys(limitations)),
            mart_build_id=mart_build_id,
            private_label_scope=effective_request.private_label_scope,
        )

    def _share_items(self, request: PortfolioMarketQueryRequest, concept_id: str) -> tuple[PortfolioMarketItem, ...]:
        if request.grain_id not in {"manufacturer", "brand", "sku"}:
            return (_not_applicable(request, concept_id, "category_position", "category_share_requires_child_grain"),)
        if request.period_mode == PeriodMode.DATE_RANGE:
            strategy = RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE
        else:
            strategy = None
        response = self.query_service.query(
            _metric_request(
                request,
                grain_id=request.grain_id,
                metric_concepts=(concept_id,),
                comparison_mode=request.comparison_mode,
            )
        )
        items: list[PortfolioMarketItem] = []
        for result in response.metric_results:
            comparison = _comparison_for_result(response, result)
            limitations = (*result.limitations, *tuple(item.issue_code for item in response.limitations))
            comparison_missing = request.comparison_mode != ComparisonMode.NONE and comparison is None
            if comparison_missing:
                limitations = (*limitations, "comparison_period_unavailable")
            status = (
                PortfolioConceptStatus.PARTIAL
                if comparison_missing or result.value is None or limitations
                else PortfolioConceptStatus.READY
            )
            if strategy is not None and result.range_aggregation_strategy != strategy:
                items.append(
                    _not_applicable(
                        request,
                        concept_id,
                        "category_position",
                        "share_range_requires_recompute_share_scope",
                    )
                )
                continue
            items.append(
                PortfolioMarketItem(
                    concept_id=concept_id,
                    status=status,
                    block_id="category_position",
                    grain_id=result.grain_id,
                    entity_id=result.entity_id,
                    label=result.entity_id,
                    value=result.value,
                    unit="percent",
                    current_value=comparison.current_value if comparison is not None else result.value,
                    reference_value=comparison.comparison_value if comparison is not None else None,
                    delta=comparison.delta if comparison is not None else None,
                    pct_delta=comparison.pct_delta if comparison is not None else None,
                    numerator_value=result.numerator_value,
                    denominator_value=result.denominator_value,
                    limitations=tuple(dict.fromkeys(limitations)),
                    provenance=result.provenance.payload if result.provenance is not None else None,
                )
            )
        return tuple(items) or (_not_applicable(request, concept_id, "category_position", "no_metric_fact_result"),)

    def _share_projection_item(self, request: PortfolioMarketQueryRequest, concept_id: str) -> PortfolioMarketItem:
        basis_metric, include_cumulative = self._SHARE_PROJECTION_CONCEPTS[concept_id]
        share_grain = request.grain_id
        if share_grain not in {"category", "manufacturer", "brand", "sku"}:
            return _not_applicable(request, concept_id, "category_position", "share_entity_grain_unsupported")
        if request.period_mode not in {PeriodMode.SINGLE_PERIOD, PeriodMode.AVAILABLE_MONTH_SET}:
            return _not_applicable(request, concept_id, "category_position", "share_range_semantics_unsupported")
        if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET and request.comparison_mode != ComparisonMode.NONE:
            return _not_applicable(
                request,
                concept_id,
                "category_position",
                "available_month_share_movement_not_implemented",
            )
        if include_cumulative and request.comparison_mode != ComparisonMode.NONE:
            return _not_applicable(
                request,
                concept_id,
                "category_position",
                "cumulative_share_comparison_semantics_unsupported",
            )
        unsupported_scope = _scope_filter_unsupported_limitation(request, prefix="share")
        if unsupported_scope:
            return _not_applicable(request, concept_id, "category_position", unsupported_scope)
        category, category_limitation = _share_category_scope(request, share_grain)
        if category_limitation:
            return _not_applicable(request, concept_id, "category_position", category_limitation)
        filters = _rank_universe_filters(share_grain, category)
        current_response = self.query_service.query(
            _metric_request(
                request,
                grain_id=share_grain,
                metric_concepts=(basis_metric,),
                comparison_mode=ComparisonMode.NONE,
                entity_ids=(),
                entity_filters=filters,
            )
        )
        current_rank_rows = _rank_rows(
            current_response.metric_results,
            rank_grain=share_grain,
            metric_concept=basis_metric,
            category=category,
        )
        current_rows = _share_rows(
            current_rank_rows,
            share_grain=share_grain,
            basis_metric=basis_metric,
            category=category,
            include_cumulative=include_cumulative,
        )
        focal_entities = _rank_focal_entities(request, share_grain)
        rows = _filter_rank_rows(current_rows, focal_entities=focal_entities)
        limitations = tuple(item.issue_code for item in current_response.limitations)
        input_results = current_response.metric_results
        evaluated_periods = tuple(current_response.available_periods)
        reference_period: date | None = None
        if request.comparison_mode != ComparisonMode.NONE:
            reference_period, reference_limitations = self._rank_reference_period(
                request,
                rank_grain=share_grain,
                metric_concept=basis_metric,
                entity_filters=filters,
            )
            limitations = (*limitations, *reference_limitations)
            if reference_period is None:
                return _not_applicable(request, concept_id, "category_position", "comparison_period_unavailable")
            reference_response = self.query_service.query(
                _metric_request(
                    request,
                    grain_id=share_grain,
                    metric_concepts=(basis_metric,),
                    comparison_mode=ComparisonMode.NONE,
                    entity_ids=(),
                    entity_filters=filters,
                    date_from=reference_period,
                    date_to=reference_period,
                )
            )
            reference_rank_rows = _rank_rows(
                reference_response.metric_results,
                rank_grain=share_grain,
                metric_concept=basis_metric,
                category=category,
            )
            reference_rows = _share_rows(
                reference_rank_rows,
                share_grain=share_grain,
                basis_metric=basis_metric,
                category=category,
                include_cumulative=False,
            )
            rows = _share_movement_rows(current_rows, reference_rows, focal_entities=focal_entities)
            limitations = (*limitations, *tuple(item.issue_code for item in reference_response.limitations))
            input_results = (*input_results, *reference_response.metric_results)
            evaluated_periods = tuple(dict.fromkeys((*evaluated_periods, *reference_response.available_periods)))
        denominator_zero = any(row.get("share_status") == "ZERO_DENOMINATOR" for row in rows)
        if denominator_zero:
            limitations = (*limitations, "zero_share_universe_denominator")
        if not rows:
            limitations = (*limitations, "no_share_metric_facts")
        status = PortfolioConceptStatus.READY if rows and not limitations else PortfolioConceptStatus.PARTIAL
        universe_total = _share_universe_metric_value(current_rows)
        reference_universe_total = (
            _share_universe_metric_value(rows, key="reference_universe_metric_value")
            if request.comparison_mode != ComparisonMode.NONE
            else None
        )
        return PortfolioMarketItem(
            concept_id=concept_id,
            status=status,
            block_id="category_position",
            grain_id=share_grain,
            entity_id=None,
            label=None,
            value=None,
            unit="percent",
            rows=rows,
            limitations=tuple(dict.fromkeys(limitations)),
            provenance=_projection_provenance(
                request,
                concept_id=concept_id,
                projection_semantics="cumulative_share_after_ranked_additive_metric"
                if include_cumulative
                else "share_of_defined_universe_from_additive_metric",
                component_metric_concepts=(basis_metric,),
                input_results=input_results,
                population_scope={
                    "share_entity_type": share_grain,
                    "share_basis_metric": basis_metric,
                    "universe_type": "selected_category_entities" if category is not None else "network_entities",
                    "universe_value": category if category is not None else "NETWORK",
                    "universe_metric_value": universe_total,
                    "reference_universe_metric_value": reference_universe_total,
                    "universe_size": _rank_universe_size(current_rows),
                    "category": category,
                    "focal_entity_ids": focal_entities,
                    "private_label_scope_applies_to": "numerator_and_denominator",
                    "share_delta_unit": "percentage_points" if request.comparison_mode != ComparisonMode.NONE else None,
                    "sum_to_100_invariant": "complete_mutually_exclusive_universe_only",
                    "calculation_precision": "float64_underlying_metric_values",
                },
                tie_policy="competition_rank" if include_cumulative else None,
                evaluated_periods=evaluated_periods,
                deterministic_secondary_sort="entity_id_ascending" if include_cumulative else None,
                reference_period=reference_period,
            ),
        )

    def _abc_item(self, request: PortfolioMarketQueryRequest, concept_id: str) -> PortfolioMarketItem:
        abc_grain, basis_metric = self._ABC_CONCEPTS[concept_id]
        if request.period_mode not in {PeriodMode.SINGLE_PERIOD, PeriodMode.AVAILABLE_MONTH_SET}:
            return _not_applicable(request, concept_id, "category_position", "abc_range_semantics_unsupported")
        if request.comparison_mode != ComparisonMode.NONE:
            return _not_applicable(request, concept_id, "category_position", "abc_comparison_semantics_unsupported")
        unsupported_scope = _scope_filter_unsupported_limitation(request, prefix="abc")
        if unsupported_scope:
            return _not_applicable(request, concept_id, "category_position", unsupported_scope)
        ownership_universe, ownership_limitation = _abc_ownership_universe(request)
        if ownership_limitation:
            return _not_applicable(request, concept_id, "category_position", ownership_limitation)
        assert ownership_universe is not None
        category, category_limitation = _share_category_scope(request, abc_grain)
        if category_limitation:
            return _not_applicable(request, concept_id, "category_position", category_limitation)
        if not category:
            return _not_applicable(request, concept_id, "category_position", "abc_requires_single_category_scope")
        filters = _rank_universe_filters(abc_grain, category)
        response = self.query_service.query(
            _metric_request(
                request,
                grain_id=abc_grain,
                metric_concepts=(basis_metric,),
                comparison_mode=ComparisonMode.NONE,
                entity_ids=(),
                entity_filters=filters,
            )
        )
        rank_rows = _rank_rows(
            response.metric_results,
            rank_grain=abc_grain,
            metric_concept=basis_metric,
            category=category,
        )
        negative_or_missing = [row for row in rank_rows if cast(float, row["metric_value"]) < 0]
        if negative_or_missing:
            return _not_applicable(
                request,
                concept_id,
                "category_position",
                "abc_negative_contribution_semantics_unsupported",
            )
        share_rows = _share_rows(
            rank_rows,
            share_grain=abc_grain,
            basis_metric=basis_metric,
            category=category,
            include_cumulative=True,
        )
        if not share_rows:
            return _not_applicable(request, concept_id, "category_position", "no_abc_metric_facts")
        universe_total = _share_universe_metric_value(share_rows)
        if universe_total is None or universe_total <= 0:
            return _not_applicable(request, concept_id, "category_position", "abc_positive_universe_required")
        rows = _abc_rows(
            share_rows,
            ownership_universe=ownership_universe,
            period_scope="AVAILABLE_MONTH_YEAR"
            if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET
            else "MONTH",
        )
        focal_entities = _rank_focal_entities(request, abc_grain)
        rows = _filter_rank_rows(rows, focal_entities=focal_entities)
        limitations = tuple(item.issue_code for item in response.limitations)
        if not rows:
            limitations = (*limitations, "no_abc_rows_after_focal_selection")
        return PortfolioMarketItem(
            concept_id=concept_id,
            status=PortfolioConceptStatus.READY if rows and not limitations else PortfolioConceptStatus.PARTIAL,
            block_id="category_position",
            grain_id=abc_grain,
            entity_id=None,
            label=None,
            value=None,
            unit="abc_class",
            rows=rows,
            limitations=tuple(dict.fromkeys(limitations)),
            provenance=_projection_provenance(
                request,
                concept_id=concept_id,
                projection_semantics="abc_classification_from_cumulative_share_projection",
                component_metric_concepts=(basis_metric,),
                input_results=response.metric_results,
                population_scope={
                    "abc_entity_type": abc_grain,
                    "abc_basis_metric": basis_metric,
                    "category": category,
                    "ownership_universe": ownership_universe,
                    "universe_type": "selected_category_entities",
                    "universe_value": category,
                    "universe_metric_value": universe_total,
                    "universe_size": _rank_universe_size(share_rows),
                    "focal_entity_ids": focal_entities,
                    "period_scope": "AVAILABLE_MONTH_YEAR"
                    if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET
                    else "MONTH",
                    "threshold_policy": "first_row_a_else_after_row_cumulative_lte_0_80_a_lte_0_95_b_else_c",
                    "a_cumulative_share_lte": 0.8,
                    "b_cumulative_share_lte": 0.95,
                    "threshold_crossing_policy": "class_by_cumulative_share_after_entity",
                    "zero_value_policy": "zero_value_rows_classified_c_when_universe_total_positive",
                    "negative_value_policy": "fail_closed",
                    "classification_enum": ("A", "B", "C"),
                },
                tie_policy="competition_rank_with_entity_id_secondary_order_may_split_ties",
                evaluated_periods=tuple(response.available_periods),
                deterministic_secondary_sort="entity_id_ascending",
            ),
        )

    def _rank_item(self, request: PortfolioMarketQueryRequest, concept_id: str) -> PortfolioMarketItem:
        rank_grain, metric_concept = self._RANK_CONCEPTS[concept_id]
        if request.period_mode not in {PeriodMode.SINGLE_PERIOD, PeriodMode.AVAILABLE_MONTH_SET}:
            return _not_applicable(request, concept_id, "category_position", "rank_range_semantics_unsupported")
        if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET and request.comparison_mode != ComparisonMode.NONE:
            return _not_applicable(
                request,
                concept_id,
                "category_position",
                "available_month_rank_movement_not_implemented",
            )
        unsupported_scope = _scope_filter_unsupported_limitation(request, prefix="rank")
        if unsupported_scope:
            return _not_applicable(request, concept_id, "category_position", unsupported_scope)
        category, category_limitation = _rank_category_scope(request, rank_grain)
        if category_limitation:
            return _not_applicable(request, concept_id, "category_position", category_limitation)
        filters = _rank_universe_filters(rank_grain, category)
        current_response = self.query_service.query(
            _metric_request(
                request,
                grain_id=rank_grain,
                metric_concepts=(metric_concept,),
                comparison_mode=ComparisonMode.NONE,
                entity_ids=(),
                entity_filters=filters,
            )
        )
        current_rows = _rank_rows(
            current_response.metric_results,
            rank_grain=rank_grain,
            metric_concept=metric_concept,
            category=category,
        )
        focal_entities = _rank_focal_entities(request, rank_grain)
        rows = _filter_rank_rows(current_rows, focal_entities=focal_entities)
        limitations = tuple(item.issue_code for item in current_response.limitations)
        input_results = current_response.metric_results
        evaluated_periods = tuple(current_response.available_periods)
        reference_period: date | None = None
        if request.comparison_mode != ComparisonMode.NONE:
            reference_period, reference_limitations = self._rank_reference_period(
                request,
                rank_grain=rank_grain,
                metric_concept=metric_concept,
                entity_filters=filters,
            )
            limitations = (*limitations, *reference_limitations)
            if reference_period is None:
                return _not_applicable(
                    request,
                    concept_id,
                    "category_position",
                    "comparison_period_unavailable",
                )
            if reference_period is not None:
                reference_response = self.query_service.query(
                    _metric_request(
                        request,
                        grain_id=rank_grain,
                        metric_concepts=(metric_concept,),
                        comparison_mode=ComparisonMode.NONE,
                        entity_ids=(),
                        entity_filters=filters,
                        date_from=reference_period,
                        date_to=reference_period,
                    )
                )
                reference_rows = _rank_rows(
                    reference_response.metric_results,
                    rank_grain=rank_grain,
                    metric_concept=metric_concept,
                    category=category,
                )
                rows = _rank_movement_rows(
                    current_rows,
                    reference_rows,
                    focal_entities=focal_entities,
                )
                limitations = (*limitations, *tuple(item.issue_code for item in reference_response.limitations))
                input_results = (*input_results, *reference_response.metric_results)
                evaluated_periods = tuple(dict.fromkeys((*evaluated_periods, *reference_response.available_periods)))
        status = PortfolioConceptStatus.READY if rows and not limitations else PortfolioConceptStatus.PARTIAL
        return PortfolioMarketItem(
            concept_id=concept_id,
            status=status,
            block_id="category_position",
            grain_id=rank_grain,
            entity_id=None,
            label=None,
            value=None,
            unit="rank",
            rows=rows,
            limitations=tuple(dict.fromkeys(limitations)) if rows else (*tuple(dict.fromkeys(limitations)), "no_rank_metric_facts"),
            provenance=_projection_provenance(
                request,
                concept_id=concept_id,
                projection_semantics="competition_rank_by_summed_additive_metric",
                component_metric_concepts=(metric_concept,),
                input_results=input_results,
                population_scope={
                    "ranking_scope": "CATEGORY" if category is not None else "NETWORK",
                    "ranking_universe_type": "selected_category_entities" if category is not None else "network_entities",
                    "rank_entity_type": rank_grain,
                    "rank_basis_metric": metric_concept,
                    "category": category,
                    "current_universe_size": _rank_universe_size(current_rows),
                    "reference_universe_size": _rank_universe_size(rows, key="reference_universe_size")
                    if request.comparison_mode != ComparisonMode.NONE
                    else None,
                },
                tie_policy="competition_rank",
                evaluated_periods=evaluated_periods,
                deterministic_secondary_sort="entity_id_ascending",
                rank_movement_semantics="reference_rank_minus_current_rank"
                if request.comparison_mode != ComparisonMode.NONE
                else None,
                reference_period=reference_period,
            ),
        )

    def _rank_reference_period(
        self,
        request: PortfolioMarketQueryRequest,
        *,
        rank_grain: str,
        metric_concept: str,
        entity_filters: dict[str, tuple[str, ...]] | None,
    ) -> tuple[date | None, tuple[str, ...]]:
        if request.comparison_mode == ComparisonMode.NONE:
            return None, ()
        if request.date_from is None:
            return None, ("comparison_period_required",)
        history = self.query_service.query(
            _metric_request(
                request,
                grain_id=rank_grain,
                metric_concepts=(metric_concept,),
                comparison_mode=ComparisonMode.NONE,
                entity_ids=(),
                entity_filters=entity_filters,
                date_from=None,
                date_to=request.date_from,
                period_mode=PeriodMode.FULL_AVAILABLE_HISTORY,
            )
        )
        periods = tuple(period for period in history.available_periods if period < request.date_from)
        if request.comparison_mode == ComparisonMode.YOY:
            candidate = date(request.date_from.year - 1, request.date_from.month, request.date_from.day)
            return (candidate, ()) if candidate in periods else (None, ("comparison_period_unavailable",))
        if request.comparison_mode == ComparisonMode.MOM:
            candidate = _add_months(request.date_from, -1)
            return (candidate, ()) if candidate in periods else (None, ("comparison_period_unavailable",))
        if request.comparison_mode == ComparisonMode.PREVIOUS_AVAILABLE:
            return (periods[-1], ()) if periods else (None, ("comparison_period_unavailable",))
        return None, ("rank_comparison_mode_unsupported",)

    def _manufacturer_population_item(self, request: PortfolioMarketQueryRequest) -> PortfolioMarketItem:
        category, category_limitation = _single_category_filter(request)
        if category_limitation:
            return _not_applicable(request, "manufacturer_population_count", "category_position", category_limitation)
        if not category:
            return _not_applicable(
                request,
                "manufacturer_population_count",
                "category_position",
                "manufacturer_population_requires_category_scope",
            )
        filters = _projection_entity_filters(request, category=category)
        response = self.query_service.query(
            _metric_request(
                request,
                grain_id="manufacturer",
                metric_concepts=("revenue",),
                comparison_mode=ComparisonMode.NONE,
                entity_ids=_semantic_entity_filters(request).get("manufacturer", ()),
                entity_filters=filters,
            )
        )
        rows = _rank_rows(
            response.metric_results,
            rank_grain="manufacturer",
            metric_concept="revenue",
            category=category,
        )
        population = len(rows)
        status = PortfolioConceptStatus.READY if rows else PortfolioConceptStatus.PARTIAL
        return PortfolioMarketItem(
            concept_id="manufacturer_population_count",
            status=status,
            block_id="category_position",
            grain_id="manufacturer",
            entity_id=None,
            label=None,
            value=population if status == PortfolioConceptStatus.READY else None,
            unit="count",
            limitations=() if rows else ("no_manufacturer_metric_facts",),
            provenance=_projection_provenance(
                request,
                concept_id="manufacturer_population_count",
                projection_semantics="manufacturer_population_count_in_category_rank_universe",
                component_metric_concepts=("revenue",),
                input_results=response.metric_results,
                population_scope={"ranking_scope": "CATEGORY", "category": category},
                tie_policy="competition_rank",
                evaluated_periods=tuple(response.available_periods),
            ),
        )

    def _active_sku_item(self, request: PortfolioMarketQueryRequest, concept_id: str) -> PortfolioMarketItem:
        if request.period_mode in {PeriodMode.DATE_RANGE, PeriodMode.AVAILABLE_MONTH_SET}:
            return _not_applicable(request, concept_id, "assortment", "active_sku_scalar_not_defined_for_range")
        current_period = request.date_from
        if current_period is None:
            return _not_applicable(request, concept_id, "assortment", "active_sku_requires_current_period")
        history_start = request.date_from if request.period_mode == PeriodMode.DATE_RANGE else None
        history_end = request.date_to or request.date_from
        source_like_rollup = self._active_sku_source_like_rollup(
            request,
            history_start=history_start,
            history_end=history_end,
        )
        entity_filters = self._active_sku_entity_filters(request, history_end=history_end)
        rollup = source_like_rollup or self._active_sku_rollup(
            request,
            entity_filters,
            history_start=history_start,
            history_end=history_end,
        )
        if rollup is None:
            response = self.query_service.query(
                _metric_request(
                    request,
                    grain_id="sku",
                    metric_concepts=("units",),
                    comparison_mode=ComparisonMode.NONE,
                    entity_ids=(),
                    entity_filters=entity_filters,
                    date_from=history_start,
                    date_to=history_end,
                )
            )
            counts = _active_sku_counts(response.metric_results)
            provenance = _projection_provenance(
                request,
                concept_id=concept_id,
                projection_semantics="sales_based_active_sku_count_against_available_period_peak",
                component_metric_concepts=("units",),
                input_results=response.metric_results,
                population_scope={"scope": "selected_category_or_network", "peak_period": None},
                tie_policy=None,
                evaluated_periods=tuple(sorted(counts)),
            )
        else:
            counts = rollup.counts
            provenance = _active_sku_projection_provenance(
                request,
                concept_id=concept_id,
                rollup=rollup,
                evaluated_periods=tuple(sorted(counts)),
            )
        current_count = counts.get(current_period, 0)
        peak_period, peak_count = _peak_count(counts)
        change = None if peak_count == 0 else (current_count - peak_count) / peak_count
        reference_period, reference_limitation = _active_sku_reference_period(
            current_period,
            tuple(sorted(counts)),
            request.comparison_mode,
        )
        reference_count = counts.get(reference_period) if reference_period is not None else None
        delta: int | None = None
        pct_delta: float | None = None
        if reference_count is not None:
            delta = current_count - reference_count
            pct_delta = None if reference_count == 0 else delta / abs(reference_count)
        values = {
            "active_sku_count": current_count,
            "historical_peak_active_sku_count": peak_count,
            "active_sku_change_pct": change,
        }
        rows = tuple(
            {"period_start": period, "value": count, "source": "backend_active_sku_count"}
            for period, count in sorted(counts.items())
        )
        limitations = () if counts else ("no_sku_units_metric_facts",)
        if concept_id == "active_sku_count" and reference_limitation:
            limitations = (*limitations, reference_limitation)
        return PortfolioMarketItem(
            concept_id=concept_id,
            status=PortfolioConceptStatus.READY if counts and not reference_limitation else PortfolioConceptStatus.PARTIAL,
            block_id="assortment",
            grain_id="sku",
            entity_id=None,
            label=None,
            value=values[concept_id] if counts else None,
            unit="percent" if concept_id == "active_sku_change_pct" else "sku_count",
            current_value=current_count if concept_id == "active_sku_count" and counts else None,
            reference_value=reference_count if concept_id == "active_sku_count" else None,
            delta=delta if concept_id == "active_sku_count" else None,
            pct_delta=pct_delta if concept_id == "active_sku_count" else None,
            rows=rows if concept_id == "active_sku_count" else (),
            limitations=limitations,
            provenance=_active_sku_provenance_with_periods(
                provenance,
                peak_period=peak_period,
                reference_period=reference_period,
            ),
        )

    def _active_sku_source_like_rollup(
        self,
        request: PortfolioMarketQueryRequest,
        *,
        history_start: date | None,
        history_end: date | None,
    ) -> ActiveSkuRollup | None:
        semantic_filters = _semantic_entity_filters(request)
        if not semantic_filters.get("store"):
            return None
        if self.query_service.source_like_rows_path is None or not self.query_service.source_like_rows_path.exists():
            return None
        source_like_rows_path = self.query_service.source_like_rows_path
        available_columns = set(pl.read_parquet_schema(source_like_rows_path))
        required_columns = {"retailer_id", "source_id", "period", "canonical_product_id"}
        if not required_columns.issubset(available_columns):
            return None
        frame = pl.scan_parquet(source_like_rows_path).filter(
            (pl.col("retailer_id") == request.retailer_id)
            & (pl.col("source_id") == request.source_id)
            & pl.col("canonical_product_id").is_not_null()
            & (pl.col("canonical_product_id").cast(pl.Utf8) != "")
        )
        source_revision_ids = _active_sku_source_revision_ids(self.query_service.mart_builds, request)
        if source_revision_ids and "source_revision_id" in available_columns:
            frame = frame.filter(
                pl.col("source_revision_id").cast(pl.Utf8).is_in([str(value) for value in source_revision_ids])
            )
        if history_start is not None:
            frame = frame.filter(pl.col("period") >= history_start)
        if history_end is not None:
            frame = frame.filter(pl.col("period") <= history_end)
        if "private_label_flag" in available_columns and request.private_label_scope != PrivateLabelScope.INCLUDE:
            frame = frame.filter(pl.col("private_label_flag") == (request.private_label_scope == PrivateLabelScope.ONLY))
        for key, values in semantic_filters.items():
            if key not in ACTIVE_SKU_FILTER_COLUMNS:
                continue
            column = ACTIVE_SKU_FILTER_COLUMNS[key]
            if column not in available_columns:
                return None
            frame = frame.filter(pl.col(column).cast(pl.Utf8).is_in([str(value) for value in values]))
        if "units" in available_columns:
            frame = frame.filter(pl.col("units").fill_null(0) > 0)
        selected_columns = ["period", "canonical_product_id"]
        if "source_revision_id" in available_columns:
            selected_columns.append("source_revision_id")
        if "analysis_run_id" in available_columns:
            selected_columns.append("analysis_run_id")
        scoped = frame.select(selected_columns).collect()
        if scoped.is_empty():
            return ActiveSkuRollup(
                counts={},
                fact_count=0,
                source_revision_ids=(),
                analysis_run_ids=(),
                metric_definition_ids=(),
                quality_statuses=(),
            )
        count_rows = (
            scoped.group_by("period")
            .agg(pl.col("canonical_product_id").cast(pl.Utf8).n_unique().alias("active_sku_count"))
            .sort("period")
            .iter_rows(named=True)
        )
        source_revision_values = (
            tuple(sorted(str(value) for value in scoped["source_revision_id"].drop_nulls().unique()))
            if "source_revision_id" in scoped.columns
            else source_revision_ids
        )
        analysis_run_values = (
            tuple(sorted(str(value) for value in scoped["analysis_run_id"].drop_nulls().unique()))
            if "analysis_run_id" in scoped.columns
            else ()
        )
        return ActiveSkuRollup(
            counts={row["period"]: int(row["active_sku_count"] or 0) for row in count_rows},
            fact_count=scoped.height,
            source_revision_ids=source_revision_values,
            analysis_run_ids=analysis_run_values,
            metric_definition_ids=(),
            quality_statuses=("valid",),
        )

    def _active_sku_rollup(
        self,
        request: PortfolioMarketQueryRequest,
        entity_filters: dict[str, tuple[str, ...]] | None,
        *,
        history_start: date | None,
        history_end: date | None,
    ) -> ActiveSkuRollup | None:
        if not self.metric_facts_path.exists():
            return None
        facts_have_private_label_scope = self.query_service._facts_have_private_label_scope()
        if request.private_label_scope != PrivateLabelScope.INCLUDE and not facts_have_private_label_scope:
            return ActiveSkuRollup(
                counts={},
                fact_count=0,
                source_revision_ids=(),
                analysis_run_ids=(),
                metric_definition_ids=(),
                quality_statuses=(),
            )
        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "period_grain = ?",
            "mart_build_id = ?",
            "grain_id = ?",
            "metric_concept = ?",
        ]
        params: list[Any] = [
            request.retailer_id,
            request.source_id,
            request.period_grain,
            request.mart_build_id,
            "sku",
            "units",
        ]
        if facts_have_private_label_scope:
            clauses.append("private_label_scope = ?")
            params.append(request.private_label_scope.value)
        if history_start is not None:
            clauses.append("period_start >= CAST(? AS DATE)")
            params.append(history_start.isoformat())
        if history_end is not None:
            clauses.append("period_start <= CAST(? AS DATE)")
            params.append(history_end.isoformat())
        for column, values in (entity_filters or {}).items():
            if column in {"category", "manufacturer", "brand", "sku", "store"}:
                _add_portfolio_parent_filter(clauses, params, column, values)
                continue
            if column not in {"entity_id", "metric_concept", "metric_definition_id", "quality_status"}:
                return None
            _add_portfolio_in_filter(clauses, params, column, values)
        if request.quality_policy == QualityPolicy.VALID_ONLY:
            clauses.append("quality_status = ?")
            params.append("valid")
        selected_columns = [
            "retailer_id",
            "source_id",
            "source_revision_id",
            "analysis_run_id",
            "mart_build_id",
            "period_grain",
            "period_start",
            "period_end",
            "business_period_id",
            "grain_id",
            "entity_id",
            "parent_entity_ids",
            "metric_definition_id",
            "metric_definition_version",
            "metric_config_hash",
            "rule_version",
            "value",
            "quality_status",
        ]
        if facts_have_private_label_scope:
            selected_columns.insert(5, "private_label_scope")
        sql = f"""
            SELECT {", ".join(selected_columns)}
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
            ORDER BY period_start, entity_id, metric_definition_id
        """
        frame = duckdb.sql(sql, params=[_duckdb_path(self.metric_facts_path), *params]).pl()
        metric_request = _metric_request(
            request,
            grain_id="sku",
            metric_concepts=("units",),
            comparison_mode=ComparisonMode.NONE,
            entity_ids=(),
            entity_filters=entity_filters,
            date_from=history_start,
            date_to=history_end,
        )
        self.query_service._validate_active_revision_scope(metric_request, request.mart_build_id or "")
        self.query_service._validate_fact_active_revisions(frame, metric_request)
        _reject_source_revision_ambiguity(frame)
        _reject_duplicate_fact_contributors(frame)
        if frame.is_empty():
            return ActiveSkuRollup(
                counts={},
                fact_count=0,
                source_revision_ids=(),
                analysis_run_ids=(),
                metric_definition_ids=(),
                quality_statuses=(),
            )
        count_rows = (
            frame.group_by("period_start")
            .agg(pl.col("entity_id").filter(pl.col("value") > 0).n_unique().alias("active_sku_count"))
            .sort("period_start")
            .iter_rows(named=True)
        )
        return ActiveSkuRollup(
            counts={row["period_start"]: int(row["active_sku_count"] or 0) for row in count_rows},
            fact_count=frame.height,
            source_revision_ids=tuple(sorted(str(value) for value in frame["source_revision_id"].drop_nulls().unique())),
            analysis_run_ids=tuple(sorted(str(value) for value in frame["analysis_run_id"].drop_nulls().unique())),
            metric_definition_ids=tuple(
                sorted(str(value) for value in frame["metric_definition_id"].drop_nulls().unique())
            ),
            quality_statuses=tuple(sorted(str(value) for value in frame["quality_status"].drop_nulls().unique())),
        )

    def _active_sku_entity_filters(
        self,
        request: PortfolioMarketQueryRequest,
        *,
        history_end: date | None,
    ) -> dict[str, tuple[str, ...]] | None:
        if (request.entity_filters or {}).get("sku"):
            return request.entity_filters
        semantic_filters = _semantic_entity_filters(request)
        if not semantic_filters:
            return request.entity_filters
        resolved_skus = _resolve_active_sku_filter_skus(
            self.query_service.source_like_rows_path,
            request,
            history_end=history_end,
            filters=semantic_filters,
            source_revision_ids=_active_sku_source_revision_ids(self.query_service.mart_builds, request),
        )
        if resolved_skus is None:
            return request.entity_filters
        filters = {
            key: values
            for key, values in (request.entity_filters or {}).items()
            if key not in {"manufacturer", "brand", "sku"} and values
        }
        filters["sku"] = resolved_skus or (NO_MATCHING_ACTIVE_SKU_FILTER,)
        return filters

    def _brand_category_item(self, request: PortfolioMarketQueryRequest, concept_id: str) -> PortfolioMarketItem:
        if request.comparison_mode == ComparisonMode.NONE or request.period_mode != PeriodMode.SINGLE_PERIOD:
            return _not_applicable(request, concept_id, "brand_vs_category", "brand_vs_category_requires_compare_mode")
        category, category_limitation = _single_category_filter(request)
        if category_limitation:
            return _not_applicable(request, concept_id, "brand_vs_category", category_limitation)
        brand, brand_limitation = _single_brand_entity(request)
        if brand_limitation:
            return _not_applicable(request, concept_id, "brand_vs_category", brand_limitation)
        if not category or not brand:
            return _not_applicable(request, concept_id, "brand_vs_category", "brand_vs_category_requires_category_and_brand")
        brand_filters = _projection_entity_filters(request, category=category)
        category_filters = _projection_entity_filters(request, category=category)
        brand_response = self.query_service.query(
            _metric_request(
                request,
                grain_id="brand",
                metric_concepts=("revenue",),
                comparison_mode=request.comparison_mode,
                entity_ids=(brand,),
                entity_filters=brand_filters,
            )
        )
        category_response = self.query_service.query(
            _metric_request(
                request,
                grain_id="category",
                metric_concepts=("revenue",),
                comparison_mode=request.comparison_mode,
                entity_ids=(category,),
                entity_filters=category_filters,
            )
        )
        brand_comparison = brand_response.comparisons[0] if brand_response.comparisons else None
        category_comparison = category_response.comparisons[0] if category_response.comparisons else None
        brand_delta = brand_comparison.pct_delta if brand_comparison is not None else None
        category_delta = category_comparison.pct_delta if category_comparison is not None else None
        gap = None if brand_delta is None or category_delta is None else brand_delta - category_delta
        reference_periods = tuple(
            sorted(
                {
                    comparison.comparison_period_start
                    for comparison in (brand_comparison, category_comparison)
                    if comparison is not None
                }
            )
        )
        reference_results = self._brand_category_reference_results(request, category, brand, reference_periods)
        value = {
            "brand_delta_pct": brand_delta,
            "category_delta_pct": category_delta,
            "brand_category_delta_gap_pp": gap,
        }[concept_id]
        status = PortfolioConceptStatus.READY if value is not None else PortfolioConceptStatus.PARTIAL
        return PortfolioMarketItem(
            concept_id=concept_id,
            status=status,
            block_id="brand_vs_category",
            grain_id="brand",
            entity_id=brand,
            label=brand,
            value=value,
            unit="percentage_points" if concept_id == "brand_category_delta_gap_pp" else "percent",
            limitations=() if status == PortfolioConceptStatus.READY else ("comparison_period_unavailable",),
            provenance=_projection_provenance(
                request,
                concept_id=concept_id,
                projection_semantics="brand_percentage_delta_minus_category_percentage_delta",
                component_metric_concepts=("revenue",),
                input_results=(*brand_response.metric_results, *category_response.metric_results, *reference_results),
                population_scope={"category": category, "brand": brand},
                tie_policy=None,
                evaluated_periods=(*reference_periods, request.date_from) if request.date_from else reference_periods,
            ),
        )

    def _gated_item(self, request: PortfolioMarketQueryRequest, concept_id: str, reason: str) -> PortfolioMarketItem:
        return _not_available(request, concept_id, _block_for_concept(concept_id), reason)

    def _brand_category_reference_results(
        self,
        request: PortfolioMarketQueryRequest,
        category: str,
        brand: str,
        periods: tuple[date, ...],
    ) -> tuple[MetricQueryResult, ...]:
        results: list[MetricQueryResult] = []
        for period in periods:
            brand_response = self.query_service.query(
                _metric_request(
                    request,
                    grain_id="brand",
                    metric_concepts=("revenue",),
                    comparison_mode=ComparisonMode.NONE,
                    entity_ids=(brand,),
                    entity_filters=_projection_entity_filters(request, category=category),
                    date_from=period,
                    date_to=period,
                )
            )
            category_response = self.query_service.query(
                _metric_request(
                    request,
                    grain_id="category",
                    metric_concepts=("revenue",),
                    comparison_mode=ComparisonMode.NONE,
                    entity_ids=(category,),
                    entity_filters=_projection_entity_filters(request, category=category),
                    date_from=period,
                    date_to=period,
                )
            )
            results.extend(brand_response.metric_results)
            results.extend(category_response.metric_results)
        return tuple(results)


_UNSET: Final = object()

def _metric_request(
    request: PortfolioMarketQueryRequest,
    *,
    grain_id: str,
    metric_concepts: tuple[str, ...],
    comparison_mode: ComparisonMode,
    entity_ids: tuple[str, ...] | None = None,
    entity_filters: dict[str, tuple[str, ...]] | None = None,
    period_mode: PeriodMode | None = None,
    date_from: date | None | object = _UNSET,
    date_to: date | None | object = _UNSET,
) -> DashboardMetricQueryRequest:
    actual_date_from = request.date_from if date_from is _UNSET else cast(date | None, date_from)
    actual_date_to = request.date_to if date_to is _UNSET else cast(date | None, date_to)
    return DashboardMetricQueryRequest(
        retailer_id=request.retailer_id,
        source_id=request.source_id,
        date_from=actual_date_from,
        date_to=actual_date_to,
        period_mode=request.period_mode if period_mode is None else period_mode,
        period_grain=request.period_grain,
        grain_id=grain_id,
        entity_ids=request.entity_ids if entity_ids is None else entity_ids,
        entity_filters=request.entity_filters if entity_filters is None else entity_filters,
        metric_concepts=metric_concepts,
        comparison_mode=comparison_mode,
        quality_policy=request.quality_policy,
        include_lineage=request.include_lineage,
        mart_build_id=request.mart_build_id,
        private_label_scope=request.private_label_scope,
    )


def _rank_rows(
    results: tuple[MetricQueryResult, ...],
    *,
    rank_grain: str,
    metric_concept: str,
    category: str | None,
) -> tuple[dict[str, Any], ...]:
    rankable = tuple(result for result in results if result.value is not None)
    sorted_results = sorted(rankable, key=lambda result: (-cast(float, result.value), result.entity_id))
    values = [cast(float, result.value) for result in sorted_results]
    population = len(sorted_results)
    rows: list[dict[str, Any]] = []
    for result in sorted_results:
        value = cast(float, result.value)
        rank = 1 + sum(1 for other in values if other > value)
        row = {
            "entity_id": result.entity_id,
            "entity_type": rank_grain,
            "rank_basis_metric": metric_concept,
            "metric_value": value,
            "rank": rank,
            "universe_size": population,
            "population_count": population,
            "tie_count": sum(1 for other in values if other == value),
            "ranking_scope": "CATEGORY" if category is not None else "NETWORK",
            "ranking_universe_type": "selected_category_entities" if category is not None else "network_entities",
            "category": category,
            "private_label_scope": result.private_label_scope.value,
        }
        if rank_grain == "manufacturer":
            row["manufacturer"] = result.entity_id
        if rank_grain == "brand":
            row["brand"] = result.entity_id
        if rank_grain == "sku":
            row["sku"] = result.entity_id
        rows.append(row)
    return tuple(rows)


def _share_rows(
    rank_rows: tuple[dict[str, Any], ...],
    *,
    share_grain: str,
    basis_metric: str,
    category: str | None,
    include_cumulative: bool,
) -> tuple[dict[str, Any], ...]:
    denominator = sum(cast(float, row["metric_value"]) for row in rank_rows)
    denominator_is_zero = denominator == 0
    running_value = 0.0
    rows: list[dict[str, Any]] = []
    for rank_row in rank_rows:
        metric_value = cast(float, rank_row["metric_value"])
        running_value += metric_value
        share = None if denominator_is_zero else metric_value / denominator
        row = dict(rank_row)
        row.update(
            {
                "share_entity_type": share_grain,
                "basis_metric_id": basis_metric,
                "share_basis_metric": basis_metric,
                "universe_type": "selected_category_entities" if category is not None else "network_entities",
                "universe_value": category if category is not None else "NETWORK",
                "universe_metric_value": denominator,
                "share": share,
                "share_status": "ZERO_DENOMINATOR" if denominator_is_zero else "READY",
            }
        )
        if include_cumulative:
            row.update(
                {
                    "cumulative_metric_value": running_value,
                    "cumulative_share": None if denominator_is_zero else running_value / denominator,
                }
            )
        rows.append(row)
    return tuple(rows)


def _filter_rank_rows(
    rows: tuple[dict[str, Any], ...],
    *,
    focal_entities: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    if not focal_entities:
        return rows
    allowed = set(focal_entities)
    return tuple(row for row in rows if str(row["entity_id"]) in allowed)


def _share_movement_rows(
    current_rows: tuple[dict[str, Any], ...],
    reference_rows: tuple[dict[str, Any], ...],
    *,
    focal_entities: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    current_by_entity = {str(row["entity_id"]): row for row in current_rows}
    reference_by_entity = {str(row["entity_id"]): row for row in reference_rows}
    entity_ids = tuple(sorted(set(current_by_entity) | set(reference_by_entity)))
    movement_rows: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        if focal_entities and entity_id not in focal_entities:
            continue
        current = current_by_entity.get(entity_id)
        reference = reference_by_entity.get(entity_id)
        if current is not None:
            row = dict(current)
        else:
            reference_row = cast(dict[str, Any], reference)
            row = dict(reference_row)
            row.update(
                {
                    "metric_value": None,
                    "rank": None,
                    "share": None,
                    "universe_metric_value": _share_universe_metric_value(current_rows),
                    "share_status": "EXITED_SHARE_UNIVERSE",
                }
            )
        reference_share = cast(float | None, reference.get("share")) if reference is not None else None
        current_share = cast(float | None, current.get("share")) if current is not None else None
        current_value = cast(float | None, current.get("metric_value")) if current is not None else None
        reference_value = cast(float | None, reference.get("metric_value")) if reference is not None else None
        row.update(
            {
                "current_share": current_share,
                "reference_share": reference_share,
                "share_delta_pp": None
                if current_share is None or reference_share is None
                else current_share - reference_share,
                "current_metric_value": current_value,
                "reference_metric_value": reference_value,
                "current_universe_metric_value": _share_universe_metric_value(current_rows),
                "reference_universe_metric_value": _share_universe_metric_value(reference_rows),
                "current_universe_size": _rank_universe_size(current_rows),
                "reference_universe_size": _rank_universe_size(reference_rows),
            }
        )
        if current is None:
            row["share_movement_state"] = "EXITED_SHARE_UNIVERSE"
        elif reference is None:
            row["share_movement_state"] = "NEW_IN_SHARE_UNIVERSE"
        elif row["share_delta_pp"] == 0:
            row["share_movement_state"] = "UNCHANGED"
        else:
            row["share_movement_state"] = "CHANGED"
        movement_rows.append(row)
    return tuple(sorted(movement_rows, key=lambda row: (row["rank"] is None, row["rank"] or 999999, str(row["entity_id"]))))


def _abc_rows(
    share_rows: tuple[dict[str, Any], ...],
    *,
    ownership_universe: str,
    period_scope: str = "MONTH",
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(share_rows):
        cumulative_share = cast(float | None, row.get("cumulative_share"))
        abc_class = _abc_class_for_row(row, position=index)
        abc_row = dict(row)
        abc_row.update(
            {
                "abc_class": abc_class,
                "ownership_universe": ownership_universe,
                "category_scope": row.get("category"),
                "period_scope": period_scope,
                "threshold_policy": "first_row_a_else_after_row_cumulative",
                "threshold_crossing_policy": "class_by_cumulative_share_after_entity",
                "a_cumulative_share_lte": 0.8,
                "b_cumulative_share_lte": 0.95,
                "cumulative_share_for_classification": cumulative_share,
            }
        )
        rows.append(abc_row)
    return tuple(rows)


def _abc_class_for_row(row: dict[str, Any], *, position: int) -> str:
    metric_value = cast(float, row["metric_value"])
    if metric_value == 0:
        return "C"
    if position == 0:
        return "A"
    cumulative_share = cast(float, row["cumulative_share"])
    if cumulative_share <= 0.8:
        return "A"
    if cumulative_share <= 0.95:
        return "B"
    return "C"


def _rank_movement_rows(
    current_rows: tuple[dict[str, Any], ...],
    reference_rows: tuple[dict[str, Any], ...],
    *,
    focal_entities: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    current_by_entity = {str(row["entity_id"]): row for row in current_rows}
    reference_by_entity = {str(row["entity_id"]): row for row in reference_rows}
    entity_ids = tuple(sorted(set(current_by_entity) | set(reference_by_entity)))
    movement_rows: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        if focal_entities and entity_id not in focal_entities:
            continue
        current = current_by_entity.get(entity_id)
        reference = reference_by_entity.get(entity_id)
        if current is not None and reference is not None:
            current_rank = int(current["rank"])
            reference_rank = int(reference["rank"])
            movement = reference_rank - current_rank
            if movement > 0:
                state = "IMPROVED"
            elif movement < 0:
                state = "DECLINED"
            else:
                state = "UNCHANGED"
            row = dict(current)
            row.update(
                {
                    "current_rank": current_rank,
                    "reference_rank": reference_rank,
                    "rank_movement_positions": movement,
                    "rank_movement_state": state,
                    "current_metric_value": current["metric_value"],
                    "reference_metric_value": reference["metric_value"],
                    "current_universe_size": current["universe_size"],
                    "reference_universe_size": reference["universe_size"],
                }
            )
        elif current is not None:
            row = dict(current)
            row.update(
                {
                    "current_rank": current["rank"],
                    "reference_rank": None,
                    "rank_movement_positions": None,
                    "rank_movement_state": "NEW_IN_RANK_UNIVERSE",
                    "current_metric_value": current["metric_value"],
                    "reference_metric_value": None,
                    "current_universe_size": current["universe_size"],
                    "reference_universe_size": _rank_universe_size(reference_rows),
                }
            )
        else:
            reference_row = cast(dict[str, Any], reference)
            row = dict(reference_row)
            row.update(
                {
                    "metric_value": None,
                    "rank": None,
                    "current_rank": None,
                    "reference_rank": reference_row["rank"],
                    "rank_movement_positions": None,
                    "rank_movement_state": "EXITED_RANK_UNIVERSE",
                    "current_metric_value": None,
                    "reference_metric_value": reference_row["metric_value"],
                    "current_universe_size": _rank_universe_size(current_rows),
                    "reference_universe_size": reference_row["universe_size"],
                }
            )
        movement_rows.append(row)
    return tuple(sorted(movement_rows, key=lambda row: (row["rank"] is None, row["rank"] or 999999, str(row["entity_id"]))))


def _rank_universe_size(rows: tuple[dict[str, Any], ...], *, key: str = "universe_size") -> int | None:
    values = {row.get(key) for row in rows if row.get(key) is not None}
    if len(values) == 1:
        value = next(iter(values))
        return int(cast(int | float | str, value))
    return None


def _share_universe_metric_value(rows: tuple[dict[str, Any], ...], *, key: str = "universe_metric_value") -> float | None:
    values = {row.get(key) for row in rows if row.get(key) is not None}
    if len(values) == 1:
        return float(cast(float | int | str, next(iter(values))))
    return None


def _rank_category_scope(request: PortfolioMarketQueryRequest, rank_grain: str) -> tuple[str | None, str | None]:
    if rank_grain == "category":
        return None, None
    category, category_limitation = _single_category_filter(request)
    if category_limitation:
        return None, category_limitation
    if not category:
        return None, f"{rank_grain}_rank_requires_category_scope"
    return category, None


def _share_category_scope(request: PortfolioMarketQueryRequest, share_grain: str) -> tuple[str | None, str | None]:
    if share_grain == "category":
        return None, None
    category, category_limitation = _single_category_filter(request)
    if category_limitation:
        return None, category_limitation
    if not category:
        return None, f"{share_grain}_share_requires_category_scope"
    return category, None


def _abc_ownership_universe(request: PortfolioMarketQueryRequest) -> tuple[str | None, str | None]:
    if request.private_label_scope == PrivateLabelScope.ONLY:
        return "OWN_PORTFOLIO_CATEGORY", None
    if request.private_label_scope == PrivateLabelScope.EXCLUDE:
        return "COMPETITOR_CATEGORY", None
    return None, "abc_ownership_universe_required"


def _rank_universe_filters(rank_grain: str, category: str | None) -> dict[str, tuple[str, ...]] | None:
    if rank_grain == "category":
        return None
    if category is None:
        return None
    return {"category": (category,)}


def _rank_focal_entities(request: PortfolioMarketQueryRequest, rank_grain: str) -> tuple[str, ...]:
    semantic_filters = _semantic_entity_filters(request)
    entities: list[str] = []
    if request.grain_id == rank_grain:
        entities.extend(request.entity_ids)
    entities.extend(semantic_filters.get(rank_grain, ()))
    if rank_grain == "sku":
        entities.extend(semantic_filters.get("canonical_product_id", ()))
    return tuple(dict.fromkeys(entities))


def _scope_filter_unsupported_limitation(request: PortfolioMarketQueryRequest, *, prefix: str) -> str | None:
    filters = {
        **(request.entity_filters or {}),
        **(request.user_entity_filters or {}),
    }
    unsupported = tuple(
        column for column in ("store", "store_format", "territory", "fo", "fo2", "region") if filters.get(column)
    )
    if unsupported:
        return f"{prefix}_scope_filter_unsupported"
    return None


def _comparison_for_result(
    response: DashboardMetricQueryResponse,
    result: MetricQueryResult,
) -> ComparisonResult | None:
    for comparison in response.comparisons:
        same_entity = comparison.entity_id == result.entity_id
        same_definition = result.lineage is None or comparison.metric_definition_id == result.lineage.metric_definition_id
        same_scope = comparison.private_label_scope == result.private_label_scope
        if same_entity and same_definition and same_scope:
            return comparison
    return None


def _active_sku_counts(results: tuple[MetricQueryResult, ...]) -> dict[date, int]:
    active: dict[date, set[str]] = defaultdict(set)
    evaluated_periods: set[date] = set()
    for result in results:
        for period in result.period_values:
            evaluated_periods.add(period.period_start)
            if period.value is not None and period.value > 0:
                active[period.period_start].add(result.entity_id)
    return {period: len(active[period]) for period in evaluated_periods}


def _peak_count(counts: dict[date, int]) -> tuple[date | None, int]:
    if not counts:
        return None, 0
    return min(counts.items(), key=lambda item: (-item[1], item[0]))


def _active_sku_reference_period(
    current_period: date,
    periods: tuple[date, ...],
    comparison_mode: ComparisonMode,
) -> tuple[date | None, str | None]:
    if comparison_mode == ComparisonMode.NONE:
        return None, None
    previous_periods = tuple(period for period in periods if period < current_period)
    if comparison_mode == ComparisonMode.YOY:
        candidate = date(current_period.year - 1, current_period.month, current_period.day)
        return (candidate, None) if candidate in previous_periods else (None, "comparison_period_unavailable")
    if comparison_mode == ComparisonMode.MOM:
        candidate = _add_months(current_period, -1)
        return (candidate, None) if candidate in previous_periods else (None, "comparison_period_unavailable")
    if comparison_mode == ComparisonMode.PREVIOUS_AVAILABLE:
        return (previous_periods[-1], None) if previous_periods else (None, "comparison_period_unavailable")
    return None, "active_sku_comparison_mode_unsupported"


def _projection_provenance(
    request: PortfolioMarketQueryRequest,
    *,
    concept_id: str,
    projection_semantics: str,
    component_metric_concepts: tuple[str, ...],
    input_results: tuple[MetricQueryResult, ...],
    population_scope: dict[str, Any],
    tie_policy: str | None,
    evaluated_periods: tuple[date, ...],
    deterministic_secondary_sort: str | None = None,
    rank_movement_semantics: str | None = None,
    reference_period: date | None = None,
    unsupported_reason: str | None = None,
) -> dict[str, Any]:
    source_revision_ids = tuple(
        sorted({period.source_revision_id for result in input_results for period in result.period_values})
    )
    analysis_run_ids = tuple(
        sorted({period.analysis_run_id for result in input_results for period in result.period_values})
    )
    metric_definition_ids = tuple(
        sorted({result.lineage.metric_definition_id for result in input_results if result.lineage is not None})
    )
    quality_statuses = tuple(
        sorted({period.quality_status for result in input_results for period in result.period_values})
    )
    return {
        "current_analytical_scope": _request_scope(request),
        "projection": {
            "concept_id": concept_id,
            "projection_semantics": projection_semantics,
            "component_metric_concepts": component_metric_concepts,
            "population_scope": population_scope,
            "tie_policy": tie_policy,
            "deterministic_secondary_sort": deterministic_secondary_sort,
            "rank_movement_semantics": rank_movement_semantics,
            "reference_period": reference_period,
            "evaluated_periods": evaluated_periods,
            "unsupported_reason": unsupported_reason,
        },
        "input_metric_facts": {
            "metric_definition_ids": metric_definition_ids,
            "fact_count": sum(len(result.period_values) for result in input_results),
        },
        "run_lineage": {
            "analysis_run_ids": analysis_run_ids,
            "mart_build_id": request.mart_build_id,
            "source_revision_ids": source_revision_ids,
        },
        "source_evidence": {
            "status": "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS",
            "source_row_ids": (),
        },
        "quality": {
            "quality_statuses": quality_statuses,
            "limitations": tuple(
                limitation for result in input_results for limitation in result.limitations
            ),
        },
        "missing_fields": ("source_row_ids",),
    }


def _active_sku_projection_provenance(
    request: PortfolioMarketQueryRequest,
    *,
    concept_id: str,
    rollup: ActiveSkuRollup,
    evaluated_periods: tuple[date, ...],
) -> dict[str, Any]:
    return {
        "current_analytical_scope": _request_scope(request),
        "projection": {
            "concept_id": concept_id,
            "projection_semantics": "sales_based_active_sku_count_against_available_period_peak",
            "component_metric_concepts": ("units",),
            "population_scope": {"scope": "selected_category_or_network", "peak_period": None},
            "tie_policy": None,
            "deterministic_secondary_sort": None,
            "rank_movement_semantics": None,
            "reference_period": None,
            "evaluated_periods": evaluated_periods,
            "unsupported_reason": None,
        },
        "input_metric_facts": {
            "metric_definition_ids": rollup.metric_definition_ids,
            "fact_count": rollup.fact_count,
        },
        "run_lineage": {
            "analysis_run_ids": rollup.analysis_run_ids,
            "mart_build_id": request.mart_build_id,
            "source_revision_ids": rollup.source_revision_ids,
        },
        "source_evidence": {
            "status": "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS",
            "source_row_ids": (),
        },
        "quality": {
            "quality_statuses": rollup.quality_statuses,
            "limitations": (),
        },
        "missing_fields": ("source_row_ids",),
    }


def _active_sku_provenance_with_periods(
    provenance: dict[str, Any],
    *,
    peak_period: date | None,
    reference_period: date | None,
) -> dict[str, Any]:
    projection = dict(provenance.get("projection") or {})
    population_scope = dict(projection.get("population_scope") or {})
    population_scope["peak_period"] = peak_period
    projection["population_scope"] = population_scope
    projection["reference_period"] = reference_period
    return {**provenance, "projection": projection}


def _request_scope(request: PortfolioMarketQueryRequest) -> dict[str, Any]:
    return {
        "retailer_id": request.retailer_id,
        "source_id": request.source_id,
        "period_mode": request.period_mode.value,
        "period_grain": request.period_grain,
        "date_from": request.date_from,
        "date_to": request.date_to,
        "comparison_mode": request.comparison_mode.value,
        "grain_id": request.grain_id,
        "entity_ids": request.entity_ids,
        "entity_filters": request.entity_filters or {},
        "user_entity_filters": request.user_entity_filters or request.entity_filters or {},
        "private_label_scope": request.private_label_scope.value,
        "scope_identity_hash": scope_identity_hash(
            private_label_scope=request.private_label_scope,
            entity_filters=request.entity_filters,
        ),
    }


def _add_portfolio_in_filter(clauses: list[str], params: list[Any], column: str, values: tuple[str, ...]) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    clauses.append(f"{column} IN ({placeholders})")
    params.extend(values)


def _add_portfolio_parent_filter(clauses: list[str], params: list[Any], key: str, values: tuple[str, ...]) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    json_key = PARENT_ENTITY_JSON_KEYS.get(key, key)
    clauses.append(f"json_extract_string(parent_entity_ids, '$.{json_key}') IN ({placeholders})")
    params.extend(values)


def _not_applicable(
    request: PortfolioMarketQueryRequest,
    concept_id: str,
    block_id: str,
    reason: str,
) -> PortfolioMarketItem:
    return PortfolioMarketItem(
        concept_id=concept_id,
        status=PortfolioConceptStatus.NOT_APPLICABLE,
        block_id=block_id,
        grain_id=request.grain_id,
        entity_id=None,
        label=None,
        value=None,
        unit=None,
        limitations=(reason,),
        provenance=_projection_provenance(
            request,
            concept_id=concept_id,
            projection_semantics="not_applicable",
            component_metric_concepts=(),
            input_results=(),
            population_scope={},
            tie_policy=None,
            evaluated_periods=(),
            unsupported_reason=reason,
        ),
    )


def _not_available(
    request: PortfolioMarketQueryRequest,
    concept_id: str,
    block_id: str,
    reason: str,
) -> PortfolioMarketItem:
    item = _not_applicable(request, concept_id, block_id, reason)
    return PortfolioMarketItem(
        concept_id=item.concept_id,
        status=PortfolioConceptStatus.NOT_AVAILABLE,
        block_id=item.block_id,
        grain_id=item.grain_id,
        entity_id=item.entity_id,
        label=item.label,
        value=item.value,
        unit=item.unit,
        limitations=item.limitations,
        provenance=item.provenance,
    )

def _projection_entity_filters(request: PortfolioMarketQueryRequest, *, category: str) -> dict[str, tuple[str, ...]]:
    filters: dict[str, tuple[str, ...]] = {"category": (category,)}
    store_values = (request.entity_filters or {}).get("store") or _semantic_entity_filters(request).get("store") or ()
    if store_values:
        filters["store"] = tuple(store_values)
    return filters

def _category_filter(request: PortfolioMarketQueryRequest) -> str | None:
    values = _semantic_entity_filters(request).get("category") or ()
    if values:
        return values[0]
    return request.entity_ids[0] if request.grain_id == "category" and request.entity_ids else None


def _single_category_filter(request: PortfolioMarketQueryRequest) -> tuple[str | None, str | None]:
    values = _semantic_entity_filters(request).get("category") or ()
    entity_category_values = request.entity_ids if request.grain_id == "category" else ()
    if len(values) > 1 or len(entity_category_values) > 1:
        return None, "portfolio_requires_single_category"
    return _category_filter(request), None


def _brand_entity(request: PortfolioMarketQueryRequest) -> str | None:
    values = _semantic_entity_filters(request).get("brand") or ()
    if values:
        return values[0]
    return request.entity_ids[0] if request.grain_id == "brand" and request.entity_ids else None


def _single_brand_entity(request: PortfolioMarketQueryRequest) -> tuple[str | None, str | None]:
    values = _semantic_entity_filters(request).get("brand") or ()
    if len(values) > 1:
        return None, "brand_vs_category_requires_single_brand"
    return _brand_entity(request), None


def _semantic_entity_filters(request: PortfolioMarketQueryRequest) -> dict[str, tuple[str, ...]]:
    return request.user_entity_filters or request.entity_filters or {}


def _resolve_active_sku_filter_skus(
    source_like_rows_path: Path | None,
    request: PortfolioMarketQueryRequest,
    *,
    history_end: date | None,
    filters: dict[str, tuple[str, ...]],
    source_revision_ids: tuple[str, ...] = (),
) -> tuple[str, ...] | None:
    if source_like_rows_path is None or not source_like_rows_path.exists():
        return None
    selected = {
        key: tuple(value for value in filters.get(key, ()) if value)
        for key in ACTIVE_SKU_FILTER_COLUMNS
        if filters.get(key)
    }
    if not selected:
        return None
    available_columns = set(pl.read_parquet_schema(source_like_rows_path))
    if "canonical_product_id" not in available_columns:
        return None
    frame = pl.scan_parquet(source_like_rows_path).filter(
        (pl.col("retailer_id") == request.retailer_id)
        & (pl.col("source_id") == request.source_id)
        & pl.col("canonical_product_id").is_not_null()
        & (pl.col("canonical_product_id") != "")
    )
    if source_revision_ids and "source_revision_id" in available_columns:
        frame = frame.filter(
            pl.col("source_revision_id").cast(pl.Utf8).is_in([str(value) for value in source_revision_ids])
        )
    if request.date_from is not None and "period" in available_columns:
        frame = frame.filter(pl.col("period") >= request.date_from)
    if history_end is not None and "period" in available_columns:
        frame = frame.filter(pl.col("period") <= history_end)
    if "private_label_flag" in available_columns and request.private_label_scope != PrivateLabelScope.INCLUDE:
        frame = frame.filter(pl.col("private_label_flag") == (request.private_label_scope == PrivateLabelScope.ONLY))
    for key, values in selected.items():
        column = ACTIVE_SKU_FILTER_COLUMNS[key]
        if column not in available_columns:
            return None
        frame = frame.filter(pl.col(column).cast(pl.Utf8).is_in([str(value) for value in values]))
    return tuple(
        str(value)
        for value in frame.select(pl.col("canonical_product_id").cast(pl.Utf8).unique().sort()).collect().to_series()
    )


def _active_sku_source_revision_ids(
    mart_builds: tuple[Any, ...],
    request: PortfolioMarketQueryRequest,
) -> tuple[str, ...]:
    matched = [
        build
        for build in mart_builds
        if build.retailer_id == request.retailer_id
        and request.source_id in build.source_ids
        and (request.mart_build_id is None or build.mart_build_id == request.mart_build_id)
    ]
    if len(matched) != 1:
        return ()
    return tuple(str(value) for value in matched[0].source_revision_ids)


def _block_for_concept(concept_id: str) -> str:
    if concept_id in {"market_segment_delta_pct", "decline_speed_ratio", "private_label_growth_while_portfolio_declines"}:
        return "market_private_label"
    if concept_id in {"broad_competitors", "direct_peers", "abc"}:
        return "competitors"
    return "portfolio_market"


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    import calendar

    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
