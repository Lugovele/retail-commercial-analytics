"""Dashboard UI request adapters and response serializers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from retail_analytics.mart import (
    ComparisonMode,
    DashboardMetricQueryRequest,
    DashboardMetricQueryResponse,
    PeriodMode,
    PrivateLabelScope,
    QualityPolicy,
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


def _date_or_none(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


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
