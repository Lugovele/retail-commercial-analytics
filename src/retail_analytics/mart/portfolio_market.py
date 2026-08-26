"""Product-safe portfolio and market dashboard route over mart facts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Final, cast

from retail_analytics.mart.metric_facts import RangeAggregationStrategy
from retail_analytics.mart.query import (
    ComparisonMode,
    ComparisonResult,
    DashboardMartQueryService,
    DashboardMetricQueryRequest,
    DashboardMetricQueryResponse,
    MetricQueryResult,
    PeriodMode,
    QualityPolicy,
)
from retail_analytics.mart.scopes import PrivateLabelScope, scope_identity_hash


class PortfolioConceptStatus(StrEnum):
    """Product readiness for one portfolio-market concept in one request."""

    READY = "READY"
    PARTIAL = "PARTIAL"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


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
            elif concept_id in self._RANK_CONCEPTS:
                items.append(self._rank_item(effective_request, concept_id))
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

    def _rank_item(self, request: PortfolioMarketQueryRequest, concept_id: str) -> PortfolioMarketItem:
        rank_grain, metric_concept = self._RANK_CONCEPTS[concept_id]
        if request.period_mode != PeriodMode.SINGLE_PERIOD:
            return _not_applicable(request, concept_id, "category_position", "rank_range_semantics_unsupported")
        unsupported_scope = _rank_unsupported_scope_limitation(request)
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
        if request.period_mode == PeriodMode.DATE_RANGE:
            return _not_applicable(request, concept_id, "assortment", "active_sku_scalar_not_defined_for_range")
        current_period = request.date_from
        if current_period is None:
            return _not_applicable(request, concept_id, "assortment", "active_sku_requires_current_period")
        history_start = request.date_from if request.period_mode == PeriodMode.DATE_RANGE else None
        history_end = request.date_to or request.date_from
        response = self.query_service.query(
            _metric_request(
                request,
                grain_id="sku",
                metric_concepts=("units",),
                comparison_mode=ComparisonMode.NONE,
                entity_ids=(),
                date_from=history_start,
                date_to=history_end,
            )
        )
        counts = _active_sku_counts(response.metric_results)
        current_count = counts.get(current_period, 0)
        peak_period, peak_count = _peak_count(counts)
        change = None if peak_count == 0 else (current_count - peak_count) / peak_count
        values = {
            "active_sku_count": current_count,
            "historical_peak_active_sku_count": peak_count,
            "active_sku_change_pct": change,
        }
        return PortfolioMarketItem(
            concept_id=concept_id,
            status=PortfolioConceptStatus.READY if counts else PortfolioConceptStatus.PARTIAL,
            block_id="assortment",
            grain_id="sku",
            entity_id=None,
            label=None,
            value=values[concept_id] if counts else None,
            unit="percent" if concept_id == "active_sku_change_pct" else "sku_count",
            limitations=() if counts else ("no_sku_units_metric_facts",),
            provenance=_projection_provenance(
                request,
                concept_id=concept_id,
                projection_semantics="sales_based_active_sku_count_against_available_period_peak",
                component_metric_concepts=("units",),
                input_results=response.metric_results,
                population_scope={"scope": "selected_category_or_network", "peak_period": peak_period},
                tie_policy=None,
                evaluated_periods=tuple(sorted(counts)),
            ),
        )

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


def _filter_rank_rows(
    rows: tuple[dict[str, Any], ...],
    *,
    focal_entities: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    if not focal_entities:
        return rows
    allowed = set(focal_entities)
    return tuple(row for row in rows if str(row["entity_id"]) in allowed)


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


def _rank_category_scope(request: PortfolioMarketQueryRequest, rank_grain: str) -> tuple[str | None, str | None]:
    if rank_grain == "category":
        return None, None
    category, category_limitation = _single_category_filter(request)
    if category_limitation:
        return None, category_limitation
    if not category:
        return None, f"{rank_grain}_rank_requires_category_scope"
    return category, None


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


def _rank_unsupported_scope_limitation(request: PortfolioMarketQueryRequest) -> str | None:
    filters = {
        **(request.entity_filters or {}),
        **(request.user_entity_filters or {}),
    }
    unsupported = tuple(
        column for column in ("store", "store_format", "territory", "fo", "fo2", "region") if filters.get(column)
    )
    if unsupported:
        return "rank_scope_filter_unsupported"
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
