"""Dashboard UI request adapters and response serializers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from retail_analytics.mart import (
    ComparisonMode,
    ContributionQueryRequest,
    ContributionQueryResponse,
    DashboardMetricQueryRequest,
    DashboardMetricQueryResponse,
    PeriodMode,
    PortfolioMarketQueryRequest,
    PortfolioMarketResponse,
    PrivateLabelScope,
    QualityPolicy,
    SignalFeedRequest,
    SignalFeedResponse,
    SignalType,
)


@dataclass(frozen=True)
class DashboardUiQueryPayload:
    """UI-facing query payload.

    The UI contract mirrors dashboard filters and deliberately does not carry
    business formula inputs. Metric semantics stay inside mart/query contracts.
    """

    retailer_id: str
    source_id: str
    period_mode: PeriodMode | str
    period_grain: str
    grain_id: str
    metric_concepts: tuple[str, ...]
    date_from: date | str | None = None
    date_to: date | str | None = None
    entity_ids: tuple[str, ...] = ()
    entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: ComparisonMode | str = ComparisonMode.NONE
    ownership_scope: str | None = None
    quality_policy: QualityPolicy | str = QualityPolicy.INCLUDE_ALL
    include_lineage: bool = True
    mart_build_id: str | None = None
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE


@dataclass(frozen=True)
class DashboardUiRuntimeResponse:
    """Runtime metadata needed by the static dashboard shell."""

    app_title: str
    retailers: tuple[dict[str, Any], ...]
    default_retailer_id: str
    default_source_id: str
    supported_grains: tuple[str, ...]
    supported_period_modes: tuple[str, ...]
    supported_comparison_modes: tuple[str, ...]
    supported_private_label_scopes: tuple[str, ...]


@dataclass(frozen=True)
class DashboardUiContributionPayload:
    """UI-facing additive contribution request."""

    retailer_id: str
    source_id: str
    current_period: date | str
    reference_period: date | str
    period_grain: str
    parent_grain_id: str
    parent_entity_id: str | None
    child_grain_id: str
    metric_concept: str
    comparison_mode: str
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None
    quality_policy: QualityPolicy | str = QualityPolicy.INCLUDE_ALL
    limit: int = 40
    parent_metric_definition_id: str | None = None
    child_metric_definition_id: str | None = None


@dataclass(frozen=True)
class DashboardUiPortfolioMarketPayload:
    """UI-facing product route request for portfolio-market analytics."""

    retailer_id: str
    source_id: str
    period_mode: PeriodMode | str
    period_grain: str
    grain_id: str
    concept_ids: tuple[str, ...]
    date_from: date | str | None = None
    date_to: date | str | None = None
    entity_ids: tuple[str, ...] = ()
    entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: str = "NONE"
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None
    quality_policy: QualityPolicy | str = QualityPolicy.INCLUDE_ALL
    include_lineage: bool = True


@dataclass(frozen=True)
class DashboardUiSignalFeedPayload:
    """UI-facing deterministic signal feed request."""

    retailer_id: str
    source_id: str
    period_mode: PeriodMode | str
    period_grain: str
    date_from: date | str | None = None
    date_to: date | str | None = None
    grain_id: str = "network"
    entity_ids: tuple[str, ...] = ()
    entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: ComparisonMode | str = ComparisonMode.NONE
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None
    signal_types: tuple[str, ...] = (
        "COMMERCIAL_SIGNAL",
        "DETERMINISTIC_PATTERN",
        "DATA_QUALITY_ALERT",
    )
    limit: int = 50
    include_capability_limitations: bool = True


def build_backend_query_request(payload: DashboardUiQueryPayload | dict[str, Any]) -> DashboardMetricQueryRequest:
    """Build the exact backend query request from a UI payload."""

    data = _coerce_payload(payload)
    return DashboardMetricQueryRequest(
        retailer_id=data.retailer_id,
        source_id=data.source_id,
        date_from=_date_or_none(data.date_from),
        date_to=_date_or_none(data.date_to),
        period_mode=PeriodMode(data.period_mode),
        period_grain=data.period_grain,
        grain_id=data.grain_id,
        entity_ids=tuple(data.entity_ids),
        entity_filters=data.entity_filters,
        metric_concepts=tuple(data.metric_concepts),
        comparison_mode=ComparisonMode(data.comparison_mode),
        ownership_scope=data.ownership_scope,
        quality_policy=QualityPolicy(data.quality_policy),
        include_lineage=data.include_lineage,
        mart_build_id=data.mart_build_id,
        private_label_scope=PrivateLabelScope(data.private_label_scope),
    )


def build_contribution_request(payload: DashboardUiContributionPayload | dict[str, Any]) -> ContributionQueryRequest:
    """Build an additive contribution request from a UI payload."""

    data = _coerce_contribution_payload(payload)
    return ContributionQueryRequest(
        retailer_id=data.retailer_id,
        source_id=data.source_id,
        current_period=_date_required(data.current_period),
        reference_period=_date_required(data.reference_period),
        period_grain=data.period_grain,
        parent_grain_id=data.parent_grain_id,
        parent_entity_id=data.parent_entity_id,
        child_grain_id=data.child_grain_id,
        metric_concept=data.metric_concept,
        comparison_mode=data.comparison_mode,
        private_label_scope=PrivateLabelScope(data.private_label_scope),
        mart_build_id=data.mart_build_id,
        quality_policy=QualityPolicy(data.quality_policy).value,
        limit=data.limit,
        parent_metric_definition_id=data.parent_metric_definition_id,
        child_metric_definition_id=data.child_metric_definition_id,
    )


def build_portfolio_market_request(
    payload: DashboardUiPortfolioMarketPayload | dict[str, Any],
) -> PortfolioMarketQueryRequest:
    """Build a concept-explicit portfolio-market backend request."""

    data = _coerce_portfolio_market_payload(payload)
    return PortfolioMarketQueryRequest(
        retailer_id=data.retailer_id,
        source_id=data.source_id,
        date_from=_date_or_none(data.date_from),
        date_to=_date_or_none(data.date_to),
        period_mode=PeriodMode(data.period_mode),
        period_grain=data.period_grain,
        grain_id=data.grain_id,
        concept_ids=tuple(data.concept_ids),
        entity_ids=tuple(data.entity_ids),
        entity_filters=data.entity_filters,
        user_entity_filters=data.entity_filters,
        comparison_mode=ComparisonMode(data.comparison_mode),
        private_label_scope=PrivateLabelScope(data.private_label_scope),
        mart_build_id=data.mart_build_id,
        quality_policy=QualityPolicy(data.quality_policy),
        include_lineage=data.include_lineage,
    )


def build_signal_feed_request(payload: DashboardUiSignalFeedPayload | dict[str, Any]) -> SignalFeedRequest:
    """Build a product-safe signal feed request from a UI payload."""

    data = _coerce_signal_feed_payload(payload)
    return SignalFeedRequest(
        retailer_id=data.retailer_id,
        source_id=data.source_id,
        date_from=_date_or_none(data.date_from),
        date_to=_date_or_none(data.date_to),
        period_mode=PeriodMode(data.period_mode),
        period_grain=data.period_grain,
        grain_id=data.grain_id,
        entity_ids=tuple(data.entity_ids),
        entity_filters=data.entity_filters,
        comparison_mode=ComparisonMode(data.comparison_mode),
        private_label_scope=PrivateLabelScope(data.private_label_scope),
        mart_build_id=data.mart_build_id,
        signal_types=tuple(SignalType(item) for item in data.signal_types),
        limit=data.limit,
        include_capability_limitations=data.include_capability_limitations,
    )


def serialize_dashboard_query_response(response: DashboardMetricQueryResponse) -> dict[str, Any]:
    """Serialize a dashboard query response without changing metric semantics."""

    return {
        "request_scope": _json_ready(response.request_scope),
        "requested_period_start": _date_text(response.requested_period_start),
        "requested_period_end": _date_text(response.requested_period_end),
        "available_periods": [_date_text(period) for period in response.available_periods],
        "missing_periods": [_date_text(period) for period in response.missing_periods],
        "coverage_ratio": response.coverage_ratio,
        "coverage_status": response.coverage_status.value,
        "metric_results": [_metric_result(result) for result in response.metric_results],
        "comparisons": [_comparison_result(result) for result in response.comparisons],
        "quality_flags": list(response.quality_flags),
        "limitations": [
            {
                "issue_code": item.issue_code,
                "message": item.message,
                "metric_definition_id": item.metric_definition_id,
                "metric_concept": item.metric_concept,
            }
            for item in response.limitations
        ],
        "mart_build_id": response.mart_build_id,
        "analysis_run_ids": list(response.analysis_run_ids),
        "metric_definition_lineage": [_lineage(lineage) for lineage in response.metric_definition_lineage],
        "private_label_scope": response.private_label_scope.value,
        "scope_identity_hash": response.scope_identity_hash,
    }


def serialize_runtime_response(response: DashboardUiRuntimeResponse) -> dict[str, Any]:
    """Serialize runtime metadata for the browser."""

    return {
        "app_title": response.app_title,
        "retailers": list(response.retailers),
        "default_retailer_id": response.default_retailer_id,
        "default_source_id": response.default_source_id,
        "supported_grains": list(response.supported_grains),
        "supported_period_modes": list(response.supported_period_modes),
        "supported_comparison_modes": list(response.supported_comparison_modes),
        "supported_private_label_scopes": list(response.supported_private_label_scopes),
    }


def serialize_contribution_response(response: ContributionQueryResponse) -> dict[str, Any]:
    """Serialize additive contribution response for the browser."""

    return {
        "status": response.status.value,
        "request_scope": _json_ready(response.request_scope),
        "metric_concept": response.metric_concept,
        "parent_metric_definition": _definition_identity(response.parent_metric_definition),
        "child_metric_definition": _definition_identity(response.child_metric_definition),
        "parent_current_value": response.parent_current_value,
        "parent_reference_value": response.parent_reference_value,
        "parent_delta": response.parent_delta,
        "rows": [
            {
                "child_entity_id": row.child_entity_id,
                "current_value": row.current_value,
                "reference_value": row.reference_value,
                "delta": row.delta,
                "absolute_delta": row.absolute_delta,
                "parent_current_value": row.parent_current_value,
                "parent_reference_value": row.parent_reference_value,
                "parent_delta": row.parent_delta,
                "contribution_share": row.contribution_share,
                "status": row.status.value,
                "provenance": _json_ready(row.provenance),
            }
            for row in response.rows
        ],
        "limitations": list(response.limitations),
        "quality_flags": list(response.quality_flags),
        "mart_build_id": response.mart_build_id,
        "analysis_run_ids": list(response.analysis_run_ids),
        "source_revision_ids": list(response.source_revision_ids),
    }


def serialize_portfolio_market_response(response: PortfolioMarketResponse) -> dict[str, Any]:
    """Serialize portfolio-market route output without changing semantics."""

    return {
        "request_scope": _json_ready(response.request_scope),
        "items": [
            {
                "concept_id": item.concept_id,
                "status": item.status.value,
                "block_id": item.block_id,
                "grain_id": item.grain_id,
                "entity_id": item.entity_id,
                "label": item.label,
                "value": item.value,
                "unit": item.unit,
                "current_value": item.current_value,
                "reference_value": item.reference_value,
                "delta": item.delta,
                "pct_delta": item.pct_delta,
                "numerator_value": item.numerator_value,
                "denominator_value": item.denominator_value,
                "rows": _json_ready(item.rows),
                "limitations": list(item.limitations),
                "provenance": _json_ready(item.provenance),
            }
            for item in response.items
        ],
        "limitations": list(response.limitations),
        "mart_build_id": response.mart_build_id,
        "private_label_scope": response.private_label_scope.value,
    }


def serialize_signal_feed_response(response: SignalFeedResponse) -> dict[str, Any]:
    """Serialize signal feed route output without inventing narrative."""

    return {
        "status": response.status.value,
        "request_scope": _json_ready(response.request_scope),
        "signals": [_signal_row(row) for row in response.signals],
        "deterministic_patterns": [_signal_row(row) for row in response.deterministic_patterns],
        "data_quality_alerts": [_signal_row(row) for row in response.data_quality_alerts],
        "capability_limitations": [
            {
                "code": item.code,
                "message": item.message,
                "status": item.status,
                "provenance": _json_ready(item.provenance),
            }
            for item in response.capability_limitations
        ],
        "limitations": list(response.limitations),
        "event_count": response.event_count,
        "surfaced_event_count": response.surfaced_event_count,
        "excluded_event_counts": dict(response.excluded_event_counts),
        "mart_build_id": response.mart_build_id,
        "analysis_run_ids": list(response.analysis_run_ids),
        "source_revision_ids": list(response.source_revision_ids),
        "private_label_scope": response.private_label_scope.value,
    }


def _metric_result(result: Any) -> dict[str, Any]:
    return {
        "metric_concept": result.metric_concept,
        "metric_name": result.metric_name,
        "grain_id": result.grain_id,
        "entity_id": result.entity_id,
        "value": result.value,
        "numerator_value": result.numerator_value,
        "denominator_value": result.denominator_value,
        "range_aggregation_strategy": result.range_aggregation_strategy.value,
        "share_scope": result.share_scope,
        "period_values": [
            {
                "period_start": _date_text(period.period_start),
                "period_end": _date_text(period.period_end),
                "business_period_id": period.business_period_id,
                "value": period.value,
                "numerator_value": period.numerator_value,
                "denominator_value": period.denominator_value,
                "source_revision_id": period.source_revision_id,
                "analysis_run_id": period.analysis_run_id,
                "quality_status": period.quality_status,
                "quality_flags": period.quality_flags,
            }
            for period in result.period_values
        ],
        "lineage": _lineage(result.lineage) if result.lineage is not None else None,
        "limitations": list(result.limitations),
        "private_label_scope": result.private_label_scope.value,
        "provenance": _json_ready(result.provenance.payload) if result.provenance is not None else None,
    }


def _comparison_result(result: Any) -> dict[str, Any]:
    return {
        "comparison_mode": result.comparison_mode.value,
        "metric_definition_id": result.metric_definition_id,
        "entity_id": result.entity_id,
        "current_period_start": _date_text(result.current_period_start),
        "comparison_period_start": _date_text(result.comparison_period_start),
        "current_value": result.current_value,
        "comparison_value": result.comparison_value,
        "delta": result.delta,
        "pct_delta": result.pct_delta,
        "quality_status": result.quality_status,
        "gap_periods": result.gap_periods,
        "private_label_scope": result.private_label_scope.value,
    }


def _lineage(lineage: Any) -> dict[str, Any]:
    return {
        "metric_definition_id": lineage.metric_definition_id,
        "metric_definition_version": lineage.metric_definition_version,
        "metric_config_hash": lineage.metric_config_hash,
        "rule_version": lineage.rule_version,
        "semantic_family": lineage.semantic_family,
        "semantic_compatibility_version": lineage.semantic_compatibility_version,
        "cross_retailer_comparable": lineage.cross_retailer_comparable,
    }


def _definition_identity(identity: Any) -> dict[str, Any] | None:
    if identity is None:
        return None
    return {
        "metric_definition_id": identity.metric_definition_id,
        "metric_definition_version": identity.metric_definition_version,
        "metric_config_hash": identity.metric_config_hash,
        "rule_version": identity.rule_version,
        "semantic_family": identity.semantic_family,
        "semantic_compatibility_version": identity.semantic_compatibility_version,
        "aggregation": identity.aggregation,
        "range_aggregation_strategy": identity.range_aggregation_strategy,
    }


def _coerce_payload(payload: DashboardUiQueryPayload | dict[str, Any]) -> DashboardUiQueryPayload:
    if isinstance(payload, DashboardUiQueryPayload):
        return payload
    raw_filters = payload.get("entity_filters")
    filters = (
        {str(key): tuple(str(item) for item in values) for key, values in raw_filters.items()}
        if isinstance(raw_filters, dict)
        else None
    )
    return DashboardUiQueryPayload(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        date_from=payload.get("date_from"),
        date_to=payload.get("date_to"),
        period_mode=payload.get("period_mode", PeriodMode.SINGLE_PERIOD),
        period_grain=str(payload.get("period_grain", "month")),
        grain_id=str(payload.get("grain_id", "network")),
        entity_ids=tuple(str(item) for item in payload.get("entity_ids", ())),
        entity_filters=filters,
        metric_concepts=tuple(str(item) for item in payload.get("metric_concepts", ())),
        comparison_mode=payload.get("comparison_mode", ComparisonMode.NONE),
        ownership_scope=payload.get("ownership_scope"),
        quality_policy=payload.get("quality_policy", QualityPolicy.INCLUDE_ALL),
        include_lineage=bool(payload.get("include_lineage", True)),
        mart_build_id=payload.get("mart_build_id"),
        private_label_scope=payload.get("private_label_scope", PrivateLabelScope.INCLUDE),
    )


def _coerce_contribution_payload(
    payload: DashboardUiContributionPayload | dict[str, Any],
) -> DashboardUiContributionPayload:
    if isinstance(payload, DashboardUiContributionPayload):
        return payload
    return DashboardUiContributionPayload(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        current_period=payload["current_period"],
        reference_period=payload["reference_period"],
        period_grain=str(payload.get("period_grain", "month")),
        parent_grain_id=str(payload["parent_grain_id"]),
        parent_entity_id=_optional_text(payload.get("parent_entity_id")),
        child_grain_id=str(payload["child_grain_id"]),
        metric_concept=str(payload["metric_concept"]),
        comparison_mode=str(payload.get("comparison_mode", "CUSTOM_PERIODS")),
        private_label_scope=payload.get("private_label_scope", PrivateLabelScope.INCLUDE),
        mart_build_id=payload.get("mart_build_id"),
        quality_policy=payload.get("quality_policy", QualityPolicy.INCLUDE_ALL),
        limit=int(payload.get("limit", 40)),
        parent_metric_definition_id=_optional_text(payload.get("parent_metric_definition_id")),
        child_metric_definition_id=_optional_text(payload.get("child_metric_definition_id")),
    )


def _coerce_portfolio_market_payload(
    payload: DashboardUiPortfolioMarketPayload | dict[str, Any],
) -> DashboardUiPortfolioMarketPayload:
    if isinstance(payload, DashboardUiPortfolioMarketPayload):
        return payload
    raw_filters = payload.get("entity_filters")
    filters = (
        {str(key): tuple(str(item) for item in values) for key, values in raw_filters.items()}
        if isinstance(raw_filters, dict)
        else None
    )
    return DashboardUiPortfolioMarketPayload(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        date_from=payload.get("date_from"),
        date_to=payload.get("date_to"),
        period_mode=payload.get("period_mode", PeriodMode.SINGLE_PERIOD),
        period_grain=str(payload.get("period_grain", "month")),
        grain_id=str(payload.get("grain_id", "network")),
        concept_ids=tuple(str(item) for item in payload.get("concept_ids", ())),
        entity_ids=tuple(str(item) for item in payload.get("entity_ids", ())),
        entity_filters=filters,
        comparison_mode=str(payload.get("comparison_mode", "NONE")),
        private_label_scope=payload.get("private_label_scope", PrivateLabelScope.INCLUDE),
        mart_build_id=payload.get("mart_build_id"),
        quality_policy=payload.get("quality_policy", QualityPolicy.INCLUDE_ALL),
        include_lineage=bool(payload.get("include_lineage", True)),
    )


def _coerce_signal_feed_payload(
    payload: DashboardUiSignalFeedPayload | dict[str, Any],
) -> DashboardUiSignalFeedPayload:
    if isinstance(payload, DashboardUiSignalFeedPayload):
        return payload
    raw_filters = payload.get("entity_filters")
    filters = (
        {str(key): tuple(str(item) for item in values) for key, values in raw_filters.items()}
        if isinstance(raw_filters, dict)
        else None
    )
    return DashboardUiSignalFeedPayload(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        date_from=payload.get("date_from"),
        date_to=payload.get("date_to"),
        period_mode=payload.get("period_mode", PeriodMode.SINGLE_PERIOD),
        period_grain=str(payload.get("period_grain", "month")),
        grain_id=str(payload.get("grain_id", "network")),
        entity_ids=tuple(str(item) for item in payload.get("entity_ids", ())),
        entity_filters=filters,
        comparison_mode=payload.get("comparison_mode", ComparisonMode.NONE),
        private_label_scope=payload.get("private_label_scope", PrivateLabelScope.INCLUDE),
        mart_build_id=payload.get("mart_build_id"),
        signal_types=tuple(
            str(item)
            for item in payload.get(
                "signal_types",
                ("COMMERCIAL_SIGNAL", "DETERMINISTIC_PATTERN", "DATA_QUALITY_ALERT"),
            )
        ),
        limit=int(payload.get("limit", 50)),
        include_capability_limitations=bool(payload.get("include_capability_limitations", True)),
    )


def _date_or_none(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _date_required(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _json_ready(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


def _signal_row(row: Any) -> dict[str, Any]:
    return {
        "signal_id": row.signal_id,
        "signal_type": row.signal_type.value,
        "event_type": row.event_type,
        "event_family": row.event_family,
        "object_grain": row.object_grain,
        "object_id": row.object_id,
        "category_id": row.category_id,
        "period": _date_text(row.period),
        "reference_period": _date_text(row.reference_period),
        "comparison_type": row.comparison_type,
        "current_value": row.current_value,
        "reference_value": row.reference_value,
        "delta_abs": row.delta_abs,
        "delta_pct": row.delta_pct,
        "delta_pp": row.delta_pp,
        "rule_id": row.rule_id,
        "rule_version": row.rule_version,
        "event_config_hash": row.event_config_hash,
        "severity": row.severity,
        "priority": row.priority,
        "confidence": row.confidence,
        "comparison_quality": row.comparison_quality,
        "private_label_scope": row.private_label_scope.value,
        "status": row.status.value,
        "provenance": _json_ready(row.provenance),
    }
