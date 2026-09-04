from __future__ import annotations

import importlib
import io
import json
import os
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from wsgiref.types import WSGIApplication

import polars as pl
import pytest

from retail_analytics.dashboard import build_synthetic_dashboard_runtime, create_dashboard_wsgi_app
from retail_analytics.dashboard.app import _asset_version
from retail_analytics.dashboard.diagnostics import DiagnosticsService, build_diagnostics_request
from retail_analytics.mart import (
    DashboardMartQueryService,
    PortfolioMarketService,
    build_product_store_metric_facts,
    write_product_store_metric_facts,
)


def test_dashboard_filter_apply_updates_rendered_kpi_when_browser_url_is_provided() -> None:
    dashboard_url = os.environ.get("DASHBOARD_E2E_URL")
    if not dashboard_url:
        return
    try:
        sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        return

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(dashboard_url, wait_until="networkidle")
            page.wait_for_selector(".kpi-card")
            before = [card.inner_text() for card in page.locator(".kpi-card").all()[:4]]

            page.locator("#category-filter-trigger").click()
            page.locator("#category-options .filter-option").first.click()
            page.locator('[data-apply-filter="category"]').click()
            page.wait_for_function(
                """(beforeValues) => {
                    const cards = Array.from(document.querySelectorAll(".kpi-card")).slice(0, 4);
                    if (cards.length < 4) return false;
                    return JSON.stringify(cards.map((card) => card.innerText)) !== JSON.stringify(beforeValues);
                }""",
                arg=before,
                timeout=15000,
            )

            after = [card.inner_text() for card in page.locator(".kpi-card").all()[:4]]
            selected = page.locator("#category-filter-trigger").inner_text()

            assert selected != "Все"
            assert before != after
            assert "Недоступно" not in "\n".join(after)

            page.locator('[data-view="stores"]').click()
            page.wait_for_selector("#stores-table")
            page.wait_for_function(
                """() => {
                    const text = document.querySelector("#stores-table")?.innerText || "";
                    return text.includes("Оборот") && !text.includes("разреза по выбранным продуктным фильтрам");
                }""",
                timeout=15000,
            )
            assert "Разрез ТТ внутри выбранной категории" not in page.locator("#stores").inner_text()
        finally:
            browser.close()



def test_dashboard_package_scope_refresh_exits_loading_when_browser_url_is_provided() -> None:
    dashboard_url = os.environ.get("DASHBOARD_E2E_URL")
    if not dashboard_url:
        return
    try:
        sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        return

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(dashboard_url, wait_until="domcontentloaded")
            _wait_overview_ready(page, timeout=60000)
            page.locator("#package-filter-trigger").click()
            page.wait_for_selector("#package-filter-popover:not(.is-hidden)", timeout=10000)
            page.locator("#package-filter-popover .filter-option", has_text="пэт").first.click()
            page.locator('[data-apply-filter="package"]').click()
            _wait_overview_refreshing(page, timeout=10000)
            _wait_overview_ready(page, timeout=30000)

            state = _overview_loading_state(page)
            assert state["ariaBusy"] == "false"
            assert state["loaderText"] == ""
            assert state["progressHidden"] is True
            assert state["verticalOverflow"] == 0
            assert state["horizontalOverflow"] == 0
            assert state["kpiCount"] == 11
            assert state["filters"]["Тара"] == "пэт"
        finally:
            browser.close()


def test_dashboard_cascade_filters_retain_valid_downstream_values_when_browser_url_is_provided() -> None:
    dashboard_url = os.environ.get("DASHBOARD_E2E_URL")
    if not dashboard_url:
        return
    try:
        sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        return

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(dashboard_url, wait_until="domcontentloaded")
            _wait_overview_ready(page, timeout=60000)
            page.evaluate(
                """() => {
                    const originalFetch = window.fetch.bind(window);
                    window.__overviewQueryPayloads = [];
                    window.__dashboardFetchCounts = { options: 0, overviewQuery: 0 };
                    window.fetch = async (input, init = {}) => {
                        const url = typeof input === "string" ? input : input.url;
                        if (url.includes("/api/dashboard/options")) {
                            window.__dashboardFetchCounts.options += 1;
                        }
                        if (url.includes("/api/dashboard/query") && init.method === "POST") {
                            window.__dashboardFetchCounts.overviewQuery += 1;
                            window.__overviewQueryPayloads.push(JSON.parse(init.body || "{}"));
                        }
                        return originalFetch(input, init);
                    };
                }"""
            )
            scenario = page.evaluate(
                """async () => {
                    const runtime = await fetch("/api/dashboard/runtime").then((response) => response.json());
                    const retailer = runtime.retailers.find(
                        (item) => item.retailer_id === runtime.default_retailer_id
                    ) || runtime.retailers[0];
                    const baseParams = new URLSearchParams({
                        retailer_id: retailer.retailer_id,
                        source_id: retailer.source_id,
                        private_label_scope: "INCLUDE",
                        period_mode: "COMPARE"
                    });
                    const options = await fetch(`/api/dashboard/options?${baseParams}`).then((response) => response.json());
                    const packages = options.entities.package || [];
                    const manufacturers = options.entities.manufacturer || [];
                    for (const manufacturer of manufacturers) {
                        const scopedParams = new URLSearchParams(baseParams);
                        scopedParams.append("manufacturer", manufacturer.value);
                        const scoped = await fetch(`/api/dashboard/options?${scopedParams}`).then((response) => response.json());
                        const packageValues = new Set((scoped.entities.package || []).map((item) => item.value));
                        const sku = (scoped.entities.sku || [])[0];
                        const preferredPet = packages.find((item) =>
                            packageValues.has(item.value)
                            && `${item.label} ${item.display_name || ""}`.toLocaleLowerCase("ru-RU").includes("пэт")
                        );
                        const validPackage = preferredPet || packages.find((item) => packageValues.has(item.value));
                        const invalidPackage = packages.find((item) => !packageValues.has(item.value));
                        if (validPackage && invalidPackage && sku) {
                            return {
                                manufacturer: manufacturer.value,
                                validPackage: validPackage.value,
                                invalidPackage: invalidPackage.value,
                                sku: sku.value
                            };
                        }
                    }
                    return null;
                }"""
            )
            if not scenario:
                pytest.skip("dashboard data has no valid/invalid package cascade scenario")

            _select_filter_value(page, "package", scenario["validPackage"])
            _apply_filter_and_wait(page, "package")
            _select_filter_value(page, "manufacturer", scenario["manufacturer"])
            _apply_filter_and_wait(page, "manufacturer")

            assert _selected_filter_values(page, "package") == [scenario["validPackage"]]
            assert _last_overview_query_payload(page)["entity_filters"]["package"] == [scenario["validPackage"]]

            _reset_filters_and_wait(page)
            _select_filter_value(page, "package", scenario["invalidPackage"])
            _apply_filter_and_wait(page, "package")
            _select_filter_value(page, "manufacturer", scenario["manufacturer"])
            _apply_filter_and_wait(page, "manufacturer")

            assert _selected_filter_values(page, "package") == []
            assert "package" not in _last_overview_query_payload(page).get("entity_filters", {})

            _reset_filters_and_wait(page)
            _select_filter_value(page, "package", scenario["validPackage"])
            _select_filter_value(page, "package", scenario["invalidPackage"])
            _apply_filter_and_wait(page, "package")
            _select_filter_value(page, "manufacturer", scenario["manufacturer"])
            _apply_filter_and_wait(page, "manufacturer")

            assert _selected_filter_values(page, "package") == [scenario["validPackage"]]

            _reset_filters_and_wait(page)
            _select_filter_value(page, "sku", scenario["sku"])
            _apply_filter_and_wait(page, "sku")
            _select_filter_value(page, "manufacturer", scenario["manufacturer"])
            _apply_filter_and_wait(page, "manufacturer")

            assert _selected_filter_values(page, "sku") == [scenario["sku"]]
            assert _last_overview_query_payload(page)["entity_filters"]["sku"] == [scenario["sku"]]

            _reset_filters_and_wait(page)
            assert _selected_filter_values(page, "manufacturer") == []
            assert _selected_filter_values(page, "package") == []
            assert _selected_filter_values(page, "sku") == []
            assert page.locator("#overview").get_attribute("aria-busy") == "false"
            assert page.evaluate("() => window.__dashboardFetchCounts.options") <= 18
        finally:
            browser.close()


def test_dashboard_scope_refresh_failure_clears_loading_when_browser_url_is_provided() -> None:
    dashboard_url = os.environ.get("DASHBOARD_E2E_URL")
    if not dashboard_url:
        return
    try:
        sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        return

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(dashboard_url, wait_until="domcontentloaded")
            _wait_overview_ready(page, timeout=60000)
            page.evaluate(
                """() => {
                    const originalFetch = window.fetch.bind(window);
                    window.fetch = (input, init = {}) => {
                        const url = typeof input === "string" ? input : input.url;
                        if (url.includes("/api/dashboard/query") && init.method === "POST") {
                            return new Promise((_, reject) => {
                                window.setTimeout(
                                    () => reject(new Error("simulated overview query failure")),
                                    250
                                );
                            });
                        }
                        return originalFetch(input, init);
                    };
                }"""
            )
            page.locator("#package-filter-trigger").click()
            page.wait_for_selector("#package-filter-popover:not(.is-hidden)", timeout=10000)
            page.locator("#package-filter-popover .filter-option", has_text="ж/б").first.click()
            page.locator('[data-apply-filter="package"]').click()
            _wait_overview_refreshing(page, timeout=10000)
            _wait_overview_ready(page, timeout=15000)

            state = _overview_loading_state(page)
            assert state["ariaBusy"] == "false"
            assert state["loaderText"] == ""
            assert state["progressHidden"] is True
            assert "Предыдущий срез сохран" in state["chartFootnote"]
            assert state["kpiCount"] == 11
        finally:
            browser.close()


def _wait_overview_ready(page: Any, *, timeout: int) -> None:
    page.wait_for_function(
        """() => {
            const overview = document.getElementById("overview");
            return overview
                && !overview.classList.contains("is-overview-initial-loading")
                && !overview.classList.contains("is-overview-scope-refreshing")
                && !overview.classList.contains("is-overview-chart-refreshing")
                && !document.querySelector(".overview-chart-loader");
        }""",
        timeout=timeout,
    )


def _wait_overview_refreshing(page: Any, *, timeout: int) -> None:
    page.wait_for_function(
        """() => {
            const overview = document.getElementById("overview");
            return overview?.getAttribute("aria-busy") === "true"
                || overview?.classList.contains("is-overview-scope-refreshing");
        }""",
        timeout=timeout,
    )


def _overview_loading_state(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const overview = document.getElementById("overview");
            const filters = Object.fromEntries(Array.from(document.querySelectorAll(".scope-field")).map((node) => [
                (node.querySelector(".scope-label")?.textContent || "").trim(),
                (node.querySelector(".filter-summary, .scope-value")?.textContent || "").trim(),
            ]));
            return {
                overviewClass: overview?.className || "",
                ariaBusy: overview?.getAttribute("aria-busy") || "",
                loaderText: document.querySelector(".overview-chart-loader")?.innerText || "",
                progressHidden: document.getElementById("overview-refresh-progress")?.classList.contains("is-hidden"),
                chartFootnote: document.getElementById("chart-footnote")?.innerText || "",
                verticalOverflow: document.documentElement.scrollHeight - document.documentElement.clientHeight,
                horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                kpiCount: document.querySelectorAll(".kpi-card").length,
                filters,
            };
        }"""
    )


def _select_filter_value(page: Any, filter_id: str, value: str) -> None:
    popover = page.locator(f"#{filter_id}-filter-popover")
    if "is-hidden" in (popover.get_attribute("class") or ""):
        page.locator(f"#{filter_id}-filter-trigger").click()
        page.wait_for_selector(f"#{filter_id}-filter-popover:not(.is-hidden)", timeout=10000)
    option_locator = page.locator(
        f"#{filter_id}-options [data-value=\"{_css_attr_value(value)}\"] input"
    ).first
    if option_locator.count() == 0:
        page.locator(f"#{filter_id}-search").fill(value)
        page.wait_for_selector(
            f"#{filter_id}-options [data-value=\"{_css_attr_value(value)}\"] input",
            timeout=10000,
        )
    option_locator.click()


def _apply_filter_and_wait(page: Any, filter_id: str) -> None:
    before_payload_count = page.evaluate("() => window.__overviewQueryPayloads?.length || 0")
    page.locator(f'[data-apply-filter="{filter_id}"]').click()
    _wait_overview_refreshing(page, timeout=10000)
    _wait_overview_ready(page, timeout=30000)
    page.wait_for_function(
        "(count) => (window.__overviewQueryPayloads?.length || 0) > count",
        arg=before_payload_count,
        timeout=10000,
    )


def _reset_filters_and_wait(page: Any) -> None:
    before_payload_count = page.evaluate("() => window.__overviewQueryPayloads?.length || 0")
    page.locator("#reset-filters").click()
    _wait_overview_refreshing(page, timeout=10000)
    _wait_overview_ready(page, timeout=30000)
    page.wait_for_function(
        "(count) => (window.__overviewQueryPayloads?.length || 0) > count",
        arg=before_payload_count,
        timeout=10000,
    )


def _selected_filter_values(page: Any, filter_id: str) -> list[str]:
    return page.eval_on_selector(
        f"#{filter_id}-filter",
        "(select) => Array.from(select.selectedOptions).map((option) => option.value)",
    )


def _last_overview_query_payload(page: Any) -> dict[str, Any]:
    return page.evaluate("() => window.__overviewQueryPayloads.at(-1)")


def _css_attr_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def test_dashboard_wsgi_runtime_catalog_and_query_contract(tmp_path: Path) -> None:
    app = create_dashboard_wsgi_app(build_synthetic_dashboard_runtime(tmp_path))

    status, _, body = _call(app, "GET", "/")
    assert status.startswith("200")
    html = body.decode("utf-8")
    asset_version = _asset_version()
    assert "Аналитика продаж" in html
    assert f"/static/app.js?v={asset_version}" in html
    assert f"/static/styles.css?v={asset_version}" in html

    status, headers, body = _call(app, "GET", "/static/app.js")
    assert status.startswith("200")
    assert body
    assert ("Cache-Control", "no-cache") in headers

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
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
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


def test_dashboard_sku_options_respect_selected_store_scope(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "GET",
        "/api/dashboard/options",
        query=(
            "retailer_id=retailer_a&source_id=source_a&private_label_scope=INCLUDE"
            "&date_from=2026-06-01&date_to=2026-06-01"
            "&category=CATEGORY_STANDARD&store=STORE_001"
        ),
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert [item["value"] for item in response["entities"]["sku"]] == ["SKU_A_001"]


def test_dashboard_product_routes_resolve_and_report_user_execution_filters(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
    app = create_dashboard_wsgi_app(runtime)
    base_payload: dict[str, Any] = {
        "retailer_id": "retailer_a",
        "source_id": "source_a",
        "date_from": "2026-06-01",
        "date_to": "2026-06-01",
        "period_mode": "SINGLE_PERIOD",
        "period_grain": "month",
        "grain_id": "network",
        "entity_filters": {
            "category": ["CATEGORY_STANDARD"],
            "manufacturer": ["Manufacturer A"],
            "brand": ["Brand A"],
        },
        "comparison_mode": "YOY",
        "private_label_scope": "INCLUDE",
        "mart_build_id": "build_dashboard_synthetic",
    }
    expected_user_filters = {
        "category": ["CATEGORY_STANDARD"],
        "manufacturer": ["Manufacturer A"],
        "brand": ["Brand A"],
    }

    portfolio_status, _, portfolio_body = _call(
        app,
        "POST",
        "/api/dashboard/portfolio-market",
        payload={**base_payload, "concept_ids": ["active_sku_count"]},
    )
    portfolio = json.loads(portfolio_body)

    assert portfolio_status.startswith("200")
    assert portfolio["request_scope"]["user_entity_filters"] == expected_user_filters
    assert portfolio["request_scope"]["execution_entity_filters"] == {"sku": ["SKU_A_001"]}
    assert portfolio["items"][0]["provenance"]["current_analytical_scope"]["user_entity_filters"] == expected_user_filters
    assert portfolio["items"][0]["provenance"]["current_analytical_scope"]["execution_entity_filters"] == {
        "sku": ["SKU_A_001"]
    }

    signals_status, _, signals_body = _call(
        app,
        "POST",
        "/api/dashboard/signals",
        payload={**base_payload, "signal_types": ["COMMERCIAL_SIGNAL"]},
    )
    signals = json.loads(signals_body)

    assert signals_status.startswith("200")
    assert signals["request_scope"]["user_entity_filters"] == expected_user_filters
    assert signals["request_scope"]["execution_entity_filters"] == {"sku": ["SKU_A_001"]}

    data_status, _, data_body = _call(
        app,
        "POST",
        "/api/dashboard/data",
        payload={**base_payload, "comparison_mode": "NONE", "limit": 10, "offset": 0},
    )
    data = json.loads(data_body)

    assert data_status.startswith("200")
    assert data["request_scope"]["user_entity_filters"] == expected_user_filters
    assert data["request_scope"]["execution_entity_filters"] == {"sku": ["SKU_A_001"]}
    assert data["audit"]["user_entity_filters"] == expected_user_filters
    assert data["audit"]["execution_entity_filters"] == {"sku": ["SKU_A_001"]}
    assert data["source_like_rows"]["total_count"] == 1


def test_dashboard_active_sku_selected_sku_store_scope_uses_source_like_truth(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = build_synthetic_dashboard_runtime(tmp_path / "demo")
    runtime = replace(
        runtime,
        source_like_rows_path=source_rows_path,
        query_service=DashboardMartQueryService(
            runtime.query_service.metric_facts_path,
            catalog=runtime.query_service.catalog,
            mart_builds=runtime.query_service.mart_builds,
            source_ledger=runtime.query_service.source_ledger,
            source_like_rows_path=source_rows_path,
        ),
    )
    app = create_dashboard_wsgi_app(runtime)

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
            "grain_id": "manufacturer",
            "entity_ids": [],
            "entity_filters": {
                "category": ["CATEGORY_STANDARD"],
                "manufacturer": ["Manufacturer A"],
                "brand": ["Brand A"],
                "sku": ["SKU_A_001"],
                "store": ["STORE_001"],
            },
            "concept_ids": ["active_sku_count"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    item = response["items"][0]
    assert item["status"] == "PARTIAL"
    assert item["current_value"] == 1
    assert item["value"] == 1
    assert item["limitations"] == ["comparison_period_unavailable"]


def test_dashboard_diagnostics_route_binds_real_query_metric_rows(tmp_path: Path) -> None:
    source_rows_path = _write_product_store_source_like_rows(tmp_path / "source_like_enriched.parquet")
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/diagnostics",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "selected_metric": "units",
            "breakdown_grain": "category",
            "summary_grain": "network",
            "summary_entity_ids": ["network"],
            "entity_filters": {},
            "metric_concepts": ["units", "revenue_vat", "active_sku_count"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["selected_metric"] == "units"
    assert response["breakdown_level"] == "category"
    assert response["entity_count"] >= 1
    standard = next(item for item in response["entities"] if item["stable_entity_id"] == "CATEGORY_STANDARD")
    assert standard["selected_metric"]["current_value"] is not None
    assert standard["metrics"]["units"]["status"] in {"READY", "PARTIAL"}
    assert standard["metrics"]["active_sku_count"]["current_value"] == 2
    assert response["summary"]["metrics"]["active_sku_count"]["status"] in {"READY", "PARTIAL"}


def test_dashboard_diagnostics_active_sku_narrow_scope_returns_one(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/diagnostics",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "selected_metric": "active_sku_count",
            "breakdown_grain": "sku",
            "summary_grain": "sku",
            "summary_entity_ids": ["SKU_A_001"],
            "entity_filters": {
                "category": ["CATEGORY_STANDARD"],
                "manufacturer": ["Manufacturer A"],
                "brand": ["Brand A"],
                "sku": ["SKU_A_001"],
                "store": ["STORE_001"],
            },
            "metric_concepts": ["active_sku_count", "units"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["entity_count"] == 1
    row = response["entities"][0]
    assert row["stable_entity_id"] == "SKU_A_001"
    assert row["selected_metric"]["current_value"] == 1
    assert response["summary"]["metrics"]["active_sku_count"]["current_value"] == 1


def test_dashboard_diagnostics_source_like_kpis_keep_local_breakdown_grain(tmp_path: Path) -> None:
    source_rows_path = _write_product_store_source_like_rows(tmp_path / "source_like_enriched.parquet")
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
    diagnostics_service = DiagnosticsService(
        runtime.query_service,
        PortfolioMarketService(runtime.query_service),
        source_like_rows_path=source_rows_path,
    )

    response = diagnostics_service.query(
        build_diagnostics_request(
            {
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "selected_metric": "velocity",
            "breakdown_grain": "brand",
            "summary_grain": "category",
            "summary_entity_ids": [],
            "entity_filters": {"sku": ["SKU_A_001"]},
            "user_entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "metric_concepts": ["velocity", "distribution"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
            }
        )
    )

    by_id = {item["stable_entity_id"]: item for item in response["entities"]}
    assert set(by_id) == {"Brand A", "Brand B"}
    assert by_id["Brand A"]["metrics"]["velocity"]["current_value"] == 8.0
    assert by_id["Brand A"]["metrics"]["velocity"]["numerator_value"] == 8.0
    assert by_id["Brand A"]["metrics"]["velocity"]["denominator_value"] == 1.0
    assert by_id["Brand B"]["metrics"]["velocity"]["current_value"] == 5.0
    assert by_id["Brand A"]["metrics"]["distribution"]["current_value"] == 0.5
    assert by_id["Brand B"]["metrics"]["distribution"]["current_value"] == 0.5


def test_dashboard_diagnostics_source_like_kpis_reject_unproductized_range_period(
    tmp_path: Path,
) -> None:
    source_rows_path = _write_product_store_source_like_rows(tmp_path / "source_like_enriched.parquet")
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/diagnostics",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2025-06-01",
            "date_to": "2026-06-01",
            "period_mode": "DATE_RANGE",
            "period_grain": "month",
            "selected_metric": "velocity",
            "breakdown_grain": "brand",
            "summary_grain": "network",
            "summary_entity_ids": ["network"],
            "entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "metric_concepts": ["velocity", "active_sku_count"],
            "comparison_mode": "NONE",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    row = next(item for item in response["entities"] if item["stable_entity_id"] == "Brand A")
    assert row["metrics"]["velocity"]["status"] == "NEEDS_BUSINESS_RULE"
    assert row["metrics"]["velocity"]["current_value"] is None
    assert "date_range_period_not_productized" in row["metrics"]["velocity"]["reason"]
    assert row["metrics"]["active_sku_count"]["status"] == "NEEDS_BUSINESS_RULE"


def test_dashboard_diagnostics_stm_exclude_matches_overview_null_scope(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows_with_null_private_label(tmp_path / "source_like_null_stm.parquet")
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/diagnostics",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "selected_metric": "active_sku_count",
            "breakdown_grain": "sku",
            "summary_grain": "network",
            "summary_entity_ids": ["network"],
            "entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "metric_concepts": ["active_sku_count"],
            "comparison_mode": "NONE",
            "private_label_scope": "EXCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert [item["stable_entity_id"] for item in response["entities"]] == ["SKU_FALSE", "SKU_NULL"]
    assert {item["selected_metric"]["current_value"] for item in response["entities"]} == {1}


def test_dashboard_diagnostics_preserves_duplicate_sku_identities(tmp_path: Path) -> None:
    source_rows_path = _write_duplicate_diagnostics_source_like_rows(tmp_path / "diagnostics_duplicates.parquet")
    runtime = _runtime_with_source_like(tmp_path / "demo", source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/diagnostics",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "selected_metric": "active_sku_count",
            "breakdown_grain": "sku",
            "summary_grain": "category",
            "summary_entity_ids": ["COLA"],
            "entity_filters": {"category": ["COLA"]},
            "metric_concepts": ["active_sku_count"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    ids = [item["stable_entity_id"] for item in response["entities"]]
    assert ids == ["706913", "756771", "940211"]
    assert len({item["display_label"] for item in response["entities"]}) == 3
    assert all("НАПИТОК КОКА-КОЛА ОРИДЖИНАЛ Ж/Б 0,33Л" in item["display_label"] for item in response["entities"])
    assert {item["selected_metric"]["current_value"] for item in response["entities"]} == {1}


def test_dashboard_diagnostics_returns_explicit_unsupported_status(tmp_path: Path) -> None:
    source_rows_path = _write_source_like_rows(tmp_path / "source_like.parquet")
    runtime = replace(build_synthetic_dashboard_runtime(tmp_path / "demo"), source_like_rows_path=source_rows_path)
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/diagnostics",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "selected_metric": "weighted_distribution",
            "breakdown_grain": "manufacturer",
            "summary_grain": "network",
            "summary_entity_ids": ["network"],
            "entity_filters": {},
            "metric_concepts": ["weighted_distribution"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    assert response["support_matrix"]["weighted_distribution"]["manufacturer"] == "NEEDS_BUSINESS_RULE"
    assert response["entities"][0]["selected_metric"]["status"] == "NEEDS_BUSINESS_RULE"


def test_dashboard_query_route_uses_product_store_serving_for_store_and_product_filters(tmp_path: Path) -> None:
    source_rows_path = _write_product_store_source_like_rows(tmp_path / "source_like_enriched.parquet")
    runtime = build_synthetic_dashboard_runtime(tmp_path / "demo")
    build = runtime.query_service.mart_builds[0]
    product_store_path = tmp_path / "product_store.parquet"
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            pl.read_parquet(source_rows_path),
            build_metadata=build,
            source_revision_id=build.source_revision_ids[0],
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    runtime = replace(
        runtime,
        source_like_rows_path=source_rows_path,
        product_store_facts_path=product_store_path,
        query_service=DashboardMartQueryService(
            runtime.query_service.metric_facts_path,
            catalog=runtime.query_service.catalog,
            mart_builds=runtime.query_service.mart_builds,
            source_ledger=runtime.query_service.source_ledger,
            product_store_facts_path=product_store_path,
        ),
    )
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
            "entity_ids": ["network"],
            "entity_filters": {"category": ["CATEGORY_STANDARD"], "store": ["STORE_001"]},
            "metric_concepts": ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    values = {item["metric_concept"]: item["value"] for item in response["metric_results"]}
    assert values == {
        "revenue": 80.0,
        "units": 8.0,
        "retailer_margin_abs": 20.0,
        "retailer_margin_pct": 0.25,
    }
    assert response["request_scope"]["user_entity_filters"] == {
        "category": ["CATEGORY_STANDARD"],
        "store": ["STORE_001"],
    }
    assert response["request_scope"]["entity_filters"] == {"category": ["CATEGORY_STANDARD"], "store": ["STORE_001"]}
    provenance = response["metric_results"][0]["provenance"]
    assert provenance["scoped_rollup"]["status"] == "DERIVED_FROM_PRODUCT_STORE_FACTS"
    assert provenance["scoped_rollup"]["source_fact_grain"] == "sku_store"
    assert provenance["current_analytical_scope"]["execution_entity_filters"] == {
        "category": ["CATEGORY_STANDARD"],
        "store": ["STORE_001"],
    }


def test_dashboard_routes_apply_package_and_volume_global_filters(tmp_path: Path) -> None:
    source_rows_path = _write_product_store_source_like_rows(tmp_path / "source_like_enriched.parquet")
    runtime = build_synthetic_dashboard_runtime(tmp_path / "demo")
    build = runtime.query_service.mart_builds[0]
    product_store_path = tmp_path / "product_store.parquet"
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            pl.read_parquet(source_rows_path),
            build_metadata=build,
            source_revision_id=build.source_revision_ids[0],
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    runtime = replace(
        runtime,
        source_like_rows_path=source_rows_path,
        product_store_facts_path=product_store_path,
        query_service=DashboardMartQueryService(
            runtime.query_service.metric_facts_path,
            catalog=runtime.query_service.catalog,
            mart_builds=runtime.query_service.mart_builds,
            source_ledger=runtime.query_service.source_ledger,
            source_like_rows_path=source_rows_path,
            product_store_facts_path=product_store_path,
        ),
    )
    app = create_dashboard_wsgi_app(runtime)

    options_status, _, options_body = _call(
        app,
        "GET",
        "/api/dashboard/options",
        query=(
            "retailer_id=retailer_a&source_id=source_a&private_label_scope=INCLUDE"
            "&category=CATEGORY_STANDARD&brand=Brand%20A&package=PACK_A"
        ),
    )
    options = json.loads(options_body)

    assert options_status.startswith("200")
    assert [item["value"] for item in options["entities"]["package"]] == ["PACK_A"]
    assert [(item["value"], item["label"], item["display_name"]) for item in options["entities"]["volume"]] == [
        ("0.5", "0,5 л", "0,5 л")
    ]
    assert [
        (item["value"], item["label"], item["sku_count"], item["exact_value_count"])
        for item in options["facets"]["volume"]["ranges"]
    ] == [("volume_range:gt_0_25_le_0_50", "> 0,25–0,50 л", 1, 1)]
    assert [item["value"] for item in options["entities"]["sku"]] == ["SKU_A_001"]

    filters = {"category": ["CATEGORY_STANDARD"], "package": ["PACK_A"], "volume": ["0.5"]}
    query_status, _, query_body = _call(
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
            "entity_filters": filters,
            "metric_concepts": ["revenue", "units"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    query_response = json.loads(query_body)

    assert query_status.startswith("200")
    values = {item["metric_concept"]: item["value"] for item in query_response["metric_results"]}
    assert values == {"revenue": 80.0, "units": 8.0}
    assert query_response["request_scope"]["user_entity_filters"] == filters
    assert query_response["request_scope"]["entity_filters"] == filters
    assert query_response["metric_results"][0]["provenance"]["current_analytical_scope"][
        "execution_entity_filters"
    ] == filters

    portfolio_status, _, portfolio_body = _call(
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
            "grain_id": "network",
            "entity_ids": ["network"],
            "entity_filters": filters,
            "concept_ids": ["active_sku_count"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    portfolio_response = json.loads(portfolio_body)

    assert portfolio_status.startswith("200")
    active_sku = portfolio_response["items"][0]
    assert active_sku["current_value"] == 1
    assert active_sku["reference_value"] == 1
    assert active_sku["provenance"]["current_analytical_scope"]["user_entity_filters"] == filters
    assert active_sku["provenance"]["current_analytical_scope"]["execution_entity_filters"] == filters

    range_filters = {"category": ["CATEGORY_STANDARD"], "package": ["PACK_A"], "volume": ["volume_range:gt_0_25_le_0_50"]}
    range_status, _, range_body = _call(
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
            "entity_filters": range_filters,
            "metric_concepts": ["revenue", "units"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    range_response = json.loads(range_body)

    assert range_status.startswith("200")
    assert {item["metric_concept"]: item["value"] for item in range_response["metric_results"]} == values

    range_portfolio_status, _, range_portfolio_body = _call(
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
            "grain_id": "network",
            "entity_ids": ["network"],
            "entity_filters": range_filters,
            "concept_ids": ["active_sku_count"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    range_portfolio_response = json.loads(range_portfolio_body)

    assert range_portfolio_status.startswith("200")
    assert range_portfolio_response["items"][0]["current_value"] == active_sku["current_value"]
    assert range_portfolio_response["items"][0]["reference_value"] == active_sku["reference_value"]


def test_dashboard_geography_route_returns_region_grouping_from_product_store_serving(tmp_path: Path) -> None:
    source_rows_path = _write_product_store_source_like_rows(tmp_path / "source_like_enriched.parquet")
    runtime = build_synthetic_dashboard_runtime(tmp_path / "demo")
    build = runtime.query_service.mart_builds[0]
    product_store_path = tmp_path / "product_store.parquet"
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            pl.read_parquet(source_rows_path),
            build_metadata=build,
            source_revision_id=build.source_revision_ids[0],
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    runtime = replace(
        runtime,
        source_like_rows_path=source_rows_path,
        product_store_facts_path=product_store_path,
        query_service=DashboardMartQueryService(
            runtime.query_service.metric_facts_path,
            catalog=runtime.query_service.catalog,
            mart_builds=runtime.query_service.mart_builds,
            source_ledger=runtime.query_service.source_ledger,
            product_store_facts_path=product_store_path,
        ),
    )
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/geography",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grouping": "region",
            "entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "metric_concepts": ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    values = {(item["entity_id"], item["metric_concept"]): item["value"] for item in response["metric_results"]}
    assert values[("region_a", "revenue")] == 80.0
    assert values[("region_b", "revenue")] == 50.0
    assert values[("region_a", "retailer_margin_pct")] == 0.25
    assert response["request_scope"]["user_entity_filters"] == {"category": ["CATEGORY_STANDARD"]}
    assert response["request_scope"]["execution_entity_filters"] == {"category": ["CATEGORY_STANDARD"]}
    assert response["metric_results"][0]["provenance"]["guardrails"]["fo2_exposed"] is False
    assert response["metric_results"][0]["provenance"]["guardrails"]["territory_exposed"] is False

    range_status, _, range_body = _call(
        app,
        "POST",
        "/api/dashboard/geography",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grouping": "region",
            "entity_filters": {"category": ["CATEGORY_STANDARD"], "volume": ["volume_range:gt_0_25_le_0_50"]},
            "metric_concepts": ["revenue", "units"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    range_response = json.loads(range_body)

    assert range_status.startswith("200")
    range_values = {
        (item["entity_id"], item["metric_concept"]): item["value"]
        for item in range_response["metric_results"]
    }
    assert range_values == {("region_a", "revenue"): 80.0, ("region_a", "units"): 8.0}


def test_dashboard_package_volume_route_returns_mix_from_canonical_attributes(tmp_path: Path) -> None:
    source_rows_path = _write_product_store_source_like_rows(tmp_path / "source_like_enriched.parquet")
    runtime = build_synthetic_dashboard_runtime(tmp_path / "demo")
    build = runtime.query_service.mart_builds[0]
    product_store_path = tmp_path / "product_store.parquet"
    write_product_store_metric_facts(
        build_product_store_metric_facts(
            pl.read_parquet(source_rows_path),
            build_metadata=build,
            source_revision_id=build.source_revision_ids[0],
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        product_store_path,
    )
    runtime = replace(
        runtime,
        source_like_rows_path=source_rows_path,
        product_store_facts_path=product_store_path,
        query_service=DashboardMartQueryService(
            runtime.query_service.metric_facts_path,
            catalog=runtime.query_service.catalog,
            mart_builds=runtime.query_service.mart_builds,
            source_ledger=runtime.query_service.source_ledger,
            product_store_facts_path=product_store_path,
        ),
    )
    app = create_dashboard_wsgi_app(runtime)

    status, _, body = _call(
        app,
        "POST",
        "/api/dashboard/package-volume",
        payload={
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grouping": "package",
            "basis_metric": "revenue",
            "entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "metric_concepts": ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"],
            "comparison_mode": "YOY",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        },
    )
    response = json.loads(body)

    assert status.startswith("200")
    rows = {row["entity_id"]: row for row in response["rows"]}
    assert rows["PACK_A"]["metric_value"] == 80.0
    assert rows["PACK_B"]["metric_value"] == 50.0
    assert rows["PACK_A"]["share"] == pytest.approx(80.0 / 130.0)
    assert rows["PACK_A"]["reference_metric_value"] == 60.0
    assert rows["PACK_A"]["provenance"]["guardrails"]["package_abc_exposed"] is False
    assert rows["PACK_A"]["provenance"]["guardrails"]["flavor_inferred"] is False
    assert response["request_scope"]["user_entity_filters"] == {"category": ["CATEGORY_STANDARD"]}
    assert response["request_scope"]["execution_entity_filters"] == {"category": ["CATEGORY_STANDARD"]}


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



def _write_product_store_source_like_rows(path: Path) -> Path:
    pl.DataFrame(
        {
            "retailer_id": ["retailer_a", "retailer_a", "retailer_a", "retailer_a"],
            "source_id": ["source_a", "source_a", "source_a", "source_a"],
            "source_revision_id": [
                "revision_dashboard_synthetic",
                "revision_dashboard_synthetic",
                "revision_dashboard_synthetic",
                "revision_dashboard_synthetic",
            ],
            "analysis_run_id": ["analysis_dashboard_synthetic"] * 4,
            "period": [date(2025, 6, 1), date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 1)],
            "category": ["CATEGORY_STANDARD", "CATEGORY_STANDARD", "CATEGORY_STANDARD", "CATEGORY_PREMIUM"],
            "manufacturer": ["Manufacturer A", "Manufacturer A", "Manufacturer B", "Manufacturer C"],
            "brand": ["Brand A", "Brand A", "Brand B", "Brand C"],
            "sku_name": ["SKU A", "SKU A", "SKU B", "SKU C"],
            "canonical_product_id": ["SKU_A_001", "SKU_A_001", "SKU_B_001", "SKU_C_001"],
            "canonical_store_id": ["STORE_001", "STORE_001", "STORE_002", "STORE_001"],
            "units": [6.0, 8.0, 5.0, 2.0],
            "revenue_vat": [72.0, 96.0, 60.0, 36.0],
            "revenue_net": [60.0, 80.0, 50.0, 30.0],
            "retailer_margin_abs": [15.0, 20.0, 10.0, 6.0],
            "shelf_price_vat": [12.0, 12.0, 12.0, 18.0],
            "input_price_vat": [8.0, 8.0, 10.0, 12.0],
            "private_label_flag": [False, False, True, False],
            "source_row_number": [1, 2, 3, 4],
            "store_format": ["format_a", "format_a", "format_b", "format_a"],
            "region": ["region_a", "region_a", "region_b", "region_a"],
            "package": ["PACK_A", "PACK_A", "PACK_B", "PACK_C"],
            "volume_l": [0.5, 0.5, 1.0, 1.5],
            "volume_band": ["NOT_PRODUCTIZED", "NOT_PRODUCTIZED", "NOT_PRODUCTIZED", "NOT_PRODUCTIZED"],
        }
    ).write_parquet(path)
    return path


def _runtime_with_source_like(base_path: Path, source_like_rows_path: Path):
    runtime = build_synthetic_dashboard_runtime(base_path)
    return replace(
        runtime,
        source_like_rows_path=source_like_rows_path,
        query_service=DashboardMartQueryService(
            runtime.query_service.metric_facts_path,
            catalog=runtime.query_service.catalog,
            mart_builds=runtime.query_service.mart_builds,
            source_ledger=runtime.query_service.source_ledger,
            source_like_rows_path=source_like_rows_path,
        ),
    )


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
            "period": [date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 1)],
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


def _write_source_like_rows_with_null_private_label(path: Path) -> Path:
    pl.DataFrame(
        {
            "retailer_id": ["retailer_a", "retailer_a", "retailer_a"],
            "source_id": ["source_a", "source_a", "source_a"],
            "source_revision_id": ["revision_dashboard_synthetic"] * 3,
            "analysis_run_id": ["analysis_dashboard_synthetic"] * 3,
            "period": [date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 1)],
            "category": ["CATEGORY_STANDARD", "CATEGORY_STANDARD", "CATEGORY_STANDARD"],
            "manufacturer": ["Manufacturer A", "Manufacturer A", "Manufacturer A"],
            "brand": ["Brand A", "Brand A", "Brand A"],
            "sku_name": ["SKU False", "SKU Null", "SKU True"],
            "canonical_product_id": ["SKU_FALSE", "SKU_NULL", "SKU_TRUE"],
            "canonical_store_id": ["STORE_001", "STORE_002", "STORE_003"],
            "units": [4.0, 5.0, 6.0],
            "revenue_vat": [40.0, 50.0, 60.0],
            "private_label_flag": [False, None, True],
        },
        schema_overrides={"private_label_flag": pl.Boolean},
    ).write_parquet(path)
    return path


def _write_duplicate_diagnostics_source_like_rows(path: Path) -> Path:
    pl.DataFrame(
        {
            "retailer_id": ["retailer_a", "retailer_a", "retailer_a"],
            "source_id": ["source_a", "source_a", "source_a"],
            "source_revision_id": ["revision_dashboard_synthetic"] * 3,
            "analysis_run_id": ["analysis_dashboard_synthetic"] * 3,
            "period": [date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 1)],
            "category": ["COLA", "COLA", "COLA"],
            "manufacturer": ["Manufacturer C", "Manufacturer C", "Manufacturer C"],
            "brand": ["COCA-COLA", "COCA-COLA", "COCA-COLA"],
            "sku_name": ["НАПИТОК КОКА-КОЛА ОРИДЖИНАЛ Ж/Б 0,33Л"] * 3,
            "canonical_product_id": ["706913", "756771", "940211"],
            "canonical_store_id": ["STORE_001", "STORE_001", "STORE_001"],
            "units": [1.0, 2.0, 3.0],
            "revenue_vat": [10.0, 20.0, 30.0],
            "private_label_flag": [False, False, False],
            "package": ["Ж/Б 0,33Л", "Ж/Б 0,33Л", "Ж/Б 0,33Л"],
            "volume_l": [0.33, 0.33, 0.33],
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
