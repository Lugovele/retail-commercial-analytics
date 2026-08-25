from __future__ import annotations

import io
import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from wsgiref.types import WSGIApplication

import polars as pl

from retail_analytics.dashboard import build_synthetic_dashboard_runtime, create_dashboard_wsgi_app
from retail_analytics.mart import DashboardMartQueryService


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


def test_dashboard_query_route_rolls_up_canonical_multi_select_filters(tmp_path: Path) -> None:
    runtime = build_synthetic_dashboard_runtime(tmp_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "GET",
        "/api/dashboard/options",
        query="retailer_id=retailer_a&source_id=source_a&private_label_scope=INCLUDE",
    )
    assert status.startswith("200")
    options = json.loads(body)
    network_id = options["entities"]["network"][0]["value"]
    category_ids = [item["value"] for item in options["entities"]["category"][:2]]

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
            "entity_ids": [network_id],
            "entity_filters": {"category": category_ids},
            "metric_concepts": ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert {item["metric_concept"] for item in response["metric_results"]} == {
        "revenue",
        "units",
        "retailer_margin_abs",
        "retailer_margin_pct",
    }
    assert response["request_scope"]["entity_filters"] == {"category": category_ids}
    assert {item["metric_definition_id"] for item in response["comparisons"]} == {
        item["lineage"]["metric_definition_id"] for item in response["metric_results"]
    }
    assert response["scope_identity_hash"]
    provenance = response["metric_results"][0]["provenance"]
    assert provenance["current_analytical_scope"]["entity_filters"] == {"category": category_ids}
    assert provenance["scoped_rollup"]["status"] == "DERIVED_FROM_FILTERED_FACTS"


def test_dashboard_query_route_resolves_cascading_source_like_filters(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = replace(build_synthetic_dashboard_runtime(tmp_path / "demo"), source_like_rows_path=source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

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
            "entity_ids": ["ALL"],
            "entity_filters": {
                "category": ["CATEGORY_STANDARD"],
                "manufacturer": ["Manufacturer A"],
                "brand": ["Brand A"],
            },
            "metric_concepts": ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert {item["metric_concept"] for item in response["metric_results"]} == {
        "revenue",
        "units",
        "retailer_margin_abs",
        "retailer_margin_pct",
    }
    assert response["request_scope"]["entity_filters"] == {"sku": ["SKU_A_001"]}
    assert response["request_scope"]["user_entity_filters"] == {
        "category": ["CATEGORY_STANDARD"],
        "manufacturer": ["Manufacturer A"],
        "brand": ["Brand A"],
    }
    assert response["comparisons"]
    provenance = response["metric_results"][0]["provenance"]
    assert provenance["current_analytical_scope"]["user_entity_filters"] == {
        "category": ["CATEGORY_STANDARD"],
        "manufacturer": ["Manufacturer A"],
        "brand": ["Brand A"],
    }
    assert provenance["current_analytical_scope"]["execution_entity_filters"] == {"sku": ["SKU_A_001"]}
    assert provenance["scoped_rollup"]["source_fact_grain"] == "sku"


def test_dashboard_contribution_route_returns_structured_rows(tmp_path: Path) -> None:
    app = create_dashboard_wsgi_app(build_synthetic_dashboard_runtime(tmp_path))

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/contribution",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "current_period": "2026-06-01",
            "reference_period": "2025-06-01",
            "period_grain": "month",
            "parent_grain_id": "network",
            "parent_entity_id": "network",
            "child_grain_id": "category",
            "metric_concept": "revenue",
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["status"] in {"READY", "TOTAL_DELTA_ZERO"}
    assert response["metric_concept"] == "revenue"
    assert response["rows"]
    assert response["rows"][0]["provenance"]["calculation"]["formula"] == "child_delta / parent_delta"
    assert response["rows"][0]["provenance"]["metric"]["parent_definition"]["metric_definition_id"]
    assert response["rows"][0]["provenance"]["metric"]["child_definition"]["metric_definition_id"]
    assert response["rows"][0]["provenance"]["run_lineage"]["mart_build_id"] == "build_dashboard_synthetic"
    assert response["rows"][0]["provenance"]["source_evidence"]["status"] == "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS"

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/contribution",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "current_period": "2026-06-01",
            "reference_period": "2025-06-01",
            "period_grain": "month",
            "parent_grain_id": "network",
            "parent_entity_id": "network",
            "child_grain_id": "category",
            "metric_concept": "retailer_margin_pct",
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    unsupported = json.loads(body)

    assert status.startswith("200")
    assert unsupported["status"] == "NOT_APPLICABLE"
    assert unsupported["rows"] == []


def test_dashboard_portfolio_market_route_returns_product_contract(tmp_path: Path) -> None:
    app = create_dashboard_wsgi_app(build_synthetic_dashboard_runtime(tmp_path))

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/portfolio-market",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "brand",
            "entity_ids": ["BRAND_A"],
            "entity_filters": {"category": ["CATEGORY_STANDARD"], "brand": ["BRAND_A"]},
            "concept_ids": [
                "category_revenue_share",
                "manufacturer_rank_revenue",
                "brand_category_delta_gap_pp",
                "broad_competitors",
            ],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["mart_build_id"] == "build_dashboard_synthetic"
    assert response["private_label_scope"] == "INCLUDE"
    assert {item["concept_id"] for item in response["items"]} == {
        "category_revenue_share",
        "manufacturer_rank_revenue",
        "brand_category_delta_gap_pp",
        "broad_competitors",
    }
    rank = next(item for item in response["items"] if item["concept_id"] == "manufacturer_rank_revenue")
    assert rank["status"] in {"READY", "PARTIAL"}
    assert rank["provenance"]["projection"]["projection_semantics"] == "competition_rank_by_summed_additive_metric"
    competitor = next(item for item in response["items"] if item["concept_id"] == "broad_competitors")
    assert competitor["status"] == "NOT_AVAILABLE"
    assert competitor["limitations"] == ["broad_competitor_projection_not_route_ready"]


def test_dashboard_signals_route_returns_empty_product_contract_without_demo_events(tmp_path: Path) -> None:
    app = create_dashboard_wsgi_app(build_synthetic_dashboard_runtime(tmp_path))

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/signals",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "network",
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["status"] == "NOT_CONFIGURED"
    assert response["signals"] == []
    assert response["deterministic_patterns"] == []
    assert response["data_quality_alerts"] == []
    assert response["capability_limitations"][0]["code"] == "signal_events_path_not_configured"
    assert response["private_label_scope"] == "INCLUDE"


def test_dashboard_data_route_returns_coverage_quality_source_rows_and_audit(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = replace(build_synthetic_dashboard_runtime(tmp_path / "demo"), source_like_rows_path=source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/data",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "network",
            "entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "comparison_mode": "NONE",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
            "limit": 1,
            "offset": 0,
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["coverage_grid"]["status"] == "READY"
    assert response["coverage_grid"]["available_periods"][0] == "2025-03-01"
    assert response["quality_summary"]["summary"] == "deterministic_checks"
    assert response["quality_summary"]["mart_build_status"] == "approved"
    assert response["source_like_rows"]["status"] == "READY"
    assert response["source_like_rows"]["limit"] == 1
    assert response["source_like_rows"]["offset"] == 0
    assert response["source_like_rows"]["total_count"] == 2
    assert response["source_like_rows"]["columns"] == [
        "period",
        "category",
        "manufacturer",
        "brand",
        "sku_name",
        "units",
        "revenue_vat",
        "private_label_flag",
    ]
    assert len(response["source_like_rows"]["rows"]) == 1
    assert response["audit"]["mart_build"]["mart_build_id"] == "build_dashboard_synthetic"
    assert response["audit"]["source_revisions"]
    assert "source_like_rows_not_configured" not in response["limitations"]


def test_dashboard_data_route_scopes_private_label_and_missing_source_like_rows(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = replace(build_synthetic_dashboard_runtime(tmp_path / "demo"), source_like_rows_path=source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/data",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "network",
            "entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "comparison_mode": "NONE",
            "private_label_scope": "EXCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["source_like_rows"]["status"] == "READY"
    assert response["source_like_rows"]["total_count"] == 1
    assert all(not row["private_label_flag"] for row in response["source_like_rows"]["rows"])

    app_without_rows = create_dashboard_wsgi_app(build_synthetic_dashboard_runtime(tmp_path / "no-source-like"))
    status, _, body = _call(
        app_without_rows,
        "POST",
        "/api/dashboard/data",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "network",
            "comparison_mode": "NONE",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    not_configured = json.loads(body)

    assert status.startswith("200")
    assert not_configured["source_like_rows"]["status"] == "NOT_CONFIGURED"
    assert "source_like_rows_not_configured" in not_configured["limitations"]


def test_dashboard_data_route_uses_current_build_revisions_for_rows_and_coverage(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = build_synthetic_dashboard_runtime(tmp_path / "demo")
    stale_entry = replace(
        runtime.query_service.source_ledger[0],
        source_revision_id="revision_dashboard_stale",
        observed_periods=(date(2024, 1, 1),),
        business_period_ids=("2024-01-01",),
        active_business_period_ids=("2024-01-01",),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 1),
        row_count=999,
        is_active_revision=False,
    )
    runtime = replace(
        runtime,
        source_like_rows_path=source_rows_path,
        query_service=DashboardMartQueryService(
            runtime.query_service.metric_facts_path,
            catalog=runtime.query_service.catalog,
            mart_builds=runtime.query_service.mart_builds,
            source_ledger=(*runtime.query_service.source_ledger, stale_entry),
        ),
    )
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/data",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "network",
            "entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "comparison_mode": "NONE",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
            "limit": 10,
            "offset": 0,
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert "2024-01-01" not in response["coverage_grid"]["available_periods"]
    assert response["source_like_rows"]["total_count"] == 2
    assert {
        row["source_revision_id"]
        for row in response["source_like_rows"]["rows"]
        if "source_revision_id" in row
    } == set()


def _write_source_like_rows(path: Path) -> Path:
    pl.DataFrame(
        {
            "retailer_id": ["retailer_a", "retailer_a", "retailer_a", "retailer_b"],
            "source_id": ["source_a", "source_a", "source_a", "source_b"],
            "source_revision_id": [
                "revision_dashboard_synthetic",
                "revision_dashboard_synthetic",
                "revision_dashboard_stale",
                "revision_dashboard_synthetic",
            ],
            "period": ["2026-06-01", "2026-06-01", "2026-06-01", "2026-06-01"],
            "category": ["CATEGORY_STANDARD", "CATEGORY_STANDARD", "CATEGORY_STANDARD", "CATEGORY_STANDARD"],
            "manufacturer": ["Manufacturer A", "Manufacturer B", "Manufacturer Stale", "Manufacturer X"],
            "brand": ["Brand A", "Brand B", "Brand Stale", "Brand X"],
            "sku_name": ["SKU A", "SKU B", "SKU Stale", "SKU X"],
            "canonical_product_id": ["SKU_A_001", "SKU_B_001", "SKU_STALE", "SKU_X_001"],
            "canonical_store_id": ["STORE_001", "STORE_002", "STORE_STALE", "STORE_X"],
            "units": [10.0, 5.0, 999.0, 99.0],
            "revenue_vat": [100.0, 50.0, 9990.0, 990.0],
            "private_label_flag": [False, True, False, False],
        }
    ).write_parquet(path)
    return path


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
