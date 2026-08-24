from __future__ import annotations

import io
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from wsgiref.types import WSGIApplication

from retail_analytics.dashboard import build_synthetic_dashboard_runtime, create_dashboard_wsgi_app


def test_dashboard_wsgi_runtime_catalog_and_query_contract(tmp_path: Path) -> None:
    app = create_dashboard_wsgi_app(build_synthetic_dashboard_runtime(tmp_path))

    status, _, body = _call(app, "GET", "/")
    assert status.startswith("200")
    assert "Аналитика продаж" in body.decode("utf-8")

    status, _, body = _call(app, "GET", "/api/dashboard/runtime")
    runtime = json.loads(body)
    assert status.startswith("200")
    assert runtime["default_retailer_id"] == "retailer_a"
    assert "INCLUDE" in runtime["supported_private_label_scopes"]

    status, _, body = _call(
        app,
        "GET",
        "/api/dashboard/catalog",
        query="retailer_id=retailer_a&source_id=source_a",
    )
    catalog = json.loads(body)
    assert status.startswith("200")
    assert {"revenue", "retailer_margin_pct"} <= {
        item["metric_concept"] for item in catalog["metrics"]
    }

    status, _, body = _call(
        app,
        "GET",
        "/api/dashboard/options",
        query="retailer_id=retailer_a&source_id=source_a&private_label_scope=EXCLUDE",
    )
    options = json.loads(body)
    assert status.startswith("200")
    assert options["periods"][0]["value"] == "2025-03-01"
    assert options["periods"][-1]["value"] == "2026-06-01"
    assert options["entities"]["category"][0]["value"] == "CATEGORY_STANDARD"
    assert options["entities"]["sku"][0]["value"] == "SKU_A_001"

    status, _, body = _call(
        app,
        "GET",
        "/api/dashboard/options",
        query="retailer_id=retailer_a&source_id=source_a&private_label_scope=INCLUDE&category=CATEGORY_OTHER",
    )
    scoped_options = json.loads(body)
    assert status.startswith("200")
    assert scoped_options["entities"]["manufacturer"] == []
    assert scoped_options["entities"]["brand"] == []
    assert scoped_options["entities"]["sku"] == []

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/query",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "network",
            "entity_ids": ["network"],
            "metric_concepts": ["revenue", "retailer_margin_pct"],
            "comparison_mode": "YOY",
            "private_label_scope": "EXCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["private_label_scope"] == "EXCLUDE"
    assert response["request_scope"]["comparison_mode"] == "YOY"
    assert response["metric_definition_lineage"]
    assert response["available_periods"] == ["2026-06-01"]
    assert response["comparisons"]


def test_dashboard_range_query_returns_missing_periods_without_zero_fill(tmp_path: Path) -> None:
    app = create_dashboard_wsgi_app(build_synthetic_dashboard_runtime(tmp_path))

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/query",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2025-03-01",
            "date_to": "2025-06-01",
            "period_mode": "DATE_RANGE",
            "period_grain": "month",
            "grain_id": "network",
            "entity_ids": ["network"],
            "metric_concepts": ["revenue", "distribution"],
            "comparison_mode": "NONE",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["coverage_status"] == "PARTIAL"
    assert response["missing_periods"] == ["2025-05-01"]
    assert "2025-05-01" not in {
        item["period_start"]
        for result in response["metric_results"]
        for item in result["period_values"]
    }
    assert "range_aggregation_period_only" in {
        item["issue_code"] for item in response["limitations"]
    }


def _call(
    app: WSGIApplication,
    method: str,
    path: str,
    *,
    query: str = "",
    payload: dict[str, Any] | None = None,
) -> tuple[str, list[tuple[str, str]], bytes]:
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else b""
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: object = None) -> None:
        del exc_info
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    chunks: Iterable[bytes] = app(environ, start_response)  # type: ignore[arg-type]
    return captured["status"], captured["headers"], b"".join(chunks)
