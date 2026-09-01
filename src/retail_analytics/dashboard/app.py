"""No-build web dashboard application."""

from __future__ import annotations

import json
import mimetypes
from dataclasses import replace
from datetime import date
from hashlib import sha256
from importlib import resources
from typing import Any
from urllib.parse import parse_qs
from wsgiref.types import StartResponse, WSGIApplication, WSGIEnvironment

from retail_analytics.dashboard.data import (
    DashboardDataService,
    build_data_request,
    data_response_to_dict,
)
from retail_analytics.dashboard.diagnostics import DiagnosticsService, build_diagnostics_request
from retail_analytics.dashboard.geography import GeographyQueryService, build_geography_request
from retail_analytics.dashboard.package_volume import (
    PackageVolumeQueryService,
    build_package_volume_request,
)
from retail_analytics.dashboard.runtime import (
    DashboardRuntime,
    build_dashboard_runtime,
    serialize_catalog,
)
from retail_analytics.dashboard.schemas import (
    build_backend_query_request,
    build_contribution_request,
    build_portfolio_market_request,
    build_signal_feed_request,
    serialize_contribution_response,
    serialize_dashboard_query_response,
    serialize_portfolio_market_response,
    serialize_signal_feed_response,
)
from retail_analytics.mart import (
    AdditiveContributionService,
    PortfolioMarketService,
    SignalFeedService,
)


def create_dashboard_wsgi_app(runtime: DashboardRuntime | None = None) -> WSGIApplication:
    """Create a small WSGI app for local dashboard use and integration tests."""

    resolved_runtime = runtime or build_dashboard_runtime()
    contribution_service = AdditiveContributionService(
        resolved_runtime.query_service.metric_facts_path,
        mart_builds=resolved_runtime.query_service.mart_builds,
    )
    portfolio_market_service = PortfolioMarketService(resolved_runtime.query_service)
    diagnostics_service = DiagnosticsService(
        resolved_runtime.query_service,
        portfolio_market_service,
        source_like_rows_path=resolved_runtime.source_like_rows_path,
    )
    signal_feed_service = SignalFeedService(
        events_path=resolved_runtime.events_path,
        event_facts_path=resolved_runtime.event_facts_path,
        event_rules_path=resolved_runtime.event_rules_path,
        mart_builds=resolved_runtime.query_service.mart_builds,
    )
    data_service = DashboardDataService(
        resolved_runtime.query_service.metric_facts_path,
        mart_builds=resolved_runtime.query_service.mart_builds,
        source_ledger=resolved_runtime.query_service.source_ledger,
        source_like_rows_path=resolved_runtime.source_like_rows_path,
    )
    geography_service = GeographyQueryService(
        resolved_runtime.product_store_facts_path,
        mart_builds=resolved_runtime.query_service.mart_builds,
        source_ledger=resolved_runtime.query_service.source_ledger,
    )
    package_volume_service = PackageVolumeQueryService(
        resolved_runtime.source_like_rows_path,
        resolved_runtime.product_store_facts_path,
        mart_builds=resolved_runtime.query_service.mart_builds,
        source_ledger=resolved_runtime.query_service.source_ledger,
    )

    def app(environ: WSGIEnvironment, start_response: StartResponse) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        try:
            if method == "GET" and path == "/":
                return _response(start_response, _template_text("index.html"), content_type="text/html; charset=utf-8")
            if method == "GET" and path.startswith("/static/"):
                name = path.removeprefix("/static/")
                return _response(
                    start_response,
                    _static_bytes(name),
                    content_type=_content_type(name),
                    headers=[("Cache-Control", "no-cache")],
                )
            if method == "GET" and path == "/healthz":
                return _json_response(start_response, {"status": "ok"})
            if method == "GET" and path == "/api/dashboard/runtime":
                return _json_response(start_response, resolved_runtime.runtime_metadata())
            if method == "GET" and path == "/api/dashboard/catalog":
                params = parse_qs(str(environ.get("QUERY_STRING", "")))
                retailer_id = _first(params, "retailer_id") or resolved_runtime.retailers[0].retailer_id
                source_id = _first(params, "source_id") or resolved_runtime.retailers[0].source_id
                return _json_response(
                    start_response,
                    {
                        "metrics": serialize_catalog(
                            resolved_runtime.effective_catalog(retailer_id=retailer_id, source_id=source_id)
                        )
                    },
                )
            if method == "GET" and path == "/api/dashboard/options":
                params = parse_qs(str(environ.get("QUERY_STRING", "")))
                retailer_id = _first(params, "retailer_id") or resolved_runtime.retailers[0].retailer_id
                source_id = _first(params, "source_id") or resolved_runtime.retailers[0].source_id
                return _json_response(
                    start_response,
                    resolved_runtime.options_metadata(
                        retailer_id=retailer_id,
                        source_id=source_id,
                        private_label_scope=_first(params, "private_label_scope") or "INCLUDE",
                        date_from=_optional_date(_first(params, "date_from")),
                        date_to=_optional_date(_first(params, "date_to")),
                        parent_filters=_parent_filters(params),
                    ),
                )
            if method == "POST" and path == "/api/dashboard/query":
                payload = _read_json(environ)
                original_entity_filters = _resolve_payload_entity_filters(payload, resolved_runtime)
                request = build_backend_query_request(payload)
                if original_entity_filters is not None:
                    request = replace(
                        request,
                        user_entity_filters={
                            key: tuple(values) for key, values in original_entity_filters.items()
                        },
                    )
                response = resolved_runtime.query_service.query(request)
                data = serialize_dashboard_query_response(response)
                _attach_user_execution_filters(data, original_entity_filters)
                return _json_response(start_response, data)
            if method == "POST" and path == "/api/dashboard/contribution":
                payload = _read_json(environ)
                contribution_request = build_contribution_request(payload)
                contribution_response = contribution_service.contribution(contribution_request)
                return _json_response(start_response, serialize_contribution_response(contribution_response))
            if method == "POST" and path == "/api/dashboard/portfolio-market":
                payload = _read_json(environ)
                original_entity_filters = _resolve_payload_entity_filters(payload, resolved_runtime)
                portfolio_request = build_portfolio_market_request(payload)
                if original_entity_filters is not None:
                    portfolio_request = replace(
                        portfolio_request,
                        user_entity_filters={
                            key: tuple(values) for key, values in original_entity_filters.items()
                        },
                    )
                portfolio_response = portfolio_market_service.query(portfolio_request)
                data = serialize_portfolio_market_response(portfolio_response)
                _attach_user_execution_filters(data, original_entity_filters)
                return _json_response(start_response, data)
            if method == "POST" and path == "/api/dashboard/diagnostics":
                payload = _read_json(environ)
                original_entity_filters = _resolve_payload_entity_filters(payload, resolved_runtime)
                if original_entity_filters is not None:
                    payload["user_entity_filters"] = original_entity_filters
                diagnostics_response = diagnostics_service.query(build_diagnostics_request(payload))
                return _json_response(start_response, diagnostics_response)
            if method == "POST" and path == "/api/dashboard/signals":
                payload = _read_json(environ)
                original_entity_filters = _resolve_payload_entity_filters(payload, resolved_runtime)
                signal_request = build_signal_feed_request(payload)
                signal_response = signal_feed_service.feed(signal_request)
                data = serialize_signal_feed_response(signal_response)
                _attach_user_execution_filters(data, original_entity_filters)
                return _json_response(start_response, data)
            if method == "POST" and path == "/api/dashboard/data":
                payload = _read_json(environ)
                original_entity_filters = _resolve_payload_entity_filters(payload, resolved_runtime)
                data_request = build_data_request(payload)
                data_response = data_service.query(data_request)
                data = data_response_to_dict(data_response)
                _attach_user_execution_filters(data, original_entity_filters)
                return _json_response(start_response, data)
            if method == "POST" and path == "/api/dashboard/geography":
                payload = _read_json(environ)
                original_entity_filters = _resolve_payload_entity_filters(payload, resolved_runtime)
                geography_request = build_geography_request(payload)
                data = geography_service.query(geography_request)
                _attach_user_execution_filters(data, original_entity_filters)
                return _json_response(start_response, data)
            if method == "POST" and path == "/api/dashboard/package-volume":
                payload = _read_json(environ)
                original_entity_filters = _resolve_payload_entity_filters(payload, resolved_runtime)
                package_volume_request = build_package_volume_request(payload)
                data = package_volume_service.query(package_volume_request)
                _attach_user_execution_filters(data, original_entity_filters)
                return _json_response(start_response, data)
            return _json_response(start_response, {"error": "not_found"}, status="404 Not Found")
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return _json_response(
                start_response,
                {"error": type(exc).__name__, "message": str(exc)},
                status="400 Bad Request",
            )

    return app


def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(length) if length else b"{}"
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON body must be an object")
    return payload


def _resolve_payload_entity_filters(payload: dict[str, Any], runtime: DashboardRuntime) -> dict[str, list[str]] | None:
    raw_filters = payload.get("entity_filters")
    if not isinstance(raw_filters, dict):
        return None
    filters = {
        str(key): tuple(str(item) for item in values)
        for key, values in raw_filters.items()
        if isinstance(values, (list, tuple))
    }
    original_filters = {key: list(values) for key, values in filters.items()}
    resolved = runtime.query_entity_filters(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        private_label_scope=payload.get("private_label_scope", "INCLUDE"),
        date_from=_optional_date(payload.get("date_from")),
        date_to=_optional_date(payload.get("date_to")),
        comparison_mode=payload.get("comparison_mode", "NONE"),
        entity_filters=filters,
    )
    if resolved is not raw_filters:
        payload["entity_filters"] = {key: list(values) for key, values in (resolved or {}).items()}
    return original_filters


def _attach_user_execution_filters(data: dict[str, Any], original_entity_filters: dict[str, list[str]] | None) -> None:
    if original_entity_filters is None:
        return
    request_scope = data.get("request_scope")
    if not isinstance(request_scope, dict):
        return
    execution_filters = request_scope.get("entity_filters") or {}
    request_scope["user_entity_filters"] = original_entity_filters
    request_scope["execution_entity_filters"] = execution_filters
    for result in data.get("metric_results") or ():
        _attach_filters_to_provenance(result.get("provenance"), original_entity_filters, execution_filters)
    for row in data.get("rows") or ():
        _attach_filters_to_provenance(row.get("provenance"), original_entity_filters, execution_filters)
    for item in data.get("items") or ():
        _attach_filters_to_provenance(item.get("provenance"), original_entity_filters, execution_filters)
        for row in item.get("rows") or ():
            _attach_filters_to_provenance(row.get("provenance"), original_entity_filters, execution_filters)
    for key in ("signals", "deterministic_patterns", "data_quality_alerts"):
        for row in data.get(key) or ():
            _attach_filters_to_provenance(row.get("provenance"), original_entity_filters, execution_filters)
    audit = data.get("audit")
    if isinstance(audit, dict):
        audit["user_entity_filters"] = original_entity_filters
        audit["execution_entity_filters"] = execution_filters


def _attach_filters_to_provenance(
    provenance: object,
    original_entity_filters: dict[str, list[str]],
    execution_filters: object,
) -> None:
    if not isinstance(provenance, dict):
        return
    scope = provenance.get("current_analytical_scope")
    if isinstance(scope, dict):
        scope["user_entity_filters"] = original_entity_filters
        scope["execution_entity_filters"] = execution_filters


def _template_text(name: str) -> str:
    text = (resources.files("retail_analytics.dashboard.templates") / name).read_text(encoding="utf-8")
    if name == "index.html":
        text = text.replace("__DASHBOARD_ASSET_VERSION__", _asset_version())
    return text


def _static_bytes(name: str) -> bytes:
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Invalid static asset path")
    return (resources.files("retail_analytics.dashboard.static") / name).read_bytes()


def _asset_version() -> str:
    digest = sha256()
    for name in ("app.js", "styles.css"):
        digest.update(_static_bytes(name))
    return digest.hexdigest()[:12]


def _response(
    start_response: StartResponse,
    body: str | bytes,
    *,
    status: str = "200 OK",
    content_type: str,
    headers: list[tuple[str, str]] | None = None,
) -> list[bytes]:
    raw = body.encode("utf-8") if isinstance(body, str) else body
    response_headers = [("Content-Type", content_type), ("Content-Length", str(len(raw)))]
    if headers:
        response_headers.extend(headers)
    start_response(status, response_headers)
    return [raw]


def _json_response(
    start_response: StartResponse,
    payload: dict[str, Any],
    *,
    status: str = "200 OK",
) -> list[bytes]:
    return _response(
        start_response,
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        status=status,
        content_type="application/json; charset=utf-8",
    )


def _content_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parent_filters(params: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    filters: dict[str, tuple[str, ...]] = {}
    for key in ("category", "manufacturer", "brand", "sku", "store"):
        values = tuple(value for value in params.get(key, ()) if value)
        if values:
            filters[key] = values
    return filters
