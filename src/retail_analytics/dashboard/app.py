"""No-build web dashboard application."""

from __future__ import annotations

import json
import mimetypes
from datetime import date
from importlib import resources
from typing import Any
from urllib.parse import parse_qs
from wsgiref.types import StartResponse, WSGIApplication, WSGIEnvironment

from retail_analytics.dashboard.data import (
    DashboardDataService,
    build_data_request,
    data_response_to_dict,
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
    signal_feed_service = SignalFeedService(
        events_path=resolved_runtime.events_path,
        event_rules_path=resolved_runtime.event_rules_path,
        mart_builds=resolved_runtime.query_service.mart_builds,
    )
    data_service = DashboardDataService(
        resolved_runtime.query_service.metric_facts_path,
        mart_builds=resolved_runtime.query_service.mart_builds,
        source_ledger=resolved_runtime.query_service.source_ledger,
        source_like_rows_path=resolved_runtime.source_like_rows_path,
    )

    def app(environ: WSGIEnvironment, start_response: StartResponse) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        try:
            if method == "GET" and path == "/":
                return _response(start_response, _template_text("index.html"), content_type="text/html; charset=utf-8")
            if method == "GET" and path.startswith("/static/"):
                name = path.removeprefix("/static/")
                return _response(start_response, _static_bytes(name), content_type=_content_type(name))
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
                request = build_backend_query_request(payload)
                response = resolved_runtime.query_service.query(request)
                return _json_response(start_response, serialize_dashboard_query_response(response))
            if method == "POST" and path == "/api/dashboard/contribution":
                payload = _read_json(environ)
                contribution_request = build_contribution_request(payload)
                contribution_response = contribution_service.contribution(contribution_request)
                return _json_response(start_response, serialize_contribution_response(contribution_response))
            if method == "POST" and path == "/api/dashboard/portfolio-market":
                payload = _read_json(environ)
                portfolio_request = build_portfolio_market_request(payload)
                portfolio_response = portfolio_market_service.query(portfolio_request)
                return _json_response(start_response, serialize_portfolio_market_response(portfolio_response))
            if method == "POST" and path == "/api/dashboard/signals":
                payload = _read_json(environ)
                signal_request = build_signal_feed_request(payload)
                signal_response = signal_feed_service.feed(signal_request)
                return _json_response(start_response, serialize_signal_feed_response(signal_response))
            if method == "POST" and path == "/api/dashboard/data":
                payload = _read_json(environ)
                data_request = build_data_request(payload)
                data_response = data_service.query(data_request)
                return _json_response(start_response, data_response_to_dict(data_response))
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


def _template_text(name: str) -> str:
    return (resources.files("retail_analytics.dashboard.templates") / name).read_text(encoding="utf-8")


def _static_bytes(name: str) -> bytes:
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Invalid static asset path")
    return (resources.files("retail_analytics.dashboard.static") / name).read_bytes()


def _response(
    start_response: StartResponse,
    body: str | bytes,
    *,
    status: str = "200 OK",
    content_type: str,
) -> list[bytes]:
    raw = body.encode("utf-8") if isinstance(body, str) else body
    start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(raw)))])
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


def _parent_filters(params: dict[str, list[str]]) -> dict[str, str]:
    return {
        key: value
        for key in ("category", "manufacturer", "brand", "sku", "store")
        if (value := _first(params, key))
    }
