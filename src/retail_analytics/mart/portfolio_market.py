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
    _RANK_CONCEPTS: ClassVar[dict[str, str]] = {
        "manufacturer_rank_revenue": "revenue",
        "manufacturer_rank_units": "units",
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
        category = _category_filter(request)
        if not category:
            return _not_applicable(request, concept_id, "category_position", "manufacturer_rank_requires_category_scope")
        metric_concept = self._RANK_CONCEPTS[concept_id]
        response = self.query_service.query(
            _metric_request(
                request,
                grain_id="manufacturer",
                metric_concepts=(metric_concept,),
                comparison_mode=ComparisonMode.NONE,
                entity_ids=(),
                entity_filters={"category": (category,)},
            )
        )
        rows = _rank_rows(response.metric_results, category=category)
        return PortfolioMarketItem(
            concept_id=concept_id,
            status=PortfolioConceptStatus.READY if rows else PortfolioConceptStatus.PARTIAL,
            block_id="category_position",
            grain_id="manufacturer",
            entity_id=None,
            label=None,
            value=None,
            unit="rank",
            rows=rows,
            limitations=() if rows else ("no_manufacturer_metric_facts",),
            provenance=_projection_provenance(
                request,
                concept_id=concept_id,
                projection_semantics="competition_rank_by_summed_additive_metric",
                component_metric_concepts=(metric_concept,),
                input_results=response.metric_results,
                population_scope={"ranking_scope": "CATEGORY", "category": category},
                tie_policy="competition_rank",
                evaluated_periods=tuple(response.available_periods),
            ),
        )

    def _manufacturer_population_item(self, request: PortfolioMarketQueryRequest) -> PortfolioMarketItem:
        category = _category_filter(request)
        if not category:
            return _not_applicable(
                request,
                "manufacturer_population_count",
                "category_position",
                "manufacturer_population_requires_category_scope",
            )
        response = self.query_service.query(
            _metric_request(
                request,
                grain_id="manufacturer",
                metric_concepts=("revenue",),
                comparison_mode=ComparisonMode.NONE,
                entity_ids=(),
                entity_filters={"category": (category,)},
            )
        )
        rows = _rank_rows(response.metric_results, category=category)
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
        category = _category_filter(request)
        brand = _brand_entity(request)
        if not category or not brand:
            return _not_applicable(request, concept_id, "brand_vs_category", "brand_vs_category_requires_category_and_brand")
        brand_response = self.query_service.query(
            _metric_request(
                request,
                grain_id="brand",
                metric_concepts=("revenue",),
                comparison_mode=request.comparison_mode,
                entity_ids=(brand,),
            )
        )
        category_response = self.query_service.query(
            _metric_request(
                request,
                grain_id="category",
                metric_concepts=("revenue",),
                comparison_mode=request.comparison_mode,
                entity_ids=(category,),
                entity_filters={"category": (category,)},
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
                    entity_filters={"category": (category,)},
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
        period_mode=request.period_mode,
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


def _rank_rows(results: tuple[MetricQueryResult, ...], *, category: str | None) -> tuple[dict[str, Any], ...]:
    sorted_results = sorted(results, key=lambda result: (-(result.value or 0), result.entity_id))
    values = [result.value or 0 for result in sorted_results]
    population = len(sorted_results)
    rows: list[dict[str, Any]] = []
    for result in sorted_results:
        value = result.value or 0
        rank = 1 + sum(1 for other in values if other > value)
        rows.append(
            {
                "manufacturer": result.entity_id,
                "metric_value": result.value,
                "rank": rank,
                "population_count": population,
                "tie_count": sum(1 for other in values if other == value),
                "ranking_scope": "CATEGORY",
                "category": category,
                "private_label_scope": result.private_label_scope.value,
            }
        )
    return tuple(rows)


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
        "private_label_scope": request.private_label_scope.value,
        "scope_identity_hash": scope_identity_hash(private_label_scope=request.private_label_scope),
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


def _category_filter(request: PortfolioMarketQueryRequest) -> str | None:
    values = (request.entity_filters or {}).get("category") or ()
    if values:
        return values[0]
    return request.entity_ids[0] if request.grain_id == "category" and request.entity_ids else None


def _brand_entity(request: PortfolioMarketQueryRequest) -> str | None:
    values = (request.entity_filters or {}).get("brand") or ()
    if values:
        return values[0]
    return request.entity_ids[0] if request.grain_id == "brand" and request.entity_ids else None



def _block_for_concept(concept_id: str) -> str:
    if concept_id in {"market_segment_delta_pct", "decline_speed_ratio", "private_label_growth_while_portfolio_declines"}:
        return "market_private_label"
    if concept_id in {"broad_competitors", "direct_peers", "abc"}:
        return "competitors"
    return "portfolio_market"
