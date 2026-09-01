"""Diagnostics dashboard binding over existing Overview analytics contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import polars as pl

from retail_analytics.mart import (
    ComparisonMode,
    DashboardMartQueryService,
    DashboardMetricQueryRequest,
    MartBuildStatus,
    MetricQueryResult,
    PeriodMode,
    PortfolioMarketService,
    PrivateLabelScope,
    QualityPolicy,
)

DIAGNOSTICS_BREAKDOWN_GRAINS: Final = ("category", "manufacturer", "brand", "sku", "store")
DIAGNOSTICS_ENTITY_COLUMNS: Final = {
    "category": "category",
    "manufacturer": "manufacturer",
    "brand": "brand",
    "sku": "canonical_product_id",
    "store": "canonical_store_id",
}
DIAGNOSTICS_LABEL_COLUMNS: Final = {
    "sku": ("sku_name", "canonical_product_id"),
    "store": ("store_display_label", "store_display_name", "store_name", "source_store_id", "canonical_store_id"),
}
DIAGNOSTICS_NETWORK_SAFE_GRAINS: Final = ("network", *DIAGNOSTICS_BREAKDOWN_GRAINS)
DIAGNOSTICS_QUERY_METRIC_SUPPORT: Final = {
    "units": frozenset(DIAGNOSTICS_NETWORK_SAFE_GRAINS),
    "revenue_vat": frozenset(DIAGNOSTICS_NETWORK_SAFE_GRAINS),
    "retailer_margin_abs": frozenset(DIAGNOSTICS_NETWORK_SAFE_GRAINS),
    "retailer_margin_pct": frozenset(DIAGNOSTICS_NETWORK_SAFE_GRAINS),
    "weighted_shelf_price_vat": frozenset(DIAGNOSTICS_NETWORK_SAFE_GRAINS),
    "weighted_input_price_vat": frozenset(DIAGNOSTICS_NETWORK_SAFE_GRAINS),
    "velocity": frozenset({"category", "brand", "sku"}),
    "distribution": frozenset({"category", "brand", "sku"}),
    "weighted_distribution": frozenset({"brand", "sku"}),
    "average_price_per_liter": frozenset({"network", "category", "brand", "sku"}),
}
DIAGNOSTICS_ACTIVE_SKU_SUPPORT: Final = frozenset(DIAGNOSTICS_BREAKDOWN_GRAINS)
DIAGNOSTICS_CONTEXT_METRICS: Final = (
    "units",
    "revenue_vat",
    "average_price_per_liter",
    "velocity",
    "distribution",
    "weighted_distribution",
    "active_sku_count",
)
DIAGNOSTICS_OVERVIEW_KPIS: Final = (
    "units",
    "revenue_vat",
    "retailer_margin_abs",
    "retailer_margin_pct",
    "velocity",
    "distribution",
    "weighted_distribution",
    "active_sku_count",
    "average_price_per_liter",
    "weighted_shelf_price_vat",
    "weighted_input_price_vat",
)
ADDITIVE_DIAGNOSTICS_METRICS: Final = frozenset({"units", "revenue_vat", "retailer_margin_abs"})
DIAGNOSTICS_SOURCE_LIKE_METRICS: Final = frozenset(
    {"velocity", "distribution", "weighted_distribution", "average_price_per_liter"}
)


@dataclass(frozen=True)
class DiagnosticsRequest:
    """UI diagnostics request sharing Overview period and scope semantics."""

    retailer_id: str
    source_id: str
    date_from: date | None
    date_to: date | None
    period_mode: PeriodMode
    period_grain: str
    selected_metric: str
    breakdown_grain: str
    summary_grain: str
    summary_entity_ids: tuple[str, ...] = ()
    metric_concepts: tuple[str, ...] = DIAGNOSTICS_OVERVIEW_KPIS
    entity_filters: dict[str, tuple[str, ...]] | None = None
    user_entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: ComparisonMode = ComparisonMode.NONE
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None
    quality_policy: QualityPolicy = QualityPolicy.INCLUDE_ALL
    limit: int = 200

    def __post_init__(self) -> None:
        object.__setattr__(self, "period_mode", PeriodMode(self.period_mode))
        object.__setattr__(self, "comparison_mode", ComparisonMode(self.comparison_mode))
        object.__setattr__(self, "private_label_scope", PrivateLabelScope(self.private_label_scope))
        object.__setattr__(self, "quality_policy", QualityPolicy(self.quality_policy))
        object.__setattr__(self, "limit", max(1, min(int(self.limit), 500)))


class DiagnosticsService:
    """Build Diagnostics rows from the same query and portfolio truth used by Overview."""

    def __init__(
        self,
        query_service: DashboardMartQueryService,
        portfolio_service: PortfolioMarketService,
        *,
        source_like_rows_path: str | Path | None = None,
    ) -> None:
        self.query_service = query_service
        self.portfolio_service = portfolio_service
        self.source_like_rows_path = Path(source_like_rows_path) if source_like_rows_path is not None else query_service.source_like_rows_path

    def query(self, request: DiagnosticsRequest) -> dict[str, Any]:
        if request.breakdown_grain not in DIAGNOSTICS_BREAKDOWN_GRAINS:
            raise ValueError(f"Unsupported diagnostics breakdown grain: {request.breakdown_grain}")
        entity_options = self._entities(request)
        entity_ids = tuple(item["stable_entity_id"] for item in entity_options)
        query_concepts = tuple(
            concept
            for concept in request.metric_concepts
            if concept not in DIAGNOSTICS_SOURCE_LIKE_METRICS
            and concept != "active_sku_count"
            and _metric_supported(concept, request.breakdown_grain)
        )
        query_response = (
            self.query_service.query(
                _query_request(
                    request,
                    grain_id=request.breakdown_grain,
                    entity_ids=entity_ids,
                    metric_concepts=query_concepts,
                )
            )
            if entity_ids and query_concepts
            else None
        )
        summary_query_concepts = tuple(
            concept
            for concept in request.metric_concepts
            if concept != "active_sku_count" and _metric_supported(concept, request.summary_grain)
        )
        summary_query_response = (
            self.query_service.query(
                _query_request(
                    request,
                    grain_id=request.summary_grain,
                    entity_ids=request.summary_entity_ids,
                    metric_concepts=summary_query_concepts,
                )
            )
            if request.summary_entity_ids and summary_query_concepts
            else None
        )
        active_sku_by_entity = self._active_sku_by_entity(request, entity_ids)
        source_like_by_entity = self._source_like_kpis_by_entity(request, entity_ids)
        summary_active_sku = self._summary_active_sku(request)
        entities = [
            _entity_payload(
                option,
                request,
                query_response=query_response,
                diagnostics_metrics={
                    **source_like_by_entity.get(option["stable_entity_id"], {}),
                    **(
                        {"active_sku_count": active_sku_by_entity[option["stable_entity_id"]]}
                        if option["stable_entity_id"] in active_sku_by_entity
                        else {}
                    ),
                },
            )
            for option in entity_options
        ]
        summary_metrics = _metrics_payload(
            request,
            request.summary_grain,
            request.summary_entity_ids[0] if request.summary_entity_ids else None,
            summary_query_response,
            {"active_sku_count": summary_active_sku} if summary_active_sku else {},
        )
        return {
            "selected_metric": request.selected_metric,
            "breakdown_level": request.breakdown_grain,
            "summary_grain": request.summary_grain,
            "request_scope": {
                "retailer_id": request.retailer_id,
                "source_id": request.source_id,
                "period_mode": request.period_mode.value,
                "comparison_mode": request.comparison_mode.value,
                "date_from": request.date_from.isoformat() if request.date_from else None,
                "date_to": request.date_to.isoformat() if request.date_to else None,
                "entity_filters": _json_filters(request.entity_filters),
                "user_entity_filters": _json_filters(request.user_entity_filters),
                "private_label_scope": request.private_label_scope.value,
            },
            "summary": {
                "entity_id": request.summary_entity_ids[0] if request.summary_entity_ids else None,
                "metrics": summary_metrics,
            },
            "entities": entities,
            "entity_count": len(entities),
            "support_matrix": _support_matrix(),
            "limitations": _response_limitations(entity_options, request),
        }

    def _entities(self, request: DiagnosticsRequest) -> tuple[dict[str, Any], ...]:
        path = self.source_like_rows_path
        if path is None or not path.exists():
            return ()
        available = set(pl.read_parquet_schema(path))
        entity_column = DIAGNOSTICS_ENTITY_COLUMNS[request.breakdown_grain]
        if entity_column not in available:
            return ()
        label_column = _label_column(request.breakdown_grain, entity_column, available)
        frame = _source_frame(path, request, available, source_revision_ids=self._source_revision_ids(request))
        frame = _apply_semantic_filters(frame, request, available)
        selected = [entity_column]
        if label_column != entity_column:
            selected.append(label_column)
        for column in ("package", "volume_l", "brand", "manufacturer"):
            if request.breakdown_grain == "sku" and column in available and column not in selected:
                selected.append(column)
        label_expr = (
            pl.col(label_column)
            .cast(pl.Utf8)
            .str.strip_chars()
            .filter(pl.col(label_column).is_not_null())
            .first()
            .alias("display_label")
            if label_column != entity_column
            else pl.col(entity_column).cast(pl.Utf8).first().alias("display_label")
        )
        rows = (
            frame.filter(pl.col(entity_column).is_not_null() & (pl.col(entity_column).cast(pl.Utf8) != ""))
            .select(selected)
            .group_by(entity_column)
            .agg(
                label_expr,
                *[
                    pl.col(column).cast(pl.Utf8).str.strip_chars().filter(pl.col(column).is_not_null()).first().alias(column)
                    for column in selected
                    if column not in {entity_column, label_column}
                ],
            )
            .collect()
            .to_dicts()
        )
        options = _entity_options_from_rows(request.breakdown_grain, entity_column, rows)
        return tuple(options[: request.limit])

    def _active_sku_by_entity(
        self,
        request: DiagnosticsRequest,
        entity_ids: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        if not entity_ids or request.breakdown_grain not in DIAGNOSTICS_ACTIVE_SKU_SUPPORT:
            return {}
        if request.period_mode != PeriodMode.SINGLE_PERIOD:
            return {
                entity_id: _unsupported_period_metric("active_sku_count", request.period_mode)
                for entity_id in entity_ids
            }
        path = self.source_like_rows_path
        if path is None or not path.exists():
            return {}
        available = set(pl.read_parquet_schema(path))
        entity_column = DIAGNOSTICS_ENTITY_COLUMNS[request.breakdown_grain]
        if entity_column not in available or "canonical_product_id" not in available:
            return {}
        frame = _source_frame(path, request, available, source_revision_ids=self._source_revision_ids(request))
        frame = _apply_semantic_filters(frame, request, available)
        if "units" in available:
            frame = frame.filter(pl.col("units").fill_null(0) > 0)
        selected_columns = ["period", entity_column]
        if "canonical_product_id" not in selected_columns:
            selected_columns.append("canonical_product_id")
        scoped = (
            frame.filter(pl.col(entity_column).cast(pl.Utf8).is_in(list(entity_ids)))
            .select(selected_columns)
            .collect()
        )
        if scoped.is_empty():
            return {}
        rows = (
            scoped.group_by([entity_column, "period"])
            .agg(pl.col("canonical_product_id").cast(pl.Utf8).n_unique().alias("value"))
            .to_dicts()
        )
        return _period_metric_payloads_by_entity(rows, entity_column, request, "sku_count")

    def _source_like_kpis_by_entity(
        self,
        request: DiagnosticsRequest,
        entity_ids: tuple[str, ...],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        concepts = tuple(
            concept
            for concept in request.metric_concepts
            if concept in DIAGNOSTICS_SOURCE_LIKE_METRICS and _metric_supported(concept, request.breakdown_grain)
        )
        if not concepts or not entity_ids:
            return {}
        if request.period_mode != PeriodMode.SINGLE_PERIOD:
            return {
                entity_id: {
                    concept: _unsupported_period_metric(concept, request.period_mode)
                    for concept in concepts
                }
                for entity_id in entity_ids
            }
        path = self.source_like_rows_path
        if path is None or not path.exists():
            return {}
        available = set(pl.read_parquet_schema(path))
        entity_column = DIAGNOSTICS_ENTITY_COLUMNS[request.breakdown_grain]
        required = {"period", "category", "canonical_store_id", "units", "revenue_vat", entity_column}
        if not required.issubset(available):
            return {}

        base_source = _source_frame(
            path,
            request,
            available,
            source_revision_ids=self._source_revision_ids(request),
        ).collect()
        scoped = _apply_semantic_filters(base_source.lazy(), request, available).collect()
        scoped = scoped.filter(pl.col(entity_column).cast(pl.Utf8).is_in(list(entity_ids)))
        if scoped.is_empty():
            return {}

        active_universe = _active_store_universe_by_period(base_source)
        rows: dict[str, dict[str, dict[date, tuple[float | None, float | None]]]] = {}
        for period in sorted(scoped.get_column("period").drop_nulls().unique().to_list()):
            period_source = base_source.filter(pl.col("period") == period)
            period_scoped = scoped.filter(pl.col("period") == period)
            for entity_id in sorted(period_scoped.get_column(entity_column).drop_nulls().unique().to_list()):
                entity_rows = period_scoped.filter(pl.col(entity_column).cast(pl.Utf8) == str(entity_id))
                for concept in concepts:
                    rows.setdefault(str(entity_id), {}).setdefault(concept, {})[period] = (
                        _source_like_components_for_concept(
                            concept,
                            entity_rows,
                            period_source,
                            active_universe.get(period, 0.0),
                        )
                    )
        return _source_like_metric_payloads_by_entity(rows, request)

    def _summary_active_sku(self, request: DiagnosticsRequest) -> dict[str, Any]:
        if "active_sku_count" not in request.metric_concepts:
            return {}
        if request.period_mode != PeriodMode.SINGLE_PERIOD:
            return _unsupported_period_metric("active_sku_count", request.period_mode)
        path = self.source_like_rows_path
        if path is None or not path.exists():
            return {}
        available = set(pl.read_parquet_schema(path))
        if "canonical_product_id" not in available:
            return {}
        frame = _source_frame(path, request, available, source_revision_ids=self._source_revision_ids(request))
        frame = _apply_semantic_filters(frame, request, available)
        summary_column = DIAGNOSTICS_ENTITY_COLUMNS.get(request.summary_grain)
        if summary_column and summary_column in available and request.summary_entity_ids:
            frame = frame.filter(pl.col(summary_column).cast(pl.Utf8).is_in(list(request.summary_entity_ids)))
        if "units" in available:
            frame = frame.filter(pl.col("units").fill_null(0) > 0)
        rows = (
            frame.select(["period", "canonical_product_id"])
            .collect()
            .group_by("period")
            .agg(pl.col("canonical_product_id").cast(pl.Utf8).n_unique().alias("value"))
            .to_dicts()
        )
        if not rows:
            return {}
        return _period_summary_metric_payload(rows, request, "sku_count")

    def _source_revision_ids(self, request: DiagnosticsRequest) -> tuple[str, ...]:
        matching = tuple(
            build
            for build in self.query_service.mart_builds
            if build.retailer_id == request.retailer_id and request.source_id in build.source_ids
            and build.status == MartBuildStatus.APPROVED
        )
        if request.mart_build_id:
            for build in matching:
                if build.mart_build_id == request.mart_build_id:
                    return tuple(sorted(build.source_revision_ids))
            return ()
        if len(matching) == 1:
            return tuple(sorted(matching[0].source_revision_ids))
        return ()


def build_diagnostics_request(payload: dict[str, Any]) -> DiagnosticsRequest:
    raw_filters = payload.get("entity_filters")
    raw_user_filters = payload.get("user_entity_filters")
    return DiagnosticsRequest(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        date_from=_date_or_none(payload.get("date_from")),
        date_to=_date_or_none(payload.get("date_to")),
        period_mode=PeriodMode(payload.get("period_mode", PeriodMode.SINGLE_PERIOD)),
        period_grain=str(payload.get("period_grain", "month")),
        selected_metric=str(payload.get("selected_metric", "units")),
        breakdown_grain=str(payload.get("breakdown_grain", "category")),
        summary_grain=str(payload.get("summary_grain", "network")),
        summary_entity_ids=tuple(str(item) for item in payload.get("summary_entity_ids", ())),
        metric_concepts=tuple(str(item) for item in payload.get("metric_concepts", DIAGNOSTICS_OVERVIEW_KPIS)),
        entity_filters=_filters(raw_filters),
        user_entity_filters=_filters(raw_user_filters) or _filters(raw_filters),
        comparison_mode=ComparisonMode(payload.get("comparison_mode", ComparisonMode.NONE)),
        private_label_scope=PrivateLabelScope(payload.get("private_label_scope", PrivateLabelScope.INCLUDE)),
        mart_build_id=payload.get("mart_build_id"),
        quality_policy=QualityPolicy(payload.get("quality_policy", QualityPolicy.INCLUDE_ALL)),
        limit=int(payload.get("limit", 200)),
    )


def _query_request(
    request: DiagnosticsRequest,
    *,
    grain_id: str,
    entity_ids: tuple[str, ...],
    metric_concepts: tuple[str, ...],
) -> DashboardMetricQueryRequest:
    return DashboardMetricQueryRequest(
        retailer_id=request.retailer_id,
        source_id=request.source_id,
        date_from=request.date_from,
        date_to=request.date_to,
        period_mode=request.period_mode,
        period_grain=request.period_grain,
        grain_id=grain_id,
        entity_ids=entity_ids,
        entity_filters=request.entity_filters,
        user_entity_filters=request.user_entity_filters,
        metric_concepts=metric_concepts,
        comparison_mode=request.comparison_mode,
        quality_policy=request.quality_policy,
        mart_build_id=request.mart_build_id,
        private_label_scope=request.private_label_scope,
    )


def _source_frame(
    path: Path,
    request: DiagnosticsRequest,
    available: set[str],
    *,
    source_revision_ids: tuple[str, ...],
) -> pl.LazyFrame:
    frame = pl.scan_parquet(path).filter((pl.col("retailer_id") == request.retailer_id) & (pl.col("source_id") == request.source_id))
    if "source_revision_id" in available and source_revision_ids:
        frame = frame.filter(pl.col("source_revision_id").cast(pl.Utf8).is_in(list(source_revision_ids)))
    if "private_label_flag" in available and request.private_label_scope == PrivateLabelScope.ONLY:
        frame = frame.filter(pl.col("private_label_flag") == True)
    elif "private_label_flag" in available and request.private_label_scope == PrivateLabelScope.EXCLUDE:
        frame = frame.filter((pl.col("private_label_flag") == False) | pl.col("private_label_flag").is_null())
    periods = _diagnostics_periods(request)
    if periods:
        frame = frame.filter(pl.col("period").is_in(list(periods)))
    elif request.date_from is not None:
        frame = frame.filter(pl.col("period") >= request.date_from)
        if request.date_to is not None:
            frame = frame.filter(pl.col("period") <= request.date_to)
    return frame


def _apply_semantic_filters(
    frame: pl.LazyFrame,
    request: DiagnosticsRequest,
    available: set[str],
) -> pl.LazyFrame:
    for key, values in _semantic_filters(request).items():
        column = DIAGNOSTICS_ENTITY_COLUMNS.get(key)
        if not column or column not in available:
            continue
        frame = frame.filter(pl.col(column).cast(pl.Utf8).is_in([str(value) for value in values]))
    return frame


def _diagnostics_periods(request: DiagnosticsRequest) -> tuple[date, ...]:
    if request.date_from is None:
        return ()
    if request.period_mode == PeriodMode.SINGLE_PERIOD:
        periods = [request.date_from]
        if request.comparison_mode == ComparisonMode.YOY:
            periods.append(date(request.date_from.year - 1, request.date_from.month, request.date_from.day))
        elif request.comparison_mode == ComparisonMode.MOM:
            periods.append(
                date(request.date_from.year - 1, 12, request.date_from.day)
                if request.date_from.month == 1
                else date(request.date_from.year, request.date_from.month - 1, request.date_from.day)
            )
        return tuple(dict.fromkeys(periods))
    return ()


def _entity_payload(
    option: dict[str, Any],
    request: DiagnosticsRequest,
    *,
    query_response: Any,
    diagnostics_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entity_id = str(option["stable_entity_id"])
    metrics = _metrics_payload(request, request.breakdown_grain, entity_id, query_response, diagnostics_metrics)
    selected_metric = metrics.get(request.selected_metric) or _unsupported_metric(request.selected_metric)
    return {
        "stable_entity_id": entity_id,
        "display_label": option["display_label"],
        "secondary_label": option.get("secondary_label"),
        "metrics": metrics,
        "selected_metric": selected_metric,
        "current_value": selected_metric.get("current_value"),
        "reference_value": selected_metric.get("reference_value"),
        "delta_value": selected_metric.get("delta_value"),
        "analysis_value": selected_metric.get("delta_value"),
        "analysis_format": selected_metric.get("delta_format"),
        "status": selected_metric.get("status"),
        "reason": selected_metric.get("reason"),
    }


def _metrics_payload(
    request: DiagnosticsRequest,
    grain_id: str,
    entity_id: str | None,
    query_response: Any,
    diagnostics_metrics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for concept in request.metric_concepts:
        if concept in diagnostics_metrics:
            payload[concept] = diagnostics_metrics[concept]
            continue
        if concept == "active_sku_count":
            payload[concept] = (
                _unsupported_metric(concept)
                if grain_id not in DIAGNOSTICS_ACTIVE_SKU_SUPPORT
                else _no_data_metric(concept, "no_active_sku_rows")
            )
            continue
        if not _metric_supported(concept, grain_id):
            payload[concept] = _unsupported_metric(concept)
            continue
        result = _result_for(query_response, concept, entity_id)
        if result is None:
            payload[concept] = _no_data_metric(concept, "no_metric_result")
            continue
        comparison = _comparison_for(query_response, result)
        payload[concept] = {
            "status": "READY" if comparison else "PARTIAL",
            "current_value": result.value,
            "reference_value": comparison.get("comparison_value") if comparison else None,
            "delta_value": comparison.get("delta") if comparison else None,
            "pct_delta": comparison.get("pct_delta") if comparison else None,
            "numerator_value": result.numerator_value,
            "denominator_value": result.denominator_value,
            "format": _format_for(result),
            "delta_format": _delta_format_for(result),
            "reason": None if comparison else "comparison_unavailable",
        }
    return payload


def _result_for(response: Any, concept: str, entity_id: str | None) -> MetricQueryResult | None:
    if response is None or entity_id is None:
        return None
    for result in response.metric_results:
        if result.metric_concept == concept and result.entity_id == entity_id:
            return result
    return None


def _comparison_for(response: Any, result: MetricQueryResult) -> dict[str, Any] | None:
    if response is None or result.lineage is None:
        return None
    for comparison in response.comparisons:
        if comparison.entity_id == result.entity_id and comparison.metric_definition_id == result.lineage.metric_definition_id:
            return {
                "comparison_value": comparison.comparison_value,
                "delta": comparison.delta,
                "pct_delta": comparison.pct_delta,
            }
    return None


def _source_like_metric_payloads_by_entity(
    rows: dict[str, dict[str, dict[date, tuple[float | None, float | None]]]],
    request: DiagnosticsRequest,
) -> dict[str, dict[str, dict[str, Any]]]:
    current_period = request.date_from
    reference_period = None
    if current_period is not None and request.comparison_mode == ComparisonMode.YOY:
        reference_period = date(current_period.year - 1, current_period.month, current_period.day)
    elif current_period is not None and request.comparison_mode == ComparisonMode.MOM:
        reference_period = (
            date(current_period.year - 1, 12, current_period.day)
            if current_period.month == 1
            else date(current_period.year, current_period.month - 1, current_period.day)
        )
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for entity_id, metrics in rows.items():
        result[entity_id] = {}
        for concept, period_components in metrics.items():
            current_components = period_components.get(current_period) if current_period is not None else None
            reference_components = period_components.get(reference_period) if reference_period is not None else None
            current_value = _ratio_value(current_components)
            reference_value = _ratio_value(reference_components)
            delta_value = (
                current_value - reference_value
                if current_value is not None and reference_value is not None
                else None
            )
            result[entity_id][concept] = {
                "status": "READY" if current_value is not None and reference_value is not None else "PARTIAL",
                "current_value": current_value,
                "reference_value": reference_value,
                "delta_value": delta_value,
                "pct_delta": (
                    delta_value / reference_value
                    if delta_value is not None and reference_value not in (None, 0)
                    else None
                ),
                "numerator_value": current_components[0] if current_components is not None else None,
                "denominator_value": current_components[1] if current_components is not None else None,
                "format": _format_for_concept(concept),
                "delta_format": _delta_format_for_concept(concept),
                "reason": None if current_value is not None else "no_metric_result",
            }
    return result


def _period_metric_payloads_by_entity(
    rows: list[dict[str, Any]],
    entity_column: str,
    request: DiagnosticsRequest,
    value_format: str,
) -> dict[str, dict[str, Any]]:
    by_entity: dict[str, dict[date, int]] = {}
    for row in rows:
        entity_id = str(row[entity_column])
        by_entity.setdefault(entity_id, {})[row["period"]] = int(row["value"] or 0)
    current_period = request.date_from
    reference_period = None
    if current_period is not None and request.comparison_mode == ComparisonMode.YOY:
        reference_period = date(current_period.year - 1, current_period.month, current_period.day)
    result: dict[str, dict[str, Any]] = {}
    for entity_id, counts in by_entity.items():
        current_value = counts.get(current_period, 0) if current_period is not None else None
        reference_value = counts.get(reference_period) if reference_period is not None else None
        delta_value = current_value - reference_value if current_value is not None and reference_value is not None else None
        result[entity_id] = {
            "status": "READY" if current_value is not None and reference_value is not None else "PARTIAL",
            "current_value": current_value,
            "reference_value": reference_value,
            "delta_value": delta_value,
            "format": value_format,
            "delta_format": value_format,
            "reason": None if current_value is not None else "no_current_active_sku_rows",
        }
    return result


def _period_summary_metric_payload(
    rows: list[dict[str, Any]],
    request: DiagnosticsRequest,
    value_format: str,
) -> dict[str, Any]:
    by_period = {row["period"]: int(row["value"] or 0) for row in rows}
    current_period = request.date_from
    reference_period = None
    if current_period is not None and request.comparison_mode == ComparisonMode.YOY:
        reference_period = date(current_period.year - 1, current_period.month, current_period.day)
    elif current_period is not None and request.comparison_mode == ComparisonMode.MOM:
        reference_period = (
            date(current_period.year - 1, 12, current_period.day)
            if current_period.month == 1
            else date(current_period.year, current_period.month - 1, current_period.day)
        )
    current_value = by_period.get(current_period) if current_period is not None else None
    reference_value = by_period.get(reference_period) if reference_period is not None else None
    delta_value = (
        current_value - reference_value
        if current_value is not None and reference_value is not None
        else None
    )
    return {
        "status": "READY" if current_value is not None and reference_value is not None else "PARTIAL",
        "current_value": current_value,
        "reference_value": reference_value,
        "delta_value": delta_value,
        "format": value_format,
        "delta_format": value_format,
        "reason": None if current_value is not None else "no_current_active_sku_rows",
    }


def _source_like_components_for_concept(
    concept: str,
    entity_rows: pl.DataFrame,
    period_source: pl.DataFrame,
    active_store_universe: float,
) -> tuple[float | None, float | None]:
    if concept == "velocity":
        return _sum(entity_rows, "units"), _distinct_active_stores(entity_rows)
    if concept == "distribution":
        return _distinct_active_stores(entity_rows), active_store_universe
    if concept == "weighted_distribution":
        categories = [str(value) for value in entity_rows.get_column("category").drop_nulls().unique().to_list()]
        if len(categories) != 1:
            return None, None
        category_rows = period_source.filter(pl.col("category").cast(pl.Utf8) == categories[0])
        active_stores = [
            str(value)
            for value in entity_rows.filter((pl.col("units") > 0) & pl.col("canonical_store_id").is_not_null())
            .get_column("canonical_store_id")
            .unique()
            .to_list()
        ]
        numerator = _sum(
            category_rows.filter(pl.col("canonical_store_id").cast(pl.Utf8).is_in(active_stores)),
            "revenue_vat",
        )
        return numerator, _sum(category_rows, "revenue_vat")
    if concept == "average_price_per_liter":
        if "volume_l" not in entity_rows.columns:
            return None, None
        valid = entity_rows.filter(
            pl.col("volume_l").is_not_null()
            & (pl.col("volume_l") > 0)
            & pl.col("units").is_not_null()
            & pl.col("revenue_vat").is_not_null()
        )
        return _sum(valid, "revenue_vat"), _sum_expr(valid, pl.col("units") * pl.col("volume_l"))
    raise ValueError(f"Unsupported source-like diagnostics KPI concept: {concept}")


def _active_store_universe_by_period(source: pl.DataFrame) -> dict[date, float]:
    if source.is_empty():
        return {}
    frame = (
        source.filter((pl.col("units") > 0) & pl.col("canonical_store_id").is_not_null())
        .group_by("period")
        .agg(pl.col("canonical_store_id").n_unique().alias("active_store_count"))
    )
    return {row["period"]: float(row["active_store_count"]) for row in frame.to_dicts()}


def _distinct_active_stores(rows: pl.DataFrame) -> float:
    if rows.is_empty():
        return 0.0
    return float(
        rows.filter((pl.col("units") > 0) & pl.col("canonical_store_id").is_not_null())
        .get_column("canonical_store_id")
        .n_unique()
    )


def _sum(rows: pl.DataFrame, column: str) -> float | None:
    if rows.is_empty() or column not in rows.columns:
        return None
    value = rows.get_column(column).sum()
    return float(value) if value is not None else None


def _sum_expr(rows: pl.DataFrame, expression: pl.Expr) -> float | None:
    if rows.is_empty():
        return None
    value = rows.select(expression.sum().alias("value")).item(0, "value")
    return float(value) if value is not None else None


def _ratio_value(components: tuple[float | None, float | None] | None) -> float | None:
    if components is None:
        return None
    numerator, denominator = components
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _entity_options_from_rows(grain: str, entity_column: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if grain != "sku":
        return sorted(
            [
                {
                    "stable_entity_id": str(row[entity_column]),
                    "display_label": str(row.get("display_label") or row[entity_column]),
                }
                for row in rows
            ],
            key=lambda item: item["display_label"].lower(),
        )
    base_labels = [_sku_display_name(row.get("display_label")) for row in rows]
    duplicates = {label for label in base_labels if base_labels.count(label) > 1 and label != "SKU без названия"}
    options: list[dict[str, Any]] = []
    for row, base_label in zip(rows, base_labels, strict=True):
        entity_id = str(row[entity_column])
        secondary = _sku_secondary(entity_id, row, needs_disambiguation=base_label in duplicates)
        label = f"{base_label} · {secondary}" if secondary and base_label in duplicates else base_label
        options.append({"stable_entity_id": entity_id, "display_label": label, "secondary_label": secondary})
    return sorted(options, key=lambda item: (item["display_label"].lower(), item["stable_entity_id"]))


def _semantic_filters(request: DiagnosticsRequest) -> dict[str, tuple[str, ...]]:
    filters = request.user_entity_filters or request.entity_filters or {}
    return {key: tuple(str(value) for value in values if value) for key, values in filters.items() if values}


def _filters(raw: object) -> dict[str, tuple[str, ...]] | None:
    if not isinstance(raw, dict):
        return None
    return {
        str(key): tuple(str(item) for item in values)
        for key, values in raw.items()
        if isinstance(values, (list, tuple)) and values
    }


def _json_filters(filters: dict[str, tuple[str, ...]] | None) -> dict[str, list[str]]:
    return {key: list(values) for key, values in (filters or {}).items()}


def _metric_supported(concept: str, grain: str) -> bool:
    return grain in DIAGNOSTICS_QUERY_METRIC_SUPPORT.get(concept, frozenset())


def _unsupported_metric(concept: str) -> dict[str, Any]:
    return {
        "status": "NEEDS_BUSINESS_RULE",
        "current_value": None,
        "reference_value": None,
        "delta_value": None,
        "format": "decimal",
        "delta_format": "decimal",
        "reason": f"{concept}_not_supported_for_diagnostics_breakdown",
    }


def _unsupported_period_metric(concept: str, period_mode: PeriodMode) -> dict[str, Any]:
    return {
        "status": "NEEDS_BUSINESS_RULE",
        "current_value": None,
        "reference_value": None,
        "delta_value": None,
        "format": _format_for_concept(concept),
        "delta_format": _delta_format_for_concept(concept),
        "reason": f"{concept}_diagnostics_{period_mode.value.lower()}_period_not_productized",
    }


def _no_data_metric(concept: str, reason: str) -> dict[str, Any]:
    return {
        "status": "NO_DATA",
        "current_value": None,
        "reference_value": None,
        "delta_value": None,
        "format": "decimal",
        "delta_format": "decimal",
        "reason": reason,
    }


def _response_limitations(entity_options: tuple[dict[str, Any], ...], request: DiagnosticsRequest) -> list[str]:
    if not entity_options:
        return ["no_diagnostics_entities"]
    if request.selected_metric not in DIAGNOSTICS_OVERVIEW_KPIS:
        return ["unknown_selected_metric"]
    return []


def _support_matrix() -> dict[str, dict[str, str]]:
    matrix: dict[str, dict[str, str]] = {}
    for concept in DIAGNOSTICS_OVERVIEW_KPIS:
        matrix[concept] = {}
        for grain in DIAGNOSTICS_BREAKDOWN_GRAINS:
            if concept == "active_sku_count" or _metric_supported(concept, grain):
                matrix[concept][grain] = "SUPPORTED_REUSING_OVERVIEW"
            else:
                matrix[concept][grain] = "NEEDS_BUSINESS_RULE"
    return matrix


def _format_for(result: MetricQueryResult) -> str:
    return _format_for_concept(result.metric_concept)


def _format_for_concept(concept: str) -> str:
    if concept in {"revenue_vat", "retailer_margin_abs", "weighted_shelf_price_vat", "weighted_input_price_vat"}:
        return "currency"
    if concept in {"retailer_margin_pct", "distribution", "weighted_distribution"}:
        return "percent"
    if concept == "average_price_per_liter":
        return "currency_per_liter"
    if concept == "velocity":
        return "decimal"
    return "decimal"


def _delta_format_for(result: MetricQueryResult) -> str:
    return _delta_format_for_concept(result.metric_concept)


def _delta_format_for_concept(concept: str) -> str:
    if concept in {"retailer_margin_pct", "distribution", "weighted_distribution"}:
        return "percentage_points"
    return _format_for_concept(concept)


def _label_column(grain: str, entity_column: str, available: set[str]) -> str:
    for candidate in DIAGNOSTICS_LABEL_COLUMNS.get(grain, (entity_column,)):
        if candidate in available:
            return candidate
    return entity_column


def _sku_display_name(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return text or "SKU без названия"


def _sku_secondary(entity_id: str, row: dict[str, Any], *, needs_disambiguation: bool) -> str | None:
    if not needs_disambiguation:
        return row.get("secondary_label")
    return f"PLU {entity_id}"


def _date_or_none(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
