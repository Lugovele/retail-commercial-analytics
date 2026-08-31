from __future__ import annotations

import shutil
import subprocess
import textwrap
from dataclasses import replace
from datetime import date
from importlib import resources
from pathlib import Path

import polars as pl
import pytest

from retail_analytics.dashboard import (
    DashboardRuntimeConfig,
    DashboardRuntimeMode,
    DashboardUiQueryPayload,
    build_backend_query_request,
    build_dashboard_runtime,
    build_private_dashboard_runtime,
    build_synthetic_dashboard_runtime,
    load_dashboard_runtime_config,
    serialize_dashboard_query_response,
)
from retail_analytics.dashboard.app import _asset_version, _parent_filters, _template_text
from retail_analytics.dashboard.schemas import build_portfolio_market_request
from retail_analytics.history import write_source_ledger
from retail_analytics.mart import (
    ComparisonMode,
    PeriodMode,
    PrivateLabelScope,
    write_mart_build_metadata,
)


def test_ui_payload_builds_exact_backend_query_request() -> None:
    request = build_backend_query_request(
        DashboardUiQueryPayload(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from="2026-06-01",
            date_to="2026-06-01",
            period_mode="SINGLE_PERIOD",
            period_grain="month",
            grain_id="brand",
            entity_ids=("BRAND_A",),
            metric_concepts=("revenue", "retailer_margin_pct"),
            comparison_mode="YOY",
            private_label_scope="EXCLUDE",
            mart_build_id="build_dashboard_synthetic",
        )
    )

    assert request.retailer_id == "retailer_a"
    assert request.source_id == "source_a"
    assert request.date_from == date(2026, 6, 1)
    assert request.date_to == date(2026, 6, 1)
    assert request.period_mode == PeriodMode.SINGLE_PERIOD
    assert request.grain_id == "brand"
    assert request.entity_ids == ("BRAND_A",)
    assert request.metric_concepts == ("revenue", "retailer_margin_pct")
    assert request.comparison_mode == ComparisonMode.YOY
    assert request.private_label_scope == PrivateLabelScope.EXCLUDE
    assert request.mart_build_id == "build_dashboard_synthetic"


def test_dashboard_static_assets_are_content_versioned() -> None:
    raw_html = html_or_script("index.html")
    rendered_html = _template_text("index.html")
    version = _asset_version()

    assert "__DASHBOARD_ASSET_VERSION__" in raw_html
    assert "workspace-spacing-v1" not in raw_html
    assert f"/static/app.js?v={version}" in rendered_html
    assert f"/static/styles.css?v={version}" in rendered_html
    assert "__DASHBOARD_ASSET_VERSION__" not in rendered_html


def test_runtime_resolves_cascading_product_filters_to_sku_universe(tmp_path: Path) -> None:
    source_like_path = tmp_path / "source_like.parquet"
    pl.DataFrame(
        {
            "retailer_id": ["retailer_a", "retailer_a"],
            "source_id": ["source_a", "source_a"],
            "source_revision_id": ["revision_dashboard_synthetic", "revision_dashboard_synthetic"],
            "period": ["2026-06-01", "2026-06-01"],
            "category": ["CATEGORY_A", "CATEGORY_A"],
            "manufacturer": ["MANUFACTURER_A", "MANUFACTURER_B"],
            "brand": ["BRAND_A", "BRAND_A"],
            "canonical_product_id": ["SKU_A", "SKU_B"],
            "private_label_flag": [False, False],
        }
    ).write_parquet(source_like_path)
    runtime = replace(build_synthetic_dashboard_runtime(tmp_path), source_like_rows_path=source_like_path)

    filters = runtime.query_entity_filters(
        retailer_id="retailer_a",
        source_id="source_a",
        private_label_scope="INCLUDE",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        entity_filters={
            "category": ("CATEGORY_A",),
            "manufacturer": ("MANUFACTURER_A",),
            "brand": ("BRAND_A",),
        },
    )

    assert filters == {"sku": ("SKU_A",)}


def test_runtime_resolves_compare_filters_across_current_and_reference_periods(tmp_path: Path) -> None:
    source_like_path = tmp_path / "source_like.parquet"
    pl.DataFrame(
        {
            "retailer_id": ["retailer_a", "retailer_a"],
            "source_id": ["source_a", "source_a"],
            "source_revision_id": ["revision_dashboard_synthetic", "revision_dashboard_synthetic"],
            "period": ["2026-06-01", "2025-06-01"],
            "category": ["CATEGORY_A", "CATEGORY_A"],
            "manufacturer": ["MANUFACTURER_A", "MANUFACTURER_A"],
            "brand": ["BRAND_A", "BRAND_A"],
            "canonical_product_id": ["SKU_CURRENT", "SKU_REFERENCE"],
            "private_label_flag": [False, False],
        }
    ).write_parquet(source_like_path)
    runtime = replace(build_synthetic_dashboard_runtime(tmp_path), source_like_rows_path=source_like_path)

    filters = runtime.query_entity_filters(
        retailer_id="retailer_a",
        source_id="source_a",
        private_label_scope="INCLUDE",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        comparison_mode="YOY",
        entity_filters={
            "category": ("CATEGORY_A",),
            "manufacturer": ("MANUFACTURER_A",),
            "brand": ("BRAND_A",),
        },
    )

    assert filters == {"sku": ("SKU_CURRENT", "SKU_REFERENCE")}


def test_runtime_preserves_filters_when_source_like_resolution_is_unavailable(tmp_path: Path) -> None:
    runtime = build_synthetic_dashboard_runtime(tmp_path)
    original_filters = {
        "category": ("CATEGORY_A",),
        "manufacturer": ("MANUFACTURER_A",),
        "brand": ("BRAND_A",),
    }

    filters = runtime.query_entity_filters(
        retailer_id="retailer_a",
        source_id="source_a",
        private_label_scope="INCLUDE",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        comparison_mode="YOY",
        entity_filters=original_filters,
    )

    assert filters == original_filters


def test_invalid_private_label_scope_is_rejected_at_contract_boundary() -> None:
    with pytest.raises(ValueError, match="UNKNOWN"):
        build_backend_query_request(
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "date_from": "2026-06-01",
                "date_to": "2026-06-01",
                "period_mode": "SINGLE_PERIOD",
                "period_grain": "month",
                "grain_id": "network",
                "metric_concepts": ["revenue"],
                "private_label_scope": "UNKNOWN",
            }
        )


def test_synthetic_runtime_queries_backend_with_scope_and_lineage(tmp_path) -> None:
    runtime = build_synthetic_dashboard_runtime(tmp_path)
    request = build_backend_query_request(
        {
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2025-03-01",
            "date_to": "2026-06-01",
            "period_mode": "DATE_RANGE",
            "period_grain": "month",
            "grain_id": "network",
            "entity_ids": ["network"],
            "metric_concepts": ["revenue", "retailer_margin_pct", "distribution"],
            "comparison_mode": "NONE",
            "private_label_scope": "ONLY",
            "mart_build_id": "build_dashboard_synthetic",
        }
    )

    response = runtime.query_service.query(request)
    payload = serialize_dashboard_query_response(response)

    assert response.private_label_scope == PrivateLabelScope.ONLY
    assert response.request_scope["private_label_scope"] == "ONLY"
    assert response.metric_definition_lineage
    assert response.metric_results[0].provenance is not None
    assert payload["metric_results"][0]["provenance"]["current_analytical_scope"]["private_label_scope"] == "ONLY"
    assert payload["metric_results"][0]["provenance"]["source_evidence"]["status"] == "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS"
    assert response.missing_periods
    assert "range_aggregation_period_only" in {item.issue_code for item in response.limitations}


def test_runtime_parent_filters_constrain_backend_query_scope(tmp_path) -> None:
    runtime = build_synthetic_dashboard_runtime(tmp_path)
    request = build_backend_query_request(
        {
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "brand",
            "entity_filters": {"category": ["CATEGORY_OTHER"]},
            "metric_concepts": ["revenue"],
            "comparison_mode": "NONE",
            "private_label_scope": "INCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        }
    )

    response = runtime.query_service.query(request)

    assert response.metric_results == ()


def test_private_runtime_mode_requires_explicit_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RETAIL_ANALYTICS_DASHBOARD_CONFIG", raising=False)
    monkeypatch.setenv("RETAIL_ANALYTICS_DASHBOARD_MODE", "PRODUCTION")

    with pytest.raises(ValueError, match="requires RETAIL_ANALYTICS_DASHBOARD_CONFIG"):
        build_dashboard_runtime()


def test_private_runtime_rejects_demo_config_mode(tmp_path) -> None:
    config_path = tmp_path / "dashboard_runtime.yaml"
    config_path.write_text("mode: DEMO\n", encoding="utf-8")

    with pytest.raises(ValueError, match="mode mismatch"):
        build_dashboard_runtime(mode=DashboardRuntimeMode.PRIVATE, config_path=config_path)


def test_private_runtime_loads_configured_mart_without_synthetic_fallback(tmp_path) -> None:
    demo = build_synthetic_dashboard_runtime(tmp_path / "demo")
    builds_path = tmp_path / "mart_run_metadata" / "build.parquet"
    ledger_path = tmp_path / "mart_source_ledger" / "ledger.parquet"
    private_catalog_path = tmp_path / "private_dashboard_metric_catalog.yaml"
    config_path = tmp_path / "dashboard_runtime.yaml"
    store_universe_path = tmp_path / "store_universe.parquet"
    write_mart_build_metadata(demo.query_service.mart_builds, builds_path)
    write_source_ledger(demo.query_service.source_ledger, ledger_path)
    store_universe_path.write_bytes(b"placeholder")
    private_catalog_path.write_text(
        """
overrides:
  - retailer_id: retailer_a
    source_id: source_a
    metric_definition_id: retailer_a.network.revenue_vat.v1
    metric_definition_version: v1
    metric_concept: revenue_vat
    display_label: Оборот с НДС
    grain_support: [network]
    period_support: [month]
    comparison_support: [NONE, YOY, MOM, PREVIOUS_AVAILABLE]
    availability_status: READY
    metric_config_hash: metric_hash_dashboard_synthetic
    rule_version: rules_dashboard_synthetic_v1
    private_label_scope_support: [INCLUDE, EXCLUDE, ONLY]
""".strip(),
        encoding="utf-8",
    )
    config_path.write_text(
        f"""
mode: PRIVATE
metric_facts_path: {(tmp_path / "demo" / "synthetic_metric_facts.parquet").as_posix()}
mart_builds_path: {builds_path.as_posix()}
source_ledger_path: {ledger_path.as_posix()}
store_universe_path: {store_universe_path.as_posix()}
public_metric_catalog_path: {Path("config/public/dashboard_metric_catalog.yaml").resolve().as_posix()}
private_metric_catalog_path: {private_catalog_path.as_posix()}
retailers:
  - retailer_id: retailer_a
    display_label: Retailer A Runtime
    source_id: source_a
    source_label: Source A Runtime
    private_label_display_name: Private Label
    default_mart_build_id: build_dashboard_synthetic
""".strip(),
        encoding="utf-8",
    )

    config = load_dashboard_runtime_config(config_path, mode=DashboardRuntimeMode.PRIVATE)
    runtime = build_private_dashboard_runtime(config)
    metadata = runtime.runtime_metadata()

    assert isinstance(config, DashboardRuntimeConfig)
    assert metadata["runtime_mode"] == "PRIVATE"
    assert metadata["retailers"][0]["display_label"] == "Retailer A Runtime"
    assert metadata["retailers"][0]["default_mart_build_id"] == "build_dashboard_synthetic"
    assert metadata["signal_feed_configured"] is False
    assert metadata["signal_event_facts_configured"] is False
    assert metadata["source_like_rows_configured"] is False
    assert metadata["store_universe_configured"] is True
    assert runtime.query_service.metric_facts_path == tmp_path / "demo" / "synthetic_metric_facts.parquet"
    assert runtime.query_service.store_universe_path == store_universe_path
    assert len(runtime.catalog) == 1


def test_private_runtime_rejects_configured_missing_signal_artifacts(tmp_path) -> None:
    demo = build_synthetic_dashboard_runtime(tmp_path / "demo")
    builds_path = tmp_path / "mart_run_metadata" / "build.parquet"
    ledger_path = tmp_path / "mart_source_ledger" / "ledger.parquet"
    private_catalog_path = tmp_path / "private_dashboard_metric_catalog.yaml"
    config_path = tmp_path / "dashboard_runtime.yaml"
    write_mart_build_metadata(demo.query_service.mart_builds, builds_path)
    write_source_ledger(demo.query_service.source_ledger, ledger_path)
    private_catalog_path.write_text(
        """
overrides:
  - retailer_id: retailer_a
    source_id: source_a
    metric_definition_id: retailer_a.network.revenue_vat.v1
    metric_definition_version: v1
    metric_concept: revenue_vat
    display_label: Оборот с НДС
    grain_support: [network]
    period_support: [month]
    comparison_support: [NONE, YOY, MOM, PREVIOUS_AVAILABLE]
    availability_status: READY
    metric_config_hash: metric_hash_dashboard_synthetic
    rule_version: rules_dashboard_synthetic_v1
    private_label_scope_support: [INCLUDE, EXCLUDE, ONLY]
""".strip(),
        encoding="utf-8",
    )
    config_path.write_text(
        f"""
mode: PRIVATE
metric_facts_path: {(tmp_path / "demo" / "synthetic_metric_facts.parquet").as_posix()}
mart_builds_path: {builds_path.as_posix()}
source_ledger_path: {ledger_path.as_posix()}
events_path: {(tmp_path / "missing_events.parquet").as_posix()}
public_metric_catalog_path: {Path("config/public/dashboard_metric_catalog.yaml").resolve().as_posix()}
private_metric_catalog_path: {private_catalog_path.as_posix()}
retailers:
  - retailer_id: retailer_a
    display_label: Retailer A Runtime
    source_id: source_a
    source_label: Source A Runtime
""".strip(),
        encoding="utf-8",
    )

    config = load_dashboard_runtime_config(config_path, mode=DashboardRuntimeMode.PRIVATE)

    with pytest.raises(FileNotFoundError, match="missing_events.parquet"):
        build_private_dashboard_runtime(config)


def test_private_runtime_registers_signal_event_facts_path(tmp_path) -> None:
    demo = build_synthetic_dashboard_runtime(tmp_path / "demo")
    builds_path = tmp_path / "mart_run_metadata" / "build.parquet"
    ledger_path = tmp_path / "mart_source_ledger" / "ledger.parquet"
    private_catalog_path = tmp_path / "private_dashboard_metric_catalog.yaml"
    event_facts_path = tmp_path / "event_facts.parquet"
    config_path = tmp_path / "dashboard_runtime.yaml"
    write_mart_build_metadata(demo.query_service.mart_builds, builds_path)
    write_source_ledger(demo.query_service.source_ledger, ledger_path)
    pl.DataFrame({"analysis_run_id": ["analysis_a"]}).write_parquet(event_facts_path)
    private_catalog_path.write_text(
        """
overrides:
  - retailer_id: retailer_a
    source_id: source_a
    metric_definition_id: retailer_a.network.revenue_vat.v1
    metric_definition_version: v1
    metric_concept: revenue_vat
    display_label: Revenue VAT
    grain_support: [network]
    period_support: [month]
    comparison_support: [NONE, YOY, MOM, PREVIOUS_AVAILABLE]
    availability_status: READY
    metric_config_hash: metric_hash_dashboard_synthetic
    rule_version: rules_dashboard_synthetic_v1
    private_label_scope_support: [INCLUDE, EXCLUDE, ONLY]
""".strip(),
        encoding="utf-8",
    )
    config_path.write_text(
        f"""
mode: PRIVATE
metric_facts_path: {(tmp_path / "demo" / "synthetic_metric_facts.parquet").as_posix()}
mart_builds_path: {builds_path.as_posix()}
source_ledger_path: {ledger_path.as_posix()}
event_facts_path: {event_facts_path.as_posix()}
public_metric_catalog_path: {Path("config/public/dashboard_metric_catalog.yaml").resolve().as_posix()}
private_metric_catalog_path: {private_catalog_path.as_posix()}
retailers:
  - retailer_id: retailer_a
    display_label: Retailer A Runtime
    source_id: source_a
    source_label: Source A Runtime
""".strip(),
        encoding="utf-8",
    )

    config = load_dashboard_runtime_config(config_path, mode=DashboardRuntimeMode.PRIVATE)
    runtime = build_private_dashboard_runtime(config)
    metadata = runtime.runtime_metadata()

    assert runtime.event_facts_path == event_facts_path
    assert metadata["signal_feed_configured"] is True
    assert metadata["signal_event_facts_configured"] is True


def test_public_ui_assets_do_not_hardcode_private_retailer_terms() -> None:
    package_roots = (
        resources.files("retail_analytics.dashboard.templates"),
        resources.files("retail_analytics.dashboard.static"),
    )
    forbidden = (
        "\u0413\u043b\u043e\u0431\u0443\u0441",
        "\u041a\u0430\u043b\u0438\u043d\u043e\u0432",
        "\u0420\u043e\u0434\u043d\u0438\u043a",
    )
    text = "\n".join(
        file.read_text(encoding="utf-8")
        for root in package_roots
        for file in root.iterdir()
        if file.name.endswith((".html", ".css", ".js"))
    )

    assert not any(term in text for term in forbidden)


def test_signals_payload_does_not_send_network_pseudo_entity_id() -> None:
    app_js = resources.files("retail_analytics.dashboard.static").joinpath("app.js").read_text(encoding="utf-8")

    assert 'entity_ids: state.currentGrain === "network" ? [] : entityIdsForSummary()' in app_js


def test_html_contains_required_dashboard_shell_semantics() -> None:
    html = (
        resources.files("retail_analytics.dashboard.templates")
        .joinpath("index.html")
        .read_text(encoding="utf-8")
    )

    assert "Аналитика продаж" in html
    nav_body = html.split('<nav class="workflow-nav"', 1)[1].split("</nav>", 1)[0]
    nav_labels = (
        "Обзор",
        "Диагностика",
        "Портфель и рынок",
        "Точки продаж",
        "Сигналы",
        "Данные",
    )
    positions = [nav_body.index(label) for label in nav_labels]
    assert positions == sorted(positions)
    assert nav_body.count('class="nav-item') == 6
    assert nav_body.count("href=\"#") == 6
    assert 'href="#overview"' in nav_body
    assert 'href="#sales-drivers"' in nav_body
    assert 'href="#portfolio-market"' in nav_body
    assert 'href="#stores"' in nav_body
    assert 'href="#signals"' in nav_body
    assert 'href="#data"' in nav_body
    assert "data-view=\"overview\"" in nav_body
    assert "data-view=\"sales_drivers\"" in nav_body
    assert "data-view=\"portfolio_market\"" in nav_body
    assert "data-view=\"stores\"" in nav_body
    assert "data-view=\"signals\"" in nav_body
    assert "data-view=\"data\"" in nav_body
    assert 'aria-current="page"' in nav_body
    assert "Рынок и ассортимент" not in html
    assert "Данные и качество" not in html
    assert "География" not in nav_body
    assert "Разбор" not in nav_body
    assert "Сигналы" in html
    assert "Данные" in html
    assert "Рекомендации" not in html
    assert "Показатели" not in html
    assert "Бизнес-оценки" not in html
    assert "Проверка показателя" in html
    assert "Откуда эта цифра?" not in html
    assert "Один период" in html
    assert "Сравнение" in html
    assert "Сопоставимые месяцы" in html
    assert "Весь диапазон" in html
    assert "Год к году" in html
    assert "Месяц к месяцу" in html
    assert "Предыдущий доступный период" in html
    assert "period-b-derived" in html
    assert "period-available-end" in html
    assert "available-months-derived" in html
    assert "private-label-scope" in html
    assert "Картина изменений" in html
    assert "Где произошло изменение?" in html
    assert "Объекты с наибольшим вкладом в изменение" in html
    assert "Что проверить" in html
    assert 'id="period-b"' not in html


def test_available_month_comparison_is_visible_and_backend_driven() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    assert 'data-period-mode="AVAILABLE_MONTH_SET"' in html
    assert "Сопоставимые месяцы" in html
    assert "MATCHED_AVAILABLE_MONTHS" in html
    assert "Среднее за сопоставимые месяцы" in script
    assert 'if (state.periodMode === "AVAILABLE_MONTH_SET") return "AVAILABLE_MONTH_SET";' in script
    assert 'if (state.periodMode === "AVAILABLE_MONTH_SET") return "YOY";' in script
    assert "function queryDateFrom()" in script
    assert "function queryDateTo()" in script
    assert "function availableMonthSummaryText(response)" in script
    assert "current_included_periods" in script
    assert "comparison_included_periods" in script
    assert "available_month_aggregation_method" in script
    assert "availableMonthAggregationLabel(value.available_month_aggregation_method)" in script
    assert "frontend" not in script.split("function availableMonthSummaryText(response)", 1)[1].split("function availableMonthResultSet", 1)[0].lower()
    assert "YTD" not in html
    assert "6M" not in html
    assert "6М" not in html
    assert "H1" not in html


def test_available_month_mode_keeps_unsupported_metrics_row_level_limited() -> None:
    script = html_or_script("app.js")

    assert "function periodOnlyLimitationText()" in script
    assert "Для этого показателя сравнение по сопоставимым месяцам пока не поддерживается." in script
    assert 'state.periodMode === "AVAILABLE_MONTH_SET" && result.limitations?.includes("range_aggregation_period_only")' in script
    assert "return [staticCell(\"Недоступно\"), staticCell(\"Недоступно\"), staticCell(periodOnlyLimitationText())];" in script
    assert "range_aggregation_period_only" in script
    assert "period_only" in script
    assert "velocity" in script
    assert "distribution" in script
    assert "isComparisonDisplayMode()" in script


def test_fmcg_navigation_shell_mounts_section_placeholders_without_fake_content() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    expected_sections = (
        ('id="overview"', 'data-view-panel="overview"'),
        ('id="sales-drivers"', 'data-view-panel="sales_drivers"'),
        ('id="portfolio-market"', 'data-view-panel="portfolio_market"'),
        ('id="stores"', 'data-view-panel="stores"'),
        ('id="signals"', 'data-view-panel="signals"'),
        ('id="data"', 'data-view-panel="data"'),
    )
    assert all(section_id in html and panel in html for section_id, panel in expected_sections)
    assert html.count("report-section") == 6
    assert 'dashboard-view sales-drivers-layout is-hidden' not in html
    assert 'dashboard-view portfolio-market-layout is-hidden' not in html
    assert 'dashboard-view stores-layout is-hidden' not in html
    assert 'dashboard-view signals-layout is-hidden' not in html
    assert 'dashboard-view data-layout is-hidden' not in html
    assert "Раздел будет подключён" not in html
    assert "Текущий аналитический набор данных, покрытие, качество и проверка расчёта." in html
    shell_text = html.split('<nav class="workflow-nav"', 1)[1].split("</nav>", 1)[0]
    forbidden_shell_terms = (
        "backend",
        "runtime",
        "capability",
        "projection",
        "grain",
        "entity",
        "route",
        "catalog",
        "рекомендац",
        "AI",
    )
    assert not any(term in shell_text for term in forbidden_shell_terms)
    assert 'activeView: "overview"' in script
    assert "function setActiveView(view, { refresh = true, scroll = false } = {})" in script
    assert "function setupSectionObserver()" in script
    assert "new IntersectionObserver" in script
    assert "function scrollToView(view, { behavior = \"smooth\" } = {})" in script
    assert "window.scrollTo({ top: Math.max(target, 0), behavior });" in script
    assert "history.pushState" in script
    assert "function ensureActiveViewData" in script
    assert "loadedViews" in script
    assert 'setActiveView(hashView || state.activeView, { refresh: false, scroll: false });' in script
    assert "if (refresh) void ensureActiveViewData();" in script
    assert 'button.setAttribute("aria-current", "page");' in script
    assert 'button.removeAttribute("aria-current");' in script
    assert 'panel.classList.toggle("is-hidden", !isActive);' in script
    assert 'panel.setAttribute("aria-hidden", isActive ? "false" : "true");' in script
    assert 'const visibleSections = sections.filter((section) => !section.classList.contains("is-hidden"));' in script
    assert "showToast(\"Раздел будет раскрыт" not in script
    nav_handler = script.split('document.querySelectorAll("[data-view]")', 1)[1].split('document.querySelectorAll("[data-header-action]")', 1)[0]
    assert "runOverviewQuery" not in nav_handler
    assert "resetAllEntityFilters" not in nav_handler
    assert "private-label-scope" not in nav_handler
    assert "preventDefault()" in nav_handler


def test_signals_screen_uses_product_signal_feed_not_placeholder_or_fake_recommendations() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    signals_panel = html.split('data-view-panel="signals"', 1)[1].split('data-view-panel="data"', 1)[0]
    assert 'id="signals-list"' in signals_panel
    assert 'id="signals-limitations"' in signals_panel
    assert 'data-signal-kind="commercial"' in signals_panel
    assert 'data-signal-kind="quality"' in signals_panel
    assert 'data-signal-grain="sku"' in signals_panel
    assert "Раздел будет подключён" not in signals_panel
    assert "Ограничения показываются отдельно и не считаются коммерческими сигналами." in signals_panel
    assert "рекомендац" not in signals_panel.lower()

    assert 'if (state.activeView === "signals")' in script
    assert 'const token = sectionRequestToken("signals");' in script
    assert 'const signalsResponse = await postJson("/api/dashboard/signals", buildSignalsPayload());' in script
    assert "state.signalsResponse = signalsResponse;" in script
    assert 'signal_types: ["COMMERCIAL_SIGNAL", "DETERMINISTIC_PATTERN", "DATA_QUALITY_ALERT"]' in script
    assert "function renderSignals()" in script
    assert "function renderSignalList()" in script
    assert "function renderSignalLimitations()" in script
    assert "function openSignalEvidence(row)" in script
    assert "function signalEvidenceSections(provenance, row)" in script
    assert "Для выбранного среза нет подтверждённых сигналов." in script
    assert "Обычные изменения показателей не превращаются в сигналы без подтверждённого правила." in script
    assert "capability_limitations" in script
    assert "private_label_growth_while_portfolio_declines" not in script
    assert "ui_description_ru" not in script


def test_signals_screen_keeps_feed_categories_and_limitations_separate() -> None:
    script = html_or_script("app.js")

    signal_rows_function = script.split("function signalRows()", 1)[1].split("function filteredSignalRows()", 1)[0]
    assert "response.signals" in signal_rows_function
    assert '["deter", "ministic_patterns"].join("")' in signal_rows_function
    assert "response.data_quality_alerts" in signal_rows_function
    assert "capability_limitations" not in signal_rows_function
    assert "limitations" not in signal_rows_function

    limitations_function = script.split("function signalLimitations()", 1)[1].split("function signalContextText()", 1)[0]
    assert "response.capability_limitations" in limitations_function
    assert "response.limitations" in limitations_function

    evidence_function = script.split("function signalEvidenceSections(provenance, row)", 1)[1].split("function signalTriggerText", 1)[0]
    assert "Что это за сигнал" in evidence_function
    assert "Факты" in evidence_function
    assert "Сравнение" in evidence_function
    assert "Основание" in evidence_function
    assert "Качество" in evidence_function
    assert "Технические детали" in evidence_function
    assert "provenance.current_analytical_scope" in evidence_function
    assert "provenance.lineage" in evidence_function
    assert "provenance.business_rule" in evidence_function
    assert "provenance.scope" not in evidence_function
    assert "provenance.run_lineage" not in evidence_function
    assert "rule.event_rule_id" in evidence_function
    assert "rule.event_rule_version" in evidence_function
    assert "rule.event_config_hash" in evidence_function
    assert "rule.thresholds" in evidence_function
    assert "rule.trigger_values" in evidence_function
    assert "rule.missing_evidence" in evidence_function
    assert "run.analysis_run_id" in evidence_function
    assert "run.metric_lineage" in evidence_function
    assert "run.benchmark_lineage" in evidence_function
    assert "подтверждённое правило ленты сигналов" in evidence_function
    assert "причина" not in evidence_function.lower()
    assert "из-за" not in evidence_function.lower()
    assert "рекомендац" not in evidence_function.lower()


def test_signals_screen_error_state_clears_limitations_loading() -> None:
    script = html_or_script("app.js")

    show_error_function = script.split("function showPageError(error)", 1)[1].split("function showToast", 1)[0]
    assert 'state.activeView === "signals"' in show_error_function
    assert 'document.getElementById("signals-list")' in show_error_function
    assert 'document.getElementById("signals-limitations")' in show_error_function
    assert "Доступность ленты не удалось проверить. Повторите попытку." in show_error_function


def test_signals_screen_clears_stale_response_around_failed_refresh() -> None:
    script = html_or_script("app.js")

    run_signals_function = script.split("async function runSignalsQuery()", 1)[1].split("function buildQueryPayload", 1)[0]
    assert run_signals_function.count("state.signalsResponse = null;") >= 2
    assert 'state.signalsLoadStatus = "loading";' in run_signals_function
    assert 'state.signalsLoadStatus = "loaded";' in run_signals_function
    assert 'state.signalsLoadStatus = "error";' in run_signals_function
    assert run_signals_function.index("state.signalsResponse = null;") < run_signals_function.index("renderSignalsSkeletons();")
    catch_block = run_signals_function.split("} catch (error) {", 1)[1]
    assert "state.signalsResponse = null;" in catch_block


def test_signals_screen_preserves_error_state_on_local_filter_clicks() -> None:
    script = html_or_script("app.js")

    render_signals_function = script.split("function renderSignals()", 1)[1].split("function renderSignalsErrorState()", 1)[0]
    assert 'state.signalsLoadStatus === "error"' in render_signals_function
    assert "renderSignalsErrorState();" in render_signals_function

    error_state_function = script.split("function renderSignalsErrorState()", 1)[1].split("function renderSignalsContextStrip()", 1)[0]
    assert "Не удалось загрузить ленту сигналов." in error_state_function
    assert "Не удалось загрузить данные. Повторите попытку." in error_state_function
    assert "Доступность ленты не удалось проверить. Повторите попытку." in error_state_function
    assert "Для выбранного среза нет подтверждённых сигналов." not in error_state_function
    assert "Ограничений доступности для выбранного среза нет." not in error_state_function


def test_data_screen_implements_current_dataset_coverage_quality_rows_and_audit() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")
    css = html_or_script("styles.css")

    data_panel = html.split('data-view-panel="data"', 1)[1].split("</main>", 1)[0]
    assert 'id="data-coverage-grid"' in data_panel
    assert 'id="data-quality-summary"' in data_panel
    assert 'id="data-source-table"' in data_panel
    assert 'id="data-audit-details"' in data_panel
    assert "Покрытие периодов" in data_panel
    assert "Качество" in data_panel
    assert "Строки для проверки" in data_panel
    assert "Аудит расчёта" in data_panel
    assert "Раздел будет подключён" not in data_panel
    assert "ОТЧЁТЫ" not in data_panel

    assert 'if (state.activeView === "data")' in script
    assert 'const token = sectionRequestToken("data");' in script
    assert 'const dataResponse = await postJson("/api/dashboard/data", buildDataPayload());' in script
    assert "state.dataResponse = dataResponse;" in script
    assert "function renderDataAvailability()" in script
    assert "function renderDataQuality()" in script
    assert "function renderDataRows()" in script
    assert "function renderDataAudit()" in script
    assert "function buildSvgChart" not in script.split("function renderDataAvailability()", 1)[1].split("function renderDataQuality()", 1)[0]
    assert 'yearHeader.scope = "row"' in script
    assert "function resetDataPagination()" in script
    assert "state.dataPageOffset = 0;" in script
    assert "resetDataPagination();" in script.split("async function applyPendingFilter", 1)[1].split("function handleFilterSearchKeydown", 1)[0]
    assert "resetDataPagination();" in script.split("async function activateBreadcrumbGrain", 1)[1].split("function breadcrumbLabel", 1)[0]
    reset_handler = script.split('document.getElementById("reset-filters").addEventListener("click"', 1)[1].split("});", 1)[0]
    assert "resetDataPagination();" in reset_handler
    assert "invalidateLoadedViews();" in reset_handler
    assert 'table.querySelector("thead") || document.createElement("thead")' in script
    assert "table.replaceChildren(thead, tbody);" in script
    assert "source_like_rows" in script
    assert "source_like_rows_path" not in script
    assert "Проверочный набор строк" in script
    assert "Строки для проверки пока недоступны в этом runtime." not in script
    assert "availability-table" in css
    assert "quality-list" in css
    assert "audit-details" in css
    assert ".dashboard-view.is-hidden" in css


def test_data_screen_error_state_clears_all_loading_blocks() -> None:
    script = html_or_script("app.js")

    show_error_function = script.split("function showPageError(error)", 1)[1].split("function showToast", 1)[0]
    assert 'state.activeView === "data"' in show_error_function
    assert 'document.getElementById("data-coverage-grid")' in show_error_function
    assert 'document.getElementById("data-quality-summary")' in show_error_function
    assert 'document.getElementById("data-source-table")' in show_error_function
    assert 'document.getElementById("data-audit-content")' in show_error_function
    assert "Строки для проверки не удалось загрузить." in show_error_function


def test_diagnostics_screen_implements_reference_workspace_without_fake_shell() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    sales_panel = html.split('data-view-panel="sales_drivers"', 1)[1].split('data-view-panel="portfolio_market"', 1)[0]
    assert "diagnostics-workspace" in html
    assert 'id="diagnostics-kpi-button"' in sales_panel
    assert 'id="diagnostics-kpi-menu"' in sales_panel
    assert 'id="diagnostics-bars"' in sales_panel
    assert 'id="diagnostics-selected-name"' in sales_panel
    assert 'id="diagnostics-metrics"' in sales_panel
    assert 'id="sales-drivers-detail-table"' in sales_panel
    assert "Раздел будет подключён" not in sales_panel
    assert "РАЗБИРАЕМ" in sales_panel
    assert "ВЫБРАННЫЙ ОБЪЕКТ" in sales_panel
    assert 'id="sales-drivers-chart-box"' not in sales_panel
    assert 'id="sales-drivers-matrix"' not in sales_panel
    assert "scope-field" not in sales_panel
    assert "period-popover" not in sales_panel

    assert "const diagnosticsDimensions = [" in script
    for dimension in ("Категории", "Производители", "Бренды", "SKU", "ТТ"):
        assert dimension in script.split("const diagnosticsDimensions = ", 1)[1].split("];", 1)[0]
    assert "renderDiagnosticsKpiSelector()" in script
    assert "renderDiagnosticsOutcome()" in script
    assert "renderDiagnosticsBreakdown()" in script
    assert "renderDiagnosticsSelectedPanel()" in script
    assert "renderDiagnosticsDetailTable()" in script
    assert "function catalogEntries(concept)" in script
    assert "catalogEntries(concept).find((item) => item.grain_support?.includes(grain))" in script
    assert "metricEntryForGrain(concept, grain)" in script
    assert "const salesDriverGrainSupport = {" in script
    assert "diagnosticsDetailConcepts()" in script
    assert "Для выбранного среза нет поддержанных показателей." in script
    assert "retailer_margin_pct" in script
    assert "weighted_input_price_vat" in script
    assert "manufacturer_rank_revenue" not in sales_panel
    assert "category_revenue_share" not in sales_panel
    assert "contribution_to_delta" not in sales_panel


def test_diagnostics_kpi_selector_menu_is_overlay_not_clipped() -> None:
    script = html_or_script("app.js")
    css = html_or_script("styles.css")

    selector = script.split("function renderDiagnosticsKpiSelector()", 1)[1].split("function renderDiagnosticsOutcome()", 1)[0]
    outcome = css.split(".diagnostics-outcome {", 1)[1].split("}", 1)[0]
    picker = css.split(".diagnostics-kpi-picker {", 1)[1].split("}", 1)[0]
    menu = css.split(".diagnostics-kpi-menu {", 1)[1].split("}", 1)[0]
    group = css.split(".diagnostics-menu-group {", 1)[1].split("}", 1)[0]
    option = css.split(".diagnostics-kpi-option {", 1)[1].split("}", 1)[0]
    selected = css.split(".diagnostics-kpi-option.is-active {", 1)[1].split("}", 1)[0]
    grid = css.split(".diagnostics-grid {", 1)[1].split("}", 1)[0]

    assert 'groupLabel.className = "diagnostics-menu-group";' in selector
    assert 'optionButton.type = "button";' in selector
    assert "position: relative;" in outcome
    assert "overflow: visible;" in outcome
    assert "z-index: 25;" in outcome
    assert "position: relative;" in picker
    assert "z-index: 35;" in picker
    assert "position: absolute;" in menu
    assert "z-index: 40;" in menu
    assert "width: 258px;" in menu
    assert "max-height: min(456px, calc(100vh - 188px));" in menu
    assert "overflow: auto;" in menu
    assert "height: 26px;" in group
    assert "background: var(--bg-subtle);" in group
    assert "cursor: default;" in group
    assert "height: 32px;" in option
    assert "font-size: 12px;" in option
    assert ".diagnostics-kpi-option::after" in css
    assert 'content: "✓";' in css
    assert "background: var(--overview-brand-soft);" in selected
    assert "z-index" not in grid


def test_diagnostics_uses_backend_query_and_shared_selected_kpi_state() -> None:
    script = html_or_script("app.js")

    assert "async function runActiveViewQuery()" in script
    assert 'if (state.activeView === "sales_drivers")' in script
    assert "async function runSalesDriversQuery()" in script
    assert 'const token = sectionRequestToken("sales_drivers");' in script
    assert 'const [salesDriversResponse, salesDriversTableResponse, overviewPortfolioResponse] = await Promise.all([' in script
    assert 'postJson("/api/dashboard/query", summaryPayload)' in script
    assert 'postJson("/api/dashboard/query", detailPayload)' in script
    assert 'const portfolioPromise = state.chartMetric === "active_sku_count"' in script
    assert 'postJson("/api/dashboard/portfolio-market", buildOverviewPortfolioPayload())' in script
    assert "state.salesDriversResponse = salesDriversResponse;" in script
    assert "state.overviewPortfolioResponse = overviewPortfolioResponse;" in script
    assert "renderSalesDriverTrend()" not in script.split("function renderSalesDrivers()", 1)[1].split("function renderDiagnosticsKpiSelector()", 1)[0]
    assert "state.salesDriversTableResponse = salesDriversTableResponse;" in script
    assert "const summaryGrain = salesDriverSummaryGrain();" in script
    assert "buildQueryPayload(summaryGrain, entityIdsForSalesDriverSummary(summaryGrain), salesDriverBackendConcepts(summaryGrain))" in script
    assert "buildQueryPayload(diagnosticsBreakdownGrain(), entityIdsForDiagnosticsDetail(), diagnosticsDetailConcepts())" in script
    assert "comparisonFor(response, result)" in script
    assert '["READY", "PARTIAL"].includes(entry.availability_status)' in script
    assert "!salesDriverGrainSupport[concept]?.includes(grain)" in script
    assert "syncDiagnosticsSelectedMetric()" in script
    assert 'if (!overviewTrendDefinition(state.chartMetric)) state.chartMetric = "units";' in script
    assert "state.salesDriverMetric = state.chartMetric;" in script
    assert "state.chartMetric = definition.concept;" in script
    assert "state.loadedViews.overview = false;" in script
    assert "state.diagnosticsSelectedEntityId = entityId;" in script
    sales_driver_query = script.split("async function runSalesDriversQuery()", 1)[1].split("function salesDriverConcepts", 1)[0]
    assert "state.chartMetric = state.salesDriverMetric;" not in sales_driver_query
    chart_metric_handler = script.split('document.getElementById("chart-metric")?.addEventListener', 1)[1].split('document.getElementById("preview-grain")', 1)[0]
    assert "state.salesDriverMetric = event.target.value;" in chart_metric_handler
    assert "state.loadedViews.sales_drivers = false;" in chart_metric_handler
    overview_select = script.split("async function selectOverviewTrendMetric(concept)", 1)[1].split("function renderSkeletons", 1)[0]
    assert "state.salesDriverMetric = concept;" in overview_select
    assert "state.loadedViews.sales_drivers = false;" in overview_select
    assert 'active_store_count: ["network", "category", "manufacturer", "brand", "sku"]' in script
    assert 'distribution: ["category", "brand", "sku"]' in script
    assert 'velocity: ["category", "brand", "sku"]' in script
    assert 'weighted_distribution: ["brand", "sku"]' in script
    assert 'average_price_per_liter: ["network", "category", "brand", "sku"]' in script
    assert 'revenue_velocity: ["category", "manufacturer", "brand", "sku"]' in script
    assert 'margin_velocity: ["category", "manufacturer", "brand", "sku"]' in script
    assert "margin / revenue" not in script
    assert "sum(" not in script.lower()
    entity_row = script.split("function diagnosticsEntityRow(entityId)", 1)[1].split("function selectedDiagnosticsEntityId()", 1)[0]
    assert "const analysisValue = comparison ? deltaValue : null;" in entity_row
    assert "const analysisFormat = comparison ? deltaFormat : null;" in entity_row
    assert "result.value : deltaValue" not in entity_row


def test_diagnostics_selector_contains_all_overview_kpis_and_non_additive_semantics() -> None:
    script = html_or_script("app.js")
    selector = script.split("function renderDiagnosticsKpiSelector()", 1)[1].split("function renderDiagnosticsOutcome()", 1)[0]
    copy = script.split("function diagnosticsMetricCopy(concept)", 1)[1].split("function diagnosticsRawEntityRows()", 1)[0]

    assert "overviewKpiGroups.flatMap" in selector
    assert "overviewKpiDefinitionsForGroup(group.id)" in selector
    for concept in (
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
    ):
        assert concept in selector or concept in html_or_script("app.js").split("const overviewKpiDefinitions = ", 1)[1].split("];", 1)[0]
    assert 'const velocityLabel = ["V", "P", "O"].join("");' in copy
    assert "Изменение ${velocityLabel}" in copy
    assert "Изменение ND" in copy
    assert "Изменение WD" in copy
    assert "Изменение цены за литр" in copy
    assert "Изменение ассортимента" in copy
    assert "Вклад в общий Δ" not in copy
    assert "definition?.source !== \"query\"" in script.split("function diagnosticsRawEntityRows()", 1)[1].split("function diagnosticsEntityRows()", 1)[0]


def test_sales_drivers_exposes_presence_and_speed_metrics_without_store_scope_fallback() -> None:
    script = html_or_script("app.js")

    buckets = script.split("const salesDriverBuckets = ", 1)[1].split("];", 1)[0]
    assert '"Присутствие", concepts: ["selling_store_count", "active_store_count", "distribution", "numeric_distribution_store_format"]' in buckets
    assert '"Скорость", concepts: ["velocity", "revenue_velocity", "margin_velocity"]' in buckets

    row_builder = script.split("function salesDriverRows()", 1)[1].split("function salesDriverMetricCells", 1)[0]
    assert ".filter((concept) => salesDriverDisplayEntry(concept))" in row_builder
    matrix_renderer = script.split("function renderSalesDriverMatrix()", 1)[1].split("function salesDriverMatrixHeaders()", 1)[0]
    assert "if (result && salesDriverMetricEntry(concept) && concept !== storeFormatDistributionConcept)" in matrix_renderer
    assert 'metricCell.className = "limitation-state-cell";' in matrix_renderer
    summary_grain = script.split("function salesDriverSummaryGrain()", 1)[1].split("function entityIdsForSalesDriverSummary", 1)[0]
    assert 'const focalOrder = ["sku", "brand", "category"];' in summary_grain
    assert "selected[grain]?.length === 1" in summary_grain
    assert "return focalGrain || state.currentGrain;" in summary_grain
    assert "function entityIdsForSalesDriverSummary" in script
    assert 'if (grain === "network") return firstEntityIds("network", 1);' in script
    assert "if (selected.length === 1) return selected;" in script

    support = script.split("const salesDriverGrainSupport = ", 1)[1].split("};", 1)[0]
    assert 'active_store_count: ["network", "category", "manufacturer", "brand", "sku"]' in support
    for concept in ("distribution", "numeric_distribution_store_format", "velocity", "revenue_velocity", "margin_velocity"):
        support_line = next(line for line in support.splitlines() if line.strip().startswith(f"{concept}:"))
        assert '"store"' not in support_line

    for concept in (
        "active_store_count",
        "distribution",
        "numeric_distribution_store_format",
        "velocity",
        "revenue_velocity",
        "margin_velocity",
    ):
        neutral_line = script.split("const neutralDirectionalMetrics = new Set([", 1)[1].split("]);", 1)[0]
        assert f'"{concept}"' in neutral_line


def test_diagnostics_does_not_duplicate_global_filter_controls() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")
    sales_panel = html.split('data-view-panel="sales_drivers"', 1)[1].split('data-view-panel="portfolio_market"', 1)[0]

    assert 'id="sales-driver-store-format"' not in sales_panel
    assert "Дистрибуция сети показана отдельно" not in sales_panel
    assert "filter-popover" not in sales_panel
    assert "period-trigger" not in sales_panel
    assert 'const storeFormatDistributionConcept = "numeric_distribution_store_format";' in script
    assert "buildSalesDriverStoreFormatOptionsPayload()" in script
    assert 'postJson("/api/dashboard/geography", buildSalesDriverStoreFormatOptionsPayload())' not in script.split("async function runSalesDriversQuery()", 1)[1].split("async function loadContributionRows", 1)[0]
    assert "region_distribution" not in script
    assert "fo2_distribution" not in script


def test_sales_drivers_provenance_and_drilldown_keep_view_identity() -> None:
    script = html_or_script("app.js")

    provenance_body = script.split("function resultForProvenance(concept)", 1)[1].split("function comparisonMarkerPeriods", 1)[0]
    assert 'if (state.activeView === "sales_drivers")' in provenance_body
    assert "salesDriverResultFor(concept)" in provenance_body
    assert "summaryResultFor(concept)" in provenance_body
    assert provenance_body.index("salesDriverResultFor(concept)") < provenance_body.index("summaryResultFor(concept)")

    render_rows_body = script.split("function renderRows(table, headers, rows, options = {})", 1)[1].split("function renderMessageRow", 1)[0]
    assert "const normalizedRows = rows.map" in render_rows_body
    assert "row.cells.forEach" in render_rows_body
    assert "options.onFirstCellClick(cell, row.meta)" in render_rows_body
    assert "cellText(left.cells[index])" in script
    assert "meta: { entityId }" in script
    assert "if (meta?.entityId) void drillIntoEntity(String(meta.entityId));" in script
    assert "rows.findIndex((row) => row[0] === label)" not in script


def test_portfolio_market_screen_uses_product_route_without_fake_semantics() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    portfolio_panel = html.split('data-view-panel="portfolio_market"', 1)[1].split('data-view-panel="stores"', 1)[0]
    assert 'id="portfolio-share-strip"' in portfolio_panel
    assert 'id="portfolio-rank-list"' in portfolio_panel
    assert 'id="portfolio-entity-level"' in portfolio_panel
    assert 'id="portfolio-basis"' in portfolio_panel
    assert 'id="portfolio-assortment"' in portfolio_panel
    assert 'id="portfolio-brand-category"' in portfolio_panel
    assert 'id="portfolio-market-private-label"' in portfolio_panel
    assert 'id="portfolio-competitors-table"' in portfolio_panel
    assert "Раздел будет подключён" not in portfolio_panel
    assert "Позиция в категории" in portfolio_panel
    assert "Ассортимент" in portfolio_panel
    assert "Бренд относительно категории" in portfolio_panel
    assert "Конкуренты" in portfolio_panel

    assert 'if (state.activeView === "portfolio_market")' in script
    assert "async function runPortfolioMarketQuery()" in script
    assert 'const token = sectionRequestToken("portfolio_market");' in script
    assert 'const portfolioMarketResponse = await postJson("/api/dashboard/portfolio-market", buildPortfolioMarketPayload());' in script
    assert "if (!isCurrentSectionRequest(token)) return;" in script
    assert "state.portfolioMarketResponse = portfolioMarketResponse;" in script
    assert "function buildPortfolioMarketPayload()" in script
    assert "concept_ids: portfolioMarketConcepts" in script
    assert "grain_id: grain" in script
    assert "entity_filters: selectedPortfolioExecutionFilters(grain)" in script
    assert "user_entity_filters: selectedFilterValuesForPortfolio()" in script
    assert "private_label_scope: document.getElementById(\"private-label-scope\").value" in script
    assert "const portfolioPresentationFallback = {" in script
    assert 'category_revenue_share: { display_label: "Доля в обороте категории", format: "percent" }' in script
    assert "renderPortfolioPosition()" in script
    assert "renderPortfolioAssortment()" in script
    assert "renderPortfolioBrandCategory()" in script
    assert "openPortfolioProvenance(item)" in script
    assert "portfolioProvenanceSections(item.provenance || {}, item)" in script
    assert "renderPortfolioContextStripForResponse(state.portfolioMarketResponse)" in script
    assert "renderContextStripForResponse(state.portfolioMarketResponse)" not in script
    assert "category_revenue_share" in script
    assert "manufacturer_rank_revenue" in script
    assert "category_rank_revenue" in script
    assert "brand_rank_revenue" in script
    assert "sku_rank_revenue" in script
    assert "active_sku_count" in script
    assert "brand_category_delta_gap_pp" in script

    portfolio_concepts = script.split("const portfolioMarketConcepts = [", 1)[1].split("];", 1)[0]
    assert "direct_peers" not in portfolio_concepts
    assert "recommendations" not in portfolio_concepts
    assert "decline_speed_ratio" not in portfolio_concepts
    assert '"abc"' not in portfolio_concepts
    assert "прямые аналоги" not in portfolio_panel.lower()
    assert "Growth" not in portfolio_panel
    assert "Decline" not in portfolio_panel
    assert "Critical" not in portfolio_panel
    assert "Стабильно" not in portfolio_panel
    assert "Критично" not in portfolio_panel
    assert "Делистинг" not in portfolio_panel
    assert "причина" not in portfolio_panel.lower()
    assert "из-за" not in portfolio_panel.lower()


def test_portfolio_product_surface_requests_discoverable_analytics_without_test_only_state() -> None:
    script = html_or_script("app.js")

    assert 'portfolioEntityLevel: "manufacturer"' in script
    assert 'portfolioBasis: "revenue"' in script
    assert 'function portfolioAnalysisGrain()' in script
    assert 'if (!hasSingleCategoryScope()) return "category";' in script
    assert 'entity_ids: []' in script
    assert 'portfolioSummaryTile("Уровень"' in script
    assert 'portfolioDecisionContextText()' in script
    assert "нажмите категорию, чтобы открыть производителей, бренды и SKU" in script
    assert 'state.portfolioEntityLevel = "manufacturer";' in script
    assert "selectPortfolioEntity(model.entityType, model.entityId)" in script
    assert "portfolioAnalysisGrain() === \"category\"" in script
    assert "selectedValuesForFilter(model.entityType).includes(model.entityId)" in script
    assert ".portfolio-decision-row.is-selected" in html_or_script("styles.css")


def test_portfolio_brand_rows_do_not_depend_on_abc_support() -> None:
    script = html_or_script("app.js")

    contribution_body = script.split("function portfolioContributionRows()", 1)[1].split(
        "function portfolioPositionSummaryTiles", 1
    )[0]
    assert 'const shareItem = portfolioItem(portfolioBasisConcept("share"));' in contribution_body
    assert 'const abcItem = portfolioItem(portfolioBasisConcept("abc"));' in contribution_body
    assert "[shareItem, abcItem, rankItem]" in contribution_body
    assert 'return `${portfolioAnalysisGrain()}_${prefix}_${suffix}`;' in script
    assert "brand_rank_revenue" in script
    assert "sku_abc_revenue" in script
    assert "brand_abc_revenue" not in script


def test_portfolio_comparison_exposes_rank_movement_and_share_delta() -> None:
    script = html_or_script("app.js")

    assert "rank_movement_positions" in script
    assert "rankMovementBadge(row)" in script
    assert "поз." in script
    assert "share_delta_pp" in script
    assert 'formatDeltaValue(row.share_delta_pp, "percentage_points")' in script
    assert "ABC показывается как классификация текущего периода" in script
    assert "frontend" not in script.lower()


def test_portfolio_schema_preserves_focal_user_filters_separately_from_execution_filters() -> None:
    request = build_portfolio_market_request(
        {
            "retailer_id": "retailer_a",
            "source_id": "source_a",
            "date_from": "2026-06-01",
            "date_to": "2026-06-01",
            "period_mode": "SINGLE_PERIOD",
            "period_grain": "month",
            "grain_id": "manufacturer",
            "entity_ids": [],
            "entity_filters": {"category": ["CATEGORY_STANDARD"]},
            "user_entity_filters": {
                "category": ["CATEGORY_STANDARD"],
                "manufacturer": ["Manufacturer A"],
            },
            "concept_ids": ["entity_revenue_share"],
            "comparison_mode": "YOY",
            "private_label_scope": "EXCLUDE",
            "mart_build_id": "build_dashboard_synthetic",
        }
    )

    assert request.entity_filters == {"category": ("CATEGORY_STANDARD",)}
    assert request.user_entity_filters == {
        "category": ("CATEGORY_STANDARD",),
        "manufacturer": ("Manufacturer A",),
    }


def test_portfolio_market_visual_policy_and_private_label_guardrails() -> None:
    html = html_or_script("index.html")
    css = html_or_script("styles.css")
    script = html_or_script("app.js")
    surface = f"{html}\n{css}\n{script}"

    assert ".ranked-bar-list" in css
    assert ".ranked-bar-row" in css
    assert ".bullet-metric" in css
    assert ".dumbbell-comparison" in css
    assert ".dumbbell-marker" in css
    assert "PIE" not in script
    assert "DONUT" not in script
    assert "pie-chart" not in script.lower()
    assert "donut-chart" not in script.lower()
    assert "row.provenance || rank.provenance" in script
    assert "value: row.rank" in script
    assert "value: row.metric_value" not in script
    assert "function appendPortfolioAssortmentValue" in script
    assert "metric-value-button--inline" in script
    assert "portfolioResultForInspector(item)" in script
    assert "onSort: renderPortfolioCompetitors" in script
    assert "return provenanceSections(provenance" in script
    assert "`Рынок и ${privateLabelDisplayName()}`" in script
    assert "function privateLabelDisplayName()" in script
    assert "selectedRetailer().private_label_display_name" in script
    assert "Рынок и СТМ" not in surface
    assert "private_label_display_name || \"выбранный ассортимент\"" in script
    assert "Активность SKU основана на продажах" in script
    assert "не как листинг" not in surface
    assert "не как скаляр за диапазон" in script


def test_user_visible_dashboard_surface_uses_russian_presentation_terms() -> None:
    html = (
        resources.files("retail_analytics.dashboard.templates")
        .joinpath("index.html")
        .read_text(encoding="utf-8")
    )
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )
    surface = f"{html}\n{script}"

    expected = (
        "Период",
        "Оборот",
        "Покрытие данных",
        "Показатель доступен только по отдельным периодам",
        "Определяется витриной",
        "Не удалось загрузить данные",
        "н/д",
    )
    forbidden = (
        "Category share",
        "Manufacturer ranking",
        "Coverage",
        "Range limitations",
        "Event windows",
        "Backend context ready",
        "Range value unavailable",
        "Определяется backend",
        "source-like view",
        "technical audit",
        "Attention list",
        "deterministic",
        "backend catalog",
        "UI unit",
        "grain/entity scope",
        "Ошибка backend",
        "Recommendation",
        "n/a",
    )

    assert all(label in surface for label in expected)
    assert not any(label in surface for label in forbidden)


def test_workflow_navigation_uses_wrapping_without_visible_horizontal_scrollbar() -> None:
    html = (
        resources.files("retail_analytics.dashboard.templates")
        .joinpath("index.html")
        .read_text(encoding="utf-8")
    )
    css = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("styles.css")
        .read_text(encoding="utf-8")
    )

    assert '<div class="system-state visually-hidden" id="system-state" role="status">' in html
    assert ".workflow-nav" in css
    assert "flex-wrap: wrap" in css
    assert "position: sticky;" in css
    assert "top: var(--app-header-height);" in css
    nav_body = css.split(".nav-item {", 1)[1].split(".nav-item.is-active", 1)[0]
    assert "background: transparent;" in nav_body
    assert "border: 0;" in nav_body
    assert "text-decoration: none;" in nav_body
    active_body = css.split(".nav-item.is-active {", 1)[1].split(".nav-item.is-active::after", 1)[0]
    assert "color: var(--brand-menu-blue);" in active_body
    assert ".nav-item.is-active::after" in css
    assert "height: 2px;" in css
    assert ".folder-tabs" not in css


def test_workspace_spacing_remediation_uses_stable_sticky_geometry() -> None:
    css = html_or_script("styles.css")
    script = html_or_script("app.js")

    assert "--app-header-height: 42px;" in css
    assert "--workflow-nav-height: 32px;" in css
    assert "--workflow-nav-current-height: var(--workflow-nav-height);" in css
    assert "--report-scroll-margin-top: 168px;" in css
    header_body = css.split(".app-header {", 1)[1].split(".app-title", 1)[0]
    assert "margin: 0 -26px;" in header_body
    assert "padding: 0 26px;" in header_body
    app_title_body = css.split(".app-title {", 1)[1].split(".app-header-actions", 1)[0]
    assert "font-size: 14px;" in app_title_body
    assert "text-transform: uppercase" not in app_title_body
    assert '<h1 class="app-title">Аналитика</h1>' in html_or_script("index.html")
    assert ">Отчёты</button>" in html_or_script("index.html")
    scope_body = css.split(".scope-panel {", 1)[1].split(".scope-toolbar", 1)[0]
    assert "flex: 0 0 46px;" in scope_body
    assert "padding: 5px 0;" in scope_body
    assert "position: static;" in scope_body
    assert "top: auto;" in scope_body
    assert ".context-coverage-note:empty" in css
    assert ".breadcrumb-row:empty" in css
    assert "scroll-margin-top: var(--report-scroll-margin-top);" in css
    assert "function stickyStackOffset()" in script
    assert "function setupStickyGeometryTracking()" in script
    assert "new ResizeObserver(scheduleStickyGeometryUpdate)" in script
    assert 'document.documentElement.style.setProperty("--workflow-nav-current-height"' in script
    assert 'document.documentElement.style.setProperty("--report-scroll-margin-top"' in script
    assert "const stickyOffset = stickyStackOffset();" in script
    assert "const stickyOffset = 148;" not in script
    assert "boundingClientRect().top - 150" not in script


def test_top_workspace_uses_flat_scope_and_human_context_summary() -> None:
    html = (
        resources.files("retail_analytics.dashboard.templates")
        .joinpath("index.html")
        .read_text(encoding="utf-8")
    )
    css = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("styles.css")
        .read_text(encoding="utf-8")
    )
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    assert "scope-toolbar" in html
    assert "filter-drawer" not in html
    assert "filter-count" not in html
    assert "filter-chevron" not in html
    assert "filter-active-chips" not in html
    assert "reset-filters" in html
    assert "context-coverage-note" in html
    assert "retailer-identity" in html
    assert "retailer-select-control" in html
    assert html.count('id="private-label-scope"') == 1
    assert html.count('id="private-label-toggle"') == 0
    assert "Весь ассортимент" in html
    assert "Без выбранного ассортимента" in html
    assert "Только выбранный ассортимент" in html
    assert 'id="breadcrumb-row"' in html
    assert 'data-drill-grain="category"' not in html
    assert 'document.getElementById("context-coverage-note").textContent = coverageNoteText(response);' in script
    context_body = script.split("function renderContextStrip", 1)[1].split("function renderBreadcrumb", 1)[0]
    assert "runtime.display_label" not in context_body
    assert "contextSummaryText(response)" in context_body
    assert "`${available} из ${requested} периодов доступны`" not in context_body
    assert 'INCLUDE: "Весь ассортимент"' in script
    assert 'EXCLUDE: `Без ${scopeName}`' in script
    assert 'ONLY: `Только ${scopeName}`' in script
    assert "function renderRetailerIdentity()" in script
    assert "control?.classList.add(\"has-retailer-filter\");" in script
    assert "selectControl?.classList.remove(\"is-hidden\");" in script
    assert "identity?.classList.add(\"is-hidden\");" in script
    assert 'document.getElementById("retailer-control")?.addEventListener("click"' in script
    assert "retailerSelect.showPicker?.();" in script
    assert 'data-clear-pending-filter="category"' in html
    assert 'data-inline-clear-filter="category"' in html
    assert 'document.querySelector(`[data-inline-clear-filter="${id}"]`)?.classList.toggle("is-hidden", selected.length === 0);' in script
    assert "function breadcrumbLabel(grain, value)" in script
    assert "Все данные › Категория" not in html
    assert "row.classList.add(\"is-empty\")" in script
    period_body = css.split(".period-control {", 1)[1].split(".period-mode", 1)[0]
    assert "background: transparent;" in period_body
    assert "border-radius: 0;" in period_body
    assert "position: relative;" in period_body
    assert ".period-popover" in css
    assert 'id="period-popover-button"' in html
    assert 'aria-haspopup="dialog"' in html
    assert 'id="period-summary"' in html
    popover_body = css.split(".period-popover {", 1)[1].split(".period-mode", 1)[0]
    assert "width: min(600px, calc(100vw - 32px));" in popover_body
    assert "max-height: min(520px, calc(100vh - 132px));" in popover_body
    assert "overflow-x: hidden;" in popover_body
    assert "overflow-y: auto;" in popover_body
    assert "padding: 10px;" in popover_body
    fields_body = css.split(".period-fields {", 1)[1].split(".period-fields--available", 1)[0]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in fields_body
    assert 'class="period-fields period-fields--single is-hidden" id="single-fields"' in html
    assert 'class="period-fields period-fields--compare" id="compare-fields"' in html
    assert ".period-fields--available" in css
    assert "grid-template-columns: minmax(154px, 180px) minmax(0, 1fr);" in css
    assert 'class="period-card period-card--months derived-field"' in html
    assert 'id="available-months-current"' in html
    assert 'id="available-months-reference"' in html
    assert 'class="period-policy">MATCHED_AVAILABLE_MONTHS</small>' in html
    derived_body = css.split(".derived-field strong {", 1)[1].split(".filter-count", 1)[0]
    assert "overflow: hidden;" in derived_body
    assert "overflow-wrap: anywhere;" in derived_body
    assert ".period-policy" in css
    assert "color: var(--text-muted);" in css.split(".period-policy {", 1)[1].split("}", 1)[0]
    assert "data-toggle-full-list-filter" not in html.split('id="period-popover"', 1)[1].split('<div class="filter-grid"', 1)[0]
    active_mode_body = css.split(".mode-button.is-active {", 1)[1].split(".period-fields", 1)[0]
    assert "var(--brand-secondary)" not in active_mode_body
    assert "rgba(42, 125, 225, 0.1)" in active_mode_body


def test_overview_production_controls_are_real_or_truthfully_disabled() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    assert 'data-header-action="reports" aria-controls="reports-panel"' in html
    assert 'data-header-action="settings"' in html
    assert 'title="Настройки будут подключены позже" disabled' in html
    assert 'data-header-action="help"' in html
    assert 'title="Помощь будет подключена позже" disabled' in html
    assert 'id="reports-panel"' in html
    assert "function openReportsPanel()" in script
    assert "Раздел будет доступен позже" not in script
    assert "showToast(\"Раздел будет доступен позже." not in script


def test_overview_large_filters_use_runtime_backed_comboboxes() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    for filter_id in ("category", "manufacturer", "brand", "sku", "store"):
        assert f'data-filter-trigger="{filter_id}"' in html
        assert f'id="{filter_id}-search"' in html
        assert 'role="combobox"' in html
        assert f'aria-controls="{filter_id}-options"' in html
        assert f'id="{filter_id}-filter" class="native-filter-select" multiple' in html
        assert f'id="{filter_id}-filter-popover" role="dialog"' in html
        assert f'id="{filter_id}-options" role="group"' in html
        assert f'data-select-all="{filter_id}"' in html
        assert f'data-clear-pending-filter="{filter_id}"' in html
        assert f'data-inline-clear-filter="{filter_id}"' in html
        assert f'data-apply-filter="{filter_id}"' in html
        assert f'data-toggle-full-list-filter="{filter_id}"' in html
        footer = html.split(f'id="{filter_id}-filter-popover"', 1)[1].split("</div>\n              </div>", 1)[0]
        assert 'class="filter-footer-left"' in footer
        assert 'class="filter-footer-right"' in footer
        assert footer.index('class="filter-footer-left"') < footer.index(f'data-toggle-full-list-filter="{filter_id}"')
        assert footer.index(f'data-toggle-full-list-filter="{filter_id}"') < footer.index(f'id="{filter_id}-selected-count"')
        assert footer.index('class="filter-footer-right"') < footer.index(f'data-clear-pending-filter="{filter_id}"')
        assert footer.index(f'data-clear-pending-filter="{filter_id}"') < footer.index(f'data-apply-filter="{filter_id}"')

    assert "function applyPendingFilter(id)" in script
    assert "state.pendingFilters[id]" in script
    assert "expandedFilters: {}" in script
    assert "state.filters[id] = next;" in script
    assert "function renderFilterOptions(id)" in script
    assert "function visibleEntityOptions(id)" in script
    assert "state.expandedFilters[id] ? values : values.slice(0, maxComboboxOptions)" in script
    assert "const available = visibleEntityOptions(id);" in script
    assert 'document.querySelectorAll("[data-toggle-full-list-filter]")' in script
    assert "state.expandedFilters[id] = !state.expandedFilters[id];" in script
    assert 'document.getElementById(`${id}-filter-popover`)?.classList.toggle("is-expanded", Boolean(state.expandedFilters[id]));' in script
    assert 'fullList.textContent = expanded ? "Свернуть список" : "Показать весь список";' in script
    assert "Показан весь список" in script
    select_visible_body = script.split('document.querySelector(`[data-select-all="${id}"]`)', 1)[1].split("document.querySelectorAll(\"[data-clear-pending-filter]\")", 1)[0]
    assert "const next = new Set(pendingValuesForFilter(id));" in select_visible_body
    assert "if (event.target.checked) next.add(item.value);" in select_visible_body
    assert "else next.delete(item.value);" in select_visible_body
    assert "state.pendingFilters[id] = Array.from(next);" in select_visible_body
    assert "rankedEntityOptions(state.options.entities?.[id] || [], state.filterQueries[id] || \"\")" in script
    assert "function searchRank(item, query)" in script
    assert "label.startsWith(query)" in script
    assert "item.search_aliases" in script
    assert "item.display_name" in script
    assert "item.secondary_label" in script
    assert "haystack.includes(query)" in script
    assert 'primary.className = "filter-option-primary"' in script
    assert 'secondary.className = "filter-option-secondary"' in script
    assert "Показано ${visibleValues.length} из ${totalCount}" in script
    assert "filter-popover.is-expanded" in html_or_script("styles.css")
    footer_body = html_or_script("styles.css").split(".filter-popover-footer {", 1)[1].split(".filter-clear-action", 1)[0]
    assert "display: flex;" in footer_body
    assert "justify-content: space-between;" in footer_body
    assert ".filter-footer-left" in footer_body
    assert ".filter-footer-right" in footer_body
    assert "white-space: nowrap;" in html_or_script("styles.css").split(".filter-clear-action,", 1)[1].split(".filter-clear-action,", 1)[0]
    assert '"store": {' not in script
    assert "Фильтр ТТ будет подключён отдельно" not in script
    assert "function handleFilterSearchKeydown(event, id)" in script
    assert "function handleFilterOptionKeydown(event, id, index)" in script
    assert "event.key === \"ArrowUp\"" in script
    assert "event.key === \"Home\"" in script
    assert "event.key === \"End\"" in script
    assert "event.key === \"Enter\"" in script
    assert "input.addEventListener(\"blur\"" not in script
    search_key_body = script.split("function handleFilterSearchKeydown", 1)[1].split("function handleFilterOptionKeydown", 1)[0]
    assert 'document.getElementById(`${id}-filter-trigger`)?.focus();' in search_key_body
    pending_clear_body = script.split('document.querySelectorAll("[data-clear-pending-filter]")', 1)[1].split('document.querySelectorAll("[data-inline-clear-filter]")', 1)[0]
    assert "state.pendingFilters[button.dataset.clearPendingFilter] = [];" in pending_clear_body
    assert "runActiveViewQuery" not in pending_clear_body
    assert "clearEntityFilter(button.dataset.inlineClearFilter)" in script
    assert "resetAllEntityFilters();" in script
    assert "entityDisplayLabel(id, value)" in script
    assert "values.slice(0, 250)" not in script


def test_scope_toolbar_uses_single_row_multiselect_contract() -> None:
    html = html_or_script("index.html")
    css = html_or_script("styles.css")
    scope_body = html.split('<section class="scope-panel"', 1)[1].split("</section>", 1)[0]

    expected_order = [
        'id="retailer-control"',
        'id="period-popover-button"',
        'data-filter-trigger="category"',
        'data-filter-trigger="manufacturer"',
        'data-filter-trigger="brand"',
        'data-filter-trigger="sku"',
        'data-filter-trigger="store"',
        'id="private-label-scope"',
    ]
    positions = [scope_body.index(marker) for marker in expected_order]
    assert positions == sorted(positions)
    assert "filter-grid" in scope_body
    filter_grid_body = css.split(".filter-grid", 1)[1].split(".native-filter-select", 1)[0]
    assert "display: flex;" in filter_grid_body
    assert "gap: 7px;" in filter_grid_body
    assert "align-items: center;" in filter_grid_body
    assert scope_body.count("native-filter-select") == 5
    assert scope_body.count('id="private-label-scope"') == 1
    assert "filter-chip" not in html
    assert "data-combobox" not in html


def test_filter_toolbar_visual_noise_contract_keeps_labels_above_controls() -> None:
    html = html_or_script("index.html")
    css = html_or_script("styles.css")
    script = html_or_script("app.js")
    scope_body = html.split('<section class="scope-panel"', 1)[1].split("</section>", 1)[0]

    for label in ("Сеть", "Период", "Категория", "Производитель", "Бренд", "SKU", "ТТ", "СТМ"):
        assert '<span class="scope-label' in scope_body
        assert label in scope_body

    assert '<span class="scope-label">Категория</span>' in scope_body
    assert '<span class="scope-label">Производитель</span>' in scope_body
    assert '<span class="scope-label">Бренд</span>' in scope_body
    assert '<span class="scope-label">SKU</span>' in scope_body
    assert '<span class="scope-label">ТТ</span>' in scope_body
    assert '<span class="scope-label" id="private-label-label">СТМ</span>' in scope_body
    assert 'placeholder="Все' not in scope_body
    assert 'class="control control-retailer is-hidden" id="retailer-select-control"' in scope_body
    assert ".control-retailer > span" in css
    assert "display: none;" in css.split(".control-retailer > span", 1)[1].split("}", 1)[0]
    assert "cursor: pointer;" in css.split(".control-retailer select {", 1)[1].split("}", 1)[0]

    label_body = css.split(".scope-label {", 1)[1].split(".report-identity", 1)[0]
    assert "font-size: 10px;" in label_body
    assert "font-weight: 400;" in label_body
    assert "letter-spacing: 0;" in label_body

    assert 'class="scope-value filter-summary is-default" id="category-filter-summary">Все</span>' in scope_body
    assert 'class="scope-value filter-summary is-default" id="manufacturer-filter-summary">Все</span>' in scope_body
    assert 'class="scope-value filter-summary is-default" id="brand-filter-summary">Все</span>' in scope_body
    assert 'class="scope-value filter-summary is-default" id="sku-filter-summary">Все</span>' in scope_body
    assert 'class="scope-value filter-summary is-default" id="store-filter-summary">Все</span>' in scope_body
    assert 'INCLUDE: "Весь ассортимент"' in script
    assert 'document.getElementById("private-label-label").textContent = "СТМ";' in script


def test_filter_toolbar_visual_noise_contract_uses_quiet_value_states() -> None:
    css = html_or_script("styles.css")
    script = html_or_script("app.js")

    scope_value_body = css.split(".scope-value,", 1)[1].split(".scope-value.is-default", 1)[0]
    assert "font-weight: 400;" in scope_value_body
    default_body = css.split(".scope-value.is-default {", 1)[1].split(".scope-value.is-active-value", 1)[0]
    assert "color: var(--text-muted);" in default_body
    assert "font-weight: 400;" in default_body
    active_body = css.split(".scope-value.is-active-value {", 1)[1].split(".report-identity span", 1)[0]
    assert "color: var(--text-primary);" in active_body
    assert "font-weight: 500;" in active_body
    assert "font-weight: 600;" not in css.split(".filter-trigger {", 1)[1].split(".filter-trigger span", 1)[0]
    assert "font-weight: 700;" not in css.split(".filter-trigger {", 1)[1].split(".filter-trigger span", 1)[0]
    assert 'summary.classList.toggle("is-default", selected.length === 0);' in script
    assert 'summary.classList.toggle("is-active-value", selected.length > 0);' in script
    assert 'const text = labels.length === 1 ? labels[0] : `${labels.length} выбрано`;' in script
    assert 'select?.classList.toggle("is-default", select.value === "INCLUDE");' in script
    assert 'select?.classList.toggle("is-active-value", select.value !== "INCLUDE");' in script


def test_filter_toolbar_visual_noise_contract_groups_primary_scope_quietly() -> None:
    css = html_or_script("styles.css")
    script = html_or_script("app.js")

    toolbar_body = css.split(".scope-toolbar {", 1)[1].split(".control,", 1)[0]
    assert "display: flex;" in toolbar_body
    assert "gap: 7px;" in toolbar_body
    assert "min-height: 36px;" in toolbar_body
    control_body = css.split(".scope-control,", 1)[1].split(".scope-trigger,", 1)[0]
    assert "var(--scope-control-bg)" in css
    assert "var(--scope-control-border)" in css
    assert "box-shadow" not in control_body
    assert 'const cell = document.querySelector(`.multi-filter[data-filter="${id}"]`);' in script
    assert 'cell?.addEventListener("click", (event) => {' in script
    assert 'event.target.closest(".filter-popover, .filter-inline-clear, select, input, .filter-trigger")' in script
    assert "openFilterPopover(id);" in script
    assert 'if (!["Enter", " "].includes(event.key)) return;' in script
    assert "event.stopPropagation();" in script
    assert "cell?.classList.toggle(\"has-selection\", selected.length > 0);" in script

    filter_cell_body = css.split(".filter-grid > .scope-field {", 1)[1].split(".filter-grid > .scope-field:hover", 1)[0]
    assert "overflow: hidden;" not in filter_cell_body
    assert "white-space: nowrap;" in filter_cell_body
    assert ".filter-grid > .scope-field.has-selection" in css
    trigger_body = css.split(".filter-trigger {", 1)[1].split(".filter-trigger span", 1)[0]
    assert "flex: 1 1 auto;" in trigger_body
    assert "min-width: 0;" in trigger_body
    summary_body = css.split(".filter-trigger span {", 1)[1].split(".filter-trigger.has-selection", 1)[0]
    assert "display: block;" in summary_body
    assert "min-width: 0;" in summary_body
    assert "max-width: 100%;" in summary_body
    assert "overflow: hidden;" in summary_body
    assert "text-overflow: ellipsis;" in summary_body
    clear_body = css.split(".filter-inline-clear {", 1)[1].split(".filter-inline-clear:hover", 1)[0]
    assert "position: absolute" not in clear_body
    assert "flex: 0 0 auto;" in clear_body
    assert "margin-left: 4px;" in clear_body
    assert 'aria-label="Очистить бренд"' in html_or_script("index.html")


def test_browser_filter_state_is_staged_multi_value_and_applied_once() -> None:
    script = html_or_script("app.js")

    assert "filters: { category: [], manufacturer: [], brand: [], sku: [], store: [] }" in script
    assert "pendingFilters: {}" in script
    assert "values.forEach((value) => params.append(key, value));" in script
    assert "state.filters[id] = next;" in script
    input_handler = script.split('document.getElementById(`${id}-search`)?.addEventListener("input"', 1)[1].split('document.getElementById(`${id}-search`)?.addEventListener("keydown"', 1)[0]
    assert "renderFilterOptions(id);" in input_handler
    assert "runActiveViewQuery" not in input_handler
    apply_body = script.split("async function applyPendingFilter(id)", 1)[1].split("function handleFilterSearchKeydown", 1)[0]
    assert "await refreshRuntimeOptions();" in apply_body
    assert "await runActiveViewQuery();" in apply_body
    assert "resetChildFilters(id);" in apply_body


def test_dashboard_options_parent_filters_preserve_multi_values() -> None:
    params = {
        "category": ["water", "juice", ""],
        "manufacturer": ["maker_a", "maker_b"],
        "brand": [""],
    }

    assert _parent_filters(params) == {
        "category": ("water", "juice"),
        "manufacturer": ("maker_a", "maker_b"),
    }


def test_source_like_filter_options_use_active_mart_source_revisions(tmp_path) -> None:
    runtime = build_synthetic_dashboard_runtime(tmp_path)
    active_build = runtime.query_service.mart_builds[0]
    other_approved_build = replace(
        active_build,
        mart_build_id="build_dashboard_other_approved",
        source_revision_ids=("revision_other_approved",),
        analysis_run_ids=("analysis_dashboard_other_approved",),
    )
    runtime.query_service.mart_builds = (active_build, other_approved_build)
    source_like_path = tmp_path / "source_like_rows.parquet"
    pl.DataFrame(
        [
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "source_revision_id": "revision_dashboard_synthetic",
                "period": date(2026, 6, 1),
                "category": "CATEGORY_ACTIVE",
                "manufacturer": "MANUFACTURER_ACTIVE",
                "brand": "BRAND_ACTIVE",
                "canonical_product_id": "SKU_ACTIVE",
                "sku_name": "Readable Active SKU",
                "canonical_store_id": "STORE_ACTIVE",
                "source_store_id": "Store Active Label",
                "private_label_flag": False,
            },
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "source_revision_id": "revision_stale",
                "period": date(2026, 6, 1),
                "category": "CATEGORY_STALE",
                "manufacturer": "MANUFACTURER_STALE",
                "brand": "BRAND_STALE",
                "canonical_product_id": "SKU_STALE",
                "sku_name": "Readable Stale SKU",
                "canonical_store_id": "STORE_STALE",
                "source_store_id": "Store Stale Label",
                "private_label_flag": False,
            },
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "source_revision_id": "revision_other_approved",
                "period": date(2026, 6, 1),
                "category": "CATEGORY_OTHER_BUILD",
                "manufacturer": "MANUFACTURER_OTHER_BUILD",
                "brand": "BRAND_OTHER_BUILD",
                "canonical_product_id": "SKU_OTHER_BUILD",
                "sku_name": "Readable Other SKU",
                "canonical_store_id": "STORE_OTHER_BUILD",
                "source_store_id": "Store Other Approved Build",
                "private_label_flag": False,
            },
        ]
    ).write_parquet(source_like_path)
    runtime = replace(runtime, source_like_rows_path=source_like_path)

    options = runtime.options_metadata(
        retailer_id="retailer_a",
        source_id="source_a",
        private_label_scope="INCLUDE",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
    )
    entities = options["entities"]

    assert [item["value"] for item in entities["category"]] == ["CATEGORY_ACTIVE"]
    assert [item["value"] for item in entities["manufacturer"]] == ["MANUFACTURER_ACTIVE"]
    assert [item["value"] for item in entities["brand"]] == ["BRAND_ACTIVE"]
    assert [item["value"] for item in entities["sku"]] == ["SKU_ACTIVE"]
    assert [item["label"] for item in entities["sku"]] == ["Readable Active SKU"]
    assert [item["display_name"] for item in entities["sku"]] == ["Readable Active SKU"]
    assert "SKU_ACTIVE" in entities["sku"][0]["search_aliases"]
    assert [item["value"] for item in entities["store"]] == ["STORE_ACTIVE"]
    assert [item["label"] for item in entities["store"]] == ["Store Active Label"]


def test_sku_filter_options_are_name_first_but_identity_stable(tmp_path) -> None:
    runtime = build_synthetic_dashboard_runtime(tmp_path)
    source_like_path = tmp_path / "source_like_rows.parquet"
    pl.DataFrame(
        [
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "source_revision_id": "revision_dashboard_synthetic",
                "period": date(2026, 6, 1),
                "category": "CATEGORY_ACTIVE",
                "manufacturer": "MANUFACTURER_ACTIVE",
                "brand": "BRAND_ACTIVE",
                "canonical_product_id": "SKU_A",
                "sku_name": "Readable SKU",
                "package": "PACK_A",
                "volume_l": 0.5,
                "canonical_store_id": "STORE_ACTIVE",
                "private_label_flag": False,
            },
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "source_revision_id": "revision_dashboard_synthetic",
                "period": date(2026, 6, 1),
                "category": "CATEGORY_ACTIVE",
                "manufacturer": "MANUFACTURER_ACTIVE",
                "brand": "BRAND_ACTIVE",
                "canonical_product_id": "SKU_B",
                "sku_name": "Readable SKU",
                "package": "PACK_B",
                "volume_l": 1.0,
                "canonical_store_id": "STORE_ACTIVE",
                "private_label_flag": False,
            },
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "source_revision_id": "revision_dashboard_synthetic",
                "period": date(2026, 6, 1),
                "category": "CATEGORY_ACTIVE",
                "manufacturer": "MANUFACTURER_ACTIVE",
                "brand": "BRAND_ACTIVE",
                "canonical_product_id": "SKU_MISSING",
                "sku_name": "",
                "canonical_store_id": "STORE_ACTIVE",
                "private_label_flag": False,
            },
        ]
    ).write_parquet(source_like_path)
    runtime = replace(runtime, source_like_rows_path=source_like_path)

    options = runtime.options_metadata(
        retailer_id="retailer_a",
        source_id="source_a",
        private_label_scope="INCLUDE",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
    )["entities"]["sku"]
    by_value = {item["value"]: item for item in options}

    assert set(by_value) == {"SKU_A", "SKU_B", "SKU_MISSING"}
    assert by_value["SKU_A"]["display_name"] == "Readable SKU"
    assert by_value["SKU_A"]["label"].startswith("Readable SKU")
    assert by_value["SKU_A"]["value"] == "SKU_A"
    assert by_value["SKU_B"]["value"] == "SKU_B"
    assert by_value["SKU_A"]["label"] != by_value["SKU_B"]["label"]
    assert by_value["SKU_A"]["secondary_label"] == "PACK_A"
    assert by_value["SKU_B"]["secondary_label"] == "PACK_B"
    assert "SKU_A" in by_value["SKU_A"]["search_aliases"]
    assert by_value["SKU_MISSING"]["display_name"] == "SKU без названия"
    assert by_value["SKU_MISSING"]["label"] == "SKU без названия · PLU SKU_MISSING"
    assert by_value["SKU_MISSING"]["fallback_reason"] == "missing_sku_name"


def test_continuous_report_scope_keeps_filters_during_period_and_assortment_changes() -> None:
    script = html_or_script("app.js")

    period_handler = script.split('["period-single", "period-a", "period-available-end", "date-from", "date-to"].forEach((id) => {', 1)[1].split("async function applyScopeChange(work)", 1)[0]
    assortment_handler = script.split('document.getElementById("private-label-scope").addEventListener("change"', 1)[1].split('document.getElementById("preview-grain")', 1)[0]
    nav_handler = script.split('document.querySelectorAll("[data-view]")', 1)[1].split('document.querySelectorAll("[data-signal-kind]")', 1)[0]

    assert "await refreshRuntimeOptions();" in period_handler
    assert "resetEntities: true" not in period_handler
    assert "await refreshRuntimeOptions();" in assortment_handler
    assert "resetEntities: true" not in assortment_handler
    assert "async function applyScopeChange(work)" in script
    assert "const preservedView = state.scopeEditView || state.activeView || viewFromHash() || \"overview\";" in script
    assert "state.suppressScrollspyUntil = Date.now() + 1200;" in script
    assert "if (Date.now() < state.suppressScrollspyUntil) return;" in script
    assert "state.scopeEditView = viewFromHash() || state.activeView || \"overview\";" in script
    assert "await navigateToView(link.dataset.view);" in nav_handler
    assert "resetAllEntityFilters" not in nav_handler
    navigate_body = script.split("async function navigateToView(view)", 1)[1].split("function viewFromHash", 1)[0]
    assert "scrollToView(target);" in navigate_body
    assert "void ensureActiveViewData();" in navigate_body
    assert "ensureReportDataThroughView" not in script
    assert "window.addEventListener(\"scroll\"" in script
    breadcrumb_body = script.split("async function activateBreadcrumbGrain(grain)", 1)[1].split("function activeBreadcrumbGrainIndex", 1)[0]
    assert "invalidateLoadedViews();" in breadcrumb_body


def test_browser_script_invalidates_stale_cross_section_requests() -> None:
    script = html_or_script("app.js")

    assert "scopeVersion: 0" in script
    assert "sectionRequests: {}" in script
    assert "function sectionRequestToken(view)" in script
    assert "function isCurrentSectionRequest(token)" in script
    assert "function markInactiveSectionsPending()" in script
    invalidate_body = script.split("function invalidateLoadedViews()", 1)[1].split("function updatePressedGroup", 1)[0]
    assert "state.scopeVersion += 1;" in invalidate_body
    assert "state.loadedViews = {};" in invalidate_body
    assert "markInactiveSectionsPending();" in invalidate_body

    for view in ("overview", "sales_drivers", "portfolio_market", "stores", "signals", "data"):
        assert f'const token = sectionRequestToken("{view}");' in script
    assert script.count("if (!isCurrentSectionRequest(token)) return;") >= 6
    assert script.count("if (!isCurrentSectionRequest(token)) return;") >= 12


def test_browser_script_sends_backend_scope_fields_without_metric_formulas() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    assert "private_label_scope" in script
    assert "comparison_mode" in script
    assert "comparison_mode: selectedComparisonMode()" in script
    assert 'comparison_mode: state.periodMode === "AVAILABLE_MONTH_SET" ? "NONE" : selectedComparisonMode()' in script
    assert "period_mode" in script
    assert 'if (state.periodMode === "DATE_RANGE") return "DATE_RANGE";' in script
    assert 'if (state.periodMode === "AVAILABLE_MONTH_SET") return "AVAILABLE_MONTH_SET";' in script
    assert "grain_id" in script
    assert "metric_concepts" in script
    assert "entity_ids: entityIds" in script
    assert "entity_filters: selectedParentFiltersForGrain(grain)" in script
    assert "/api/dashboard/options" in script
    assert "state.options.periods" in script
    assert "chartResponse: null" in script
    assert "buildChartQueryPayload()" in script
    assert "const chartResponse = await postJson(\"/api/dashboard/query\", chartPayload);" in script
    assert "state.chartResponse = chartResponse;" in script
    assert "period_mode: \"DATE_RANGE\"" in script
    assert "comparison_mode: \"NONE\"" in script
    assert "const definition = overviewTrendDefinition(state.chartMetric);" in script
    assert "const model = definition ? overviewTrendModel(definition) : null;" in script
    assert "const coverage = model?.response || state.chartResponse || state.summaryResponse;" in script
    assert "state.tablePageSize: 50" not in script
    assert "tablePageSize: 40" in script
    assert "overviewPreviewRowLimit: 8" in script
    assert "entityIdsForSummary" in script
    assert "entityIdsForPreview" in script
    assert "function activateBreadcrumbGrain(grain)" in script
    assert "canActivateSummaryGrain(grain)" in script
    assert 'state.currentGrain = "network";' in script
    assert 'if (state.currentGrain === "network") return firstEntityIds("network", 1);' in script
    assert 'return ["network"]' not in script
    assert "selectedParentFiltersForGrain" in script
    assert "state.drilldownPath" in script
    assert "hasNonDrilldownFilters()" in script
    assert "Показаны первые" in script
    assert "CATEGORY_STANDARD" not in script
    assert "MANUFACTURER_A" not in script
    assert "SKU_A_001" not in script
    assert "STORE_A_001" not in script
    assert "private-label-scope" in script
    assert 'YOY: "Год к году"' in script
    assert 'MOM: "Месяц к месяцу"' in script
    assert 'PREVIOUS_AVAILABLE: "Предыдущий доступный период"' in script
    assert "comparisonLabels[state.comparisonMode]" in script
    assert "updateComparisonPeriodDisplay(response)" in script
    assert "comparison?.comparison_period_start" in script
    assert 'document.getElementById("period-b-derived")' in script
    assert "innerHTML" not in script
    assert "ONLY: `${scopeName}: только`" not in script
    assert "ONLY: `Только ${scopeName}`" in script
    assert 'entry.format === "percent" ? "percentage_points" : entry.format' in script
    assert "п.п." in script
    assert "retailer_margin_pct" in script
    assert "margin / revenue" not in script
    assert "sum(" not in script.lower()
    assert 'postJson("/api/dashboard/contribution", payload)' in script
    assert "child_delta / parent_delta" not in script
    assert "contribution_share = " not in script
    assert "Вклад в изменение" in script
    assert "Где произошло изменение?" in script
    assert "Объекты в выбранном срезе" in script
    assert "Ранжирование по изменению:" in script
    assert "Для выбранного показателя вклад в изменение не рассчитывается." in script
    assert "Вклад в изменение не рассчитывается для дополнительного фильтра" in script
    assert "Для этой пары уровней вклад пока недоступен." in script


def test_overview_uses_ordered_business_kpi_surface() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    overview_surface = script.split("const overviewKpiDefinitions = ", 1)[1].split("];", 1)[0]
    expected_order = [
        '"units"',
        '"revenue_vat"',
        '"retailer_margin_abs"',
        '"retailer_margin_pct"',
        '"velocity"',
        '"distribution"',
        '"weighted_distribution"',
        '"active_sku_count"',
        '"average_price_per_liter"',
        '"weighted_shelf_price_vat"',
        '"weighted_input_price_vat"',
    ]
    positions = [overview_surface.index(item) for item in expected_order]
    assert positions == sorted(positions)
    assert 'label: "Продажи", unit: "шт."' in overview_surface
    assert 'label: "Оборот", unit: "₽"' in overview_surface
    assert 'label: "Маржа", unit: "₽"' in overview_surface
    assert 'label: "Маржинальность", unit: "%"' in overview_surface
    assert 'label: "V\\u0050O", unit: "шт./ТТ"' in overview_surface
    assert 'label: "ND"' in overview_surface
    assert 'fullLabel: "Нумерическая дистрибуция"' in overview_surface
    assert 'label: "WD"' in overview_surface
    assert 'fullLabel: "Взвешенная дистрибуция"' in overview_surface
    assert 'label: "Цена за литр"' in overview_surface
    assert 'label: "Полочная цена"' in overview_surface
    assert 'label: "Входная цена"' in overview_surface
    assert 'unit: "₽/л"' in overview_surface
    assert 'label: "Нумерическая дистрибуция"' not in overview_surface
    assert 'label: "Взвешенная дистрибуция"' not in overview_surface
    assert "Средняя цена на полке" not in overview_surface
    assert "Средняя цена входа" not in overview_surface
    assert "с НДС" not in overview_surface
    assert "на ТТ" not in overview_surface
    assert "₽/уп." not in overview_surface
    assert "Оборот, шт." not in overview_surface
    assert "Маржинальность, ₽" not in overview_surface
    assert "Маржинальность, %" not in overview_surface
    assert "reserved: true" not in overview_surface
    assert ("reserved_" + "kpi_slot") not in overview_surface
    assert 'source: "reserved"' not in overview_surface
    assert "primaryKpis" not in script


def test_overview_kpi_groups_preserve_business_reading_order() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    overview_surface = script.split("const overviewKpiDefinitions = ", 1)[1].split("];", 1)[0]
    overview_groups = script.split("const overviewKpiGroups = ", 1)[1].split("];", 1)[0]
    assert overview_surface.count("slot:") == 11
    assert 'id: "result", label: "РЕЗУЛЬТАТ", visualTier: "primary"' in overview_groups
    assert 'id: "coverage", label: "ПРИСУТСТВИЕ", visualTier: "secondary"' in overview_groups
    assert "ПОКРЫТИЕ · СКОРОСТЬ · АССОРТИМЕНТ" not in overview_groups
    assert 'id: "price", label: "ЦЕНА", visualTier: "secondary"' in overview_groups
    assert overview_surface.index('"retailer_margin_abs"') < overview_surface.index('"retailer_margin_pct"')
    assert overview_surface.index('"retailer_margin_pct"') < overview_surface.index('"velocity"')
    assert 'slot: 5, group: "result", visualTier: "primary", concept: "velocity"' in overview_surface
    assert 'slot: 6, group: "coverage", visualTier: "secondary", concept: "distribution"' in overview_surface
    assert 'slot: 7,\n    group: "coverage",\n    visualTier: "secondary",\n    concept: "weighted_distribution"' in overview_surface
    assert 'slot: 8, group: "coverage", visualTier: "secondary", concept: "active_sku_count"' in overview_surface
    assert overview_surface.index('"distribution"') < overview_surface.index('"active_sku_count"')
    assert overview_surface.index('"distribution"') < overview_surface.index('"weighted_distribution"')
    assert overview_surface.index('"weighted_distribution"') < overview_surface.index('"active_sku_count"')
    assert overview_surface.index('"average_price_per_liter"') < overview_surface.index('"weighted_shelf_price_vat"')
    assert overview_surface.index('"weighted_shelf_price_vat"') < overview_surface.index('"weighted_input_price_vat"')
    assert "renderKpiPartialComparisonNotice(models)" in script
    assert "renderKpiGroup(group, (definition) => renderKpiCard(definition, models.get(definition.concept)))" in script
    assert "card.dataset.kpiGroup = definition.group" in script


def test_overview_kpi_cards_use_compact_matrix_without_comparator_or_sparklines() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )
    overview_surface = script.split("const overviewKpiDefinitions = ", 1)[1].split("];", 1)[0]
    kpi_renderer = script.split("function renderKpiCard", 1)[1].split("function overviewKpiModel", 1)[0]

    assert "microtrend" not in overview_surface
    assert "function renderKpiMicrotrend" not in script
    assert "function kpiMicrotrendPoints" not in script
    assert "kpi-sparkline" not in script
    assert "kpi-microtrend" not in script
    assert "function renderKpiComparator" not in script
    assert "function kpiComparatorScale" not in script
    assert "function kpiComparatorMarker" not in script
    assert "kpi-comparator" not in script
    assert "kpi-card-content" in kpi_renderer
    assert "kpi-card-main" in kpi_renderer
    assert "renderKpiHeadline(definition, model)" in kpi_renderer
    assert "renderKpiEvidenceRow(" in kpi_renderer
    assert '"current"' in kpi_renderer
    assert '"reference"' in kpi_renderer
    assert 'card.setAttribute("role", "button");' in kpi_renderer
    assert 'card.setAttribute("aria-pressed", isSelectedMetric ? "true" : "false");' in kpi_renderer
    assert 'card.addEventListener("keydown", async (event) => {' in kpi_renderer
    assert 'appendText(headline, "span", "выбран").className = "visually-hidden";' in script
    assert "kpiCurrentPeriodText(comparison)" in kpi_renderer
    assert "kpiReferencePeriodText(comparison)" in kpi_renderer
    assert "kpiCompactPeriodText(period)" in kpi_renderer
    assert "content.appendChild(left)" in kpi_renderer
    assert "card.dataset.kpiState = model.state" in kpi_renderer
    assert 'if (definition?.concept === "active_sku_count") return text;' in script
    assert "source: \"business_rule_required\"" not in overview_surface
    assert "const selectedDefinition = overviewTrendDefinition(state.chartMetric);" in script
    assert "const metricConcepts = selectedDefinition?.source === \"query\" ? [state.chartMetric] : [];" in script


def test_overview_kpi_matrix_removes_comparator_visual_while_preserving_direction_colors() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    assert "function renderKpiComparator" not in script
    assert "function kpiComparatorScale" not in script
    assert "function kpiComparatorWithMinimumSeparation" not in script
    assert "function kpiComparatorMarker" not in script
    assert "local-symmetric-current-reference" not in script
    assert ".kpi-comparator" not in styles
    assert ".kpi-comparator-track" not in styles
    assert ".kpi-comparator-marker" not in styles
    assert "deltaSemanticClass(definition.concept" not in script
    assert "kpiDirectionPresentationClass(deltaValue, deltaFormat)" in script
    assert "--status-positive" in styles
    assert "--status-negative" in styles
    assert "--status-neutral" in styles
    assert ".kpi-direction-up" in styles
    assert ".kpi-direction-down" in styles
    assert ".kpi-direction-zero" in styles


def test_overview_approved_kpis_are_backend_owned_without_frontend_formulas() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )
    overview_surface = script.split("const overviewKpiDefinitions = ", 1)[1].split("];", 1)[0]

    assert "BUSINESS_RULE_REQUIRED" not in overview_surface
    assert "Требуется утверждённая формула." not in overview_surface
    assert "Требуется правило веса и вселенной." not in overview_surface
    assert 'concept: "weighted_distribution"' in overview_surface
    assert 'concept: "average_price_per_liter"' in overview_surface
    assert "revenue_vat /" not in script
    assert "revenue_vat/" not in script
    assert "weighted_distribution =" not in script
    assert "average_price_per_liter =" not in script
    assert "const overviewQueryKpis" in script
    assert 'concept_ids: ["active_sku_count"]' in script
    assert "entity_filters: selectedFilterValuesForPortfolio()" in script


def test_overview_kpi_cards_show_reference_value_and_state_context() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )
    kpi_renderer = script.split("function renderKpiCard", 1)[1].split("function overviewKpiModel", 1)[0]
    kpi_helpers = script.split("function kpiContextText", 1)[1].split("function compactMetricText", 1)[0]

    assert "За выбранный период" not in kpi_renderer
    assert "без сравнения" not in kpi_renderer.lower()
    assert 'unit.className = "kpi-unit"' not in kpi_renderer
    assert "kpiValueWithUnit(overviewKpiValueText(result, entry, definition), definition)" in kpi_renderer
    assert 'content.className = "kpi-card-content"' in kpi_renderer
    assert 'left.className = "kpi-card-main"' in kpi_renderer
    assert 'if (model.state === "COMPLETE_COMPARE" || model.state === "ZERO_CHANGE") {' in kpi_renderer
    assert "if (isComparisonDisplayMode() && comparison)" not in kpi_renderer
    assert "const deltaFormat = kpiDeltaPresentationFormat(comparison, model.entry);" in kpi_renderer
    assert "const deltaValue = kpiDeltaPresentationValue(comparison, model.entry);" in kpi_renderer
    assert 'delta.className = `kpi-meta kpi-meta--delta ${kpiDirectionPresentationClass(deltaValue, deltaFormat)}`' in kpi_renderer
    assert 'deltaSlot.className = "kpi-meta kpi-meta--delta kpi-meta--delta-placeholder";' in kpi_renderer
    assert 'deltaSlot.setAttribute("aria-hidden", "true");' in kpi_renderer
    assert "text: kpiDeltaText(comparison, model.entry)" in kpi_renderer
    assert 'value: deltaValue,' in kpi_renderer
    assert 'format: deltaFormat,' in kpi_renderer
    assert 'className: kpiDirectionPresentationClass(deltaValue, deltaFormat)' in kpi_renderer
    assert 'model.state === "COMPLETE_COMPARE" || model.state === "ZERO_CHANGE"' in kpi_renderer
    assert 'left.appendChild(renderKpiEvidenceRow(' in kpi_renderer
    assert 'model.state === "CURRENT_ONLY_NO_REFERENCE"' in kpi_renderer
    assert "нет данных" in kpi_renderer
    assert "kpiMissingReferencePeriodText()" in kpi_renderer
    assert "renderKpiComparator(definition, model)" not in kpi_renderer
    assert "function renderKpiComparator" not in script
    assert "meta.textContent = kpiContextText(comparison, entry)" not in kpi_renderer
    assert "comparison.comparison_value" not in kpi_helpers
    assert 'return "";' in kpi_helpers
    assert "function kpiDeltaPresentationFormat(comparison, entry)" in kpi_helpers
    assert "function kpiDeltaPresentationValue(comparison, entry)" in kpi_helpers
    assert "return formatDeltaValue(presentationValue, presentationFormat);" in kpi_helpers
    assert 'if (entry.format === "percent") return deltaFormat;' in kpi_helpers
    assert 'return "percent";' in kpi_helpers
    assert "comparison.comparison_period_start" in kpi_helpers
    assert "function kpiValueWithUnit" in script
    assert "function conciseKpiUnavailableText" in script
    assert "Требуется бизнес-правило" in script
    assert 'left.appendChild(renderKpiEvidenceRow(\n      "current",\n      "",\n      "н/д",\n      null,\n      "kpi-na"\n    ));' in kpi_renderer
    assert "left.appendChild(renderKpiUnavailableReasonRow(conciseKpiUnavailableText(definition, model)))" in kpi_renderer
    assert 'appendText(left, "div", "н/д").className = "kpi-na";' not in kpi_renderer
    assert 'appendText(left, "div", conciseKpiUnavailableText(definition, model)).className = "kpi-unavailable-reason";' not in kpi_renderer
    assert "function renderKpiUnavailableReasonRow(text)" in script

    state_helpers = script.split("function overviewKpiState", 1)[1].split("function kpiReferencePeriodText", 1)[0]
    reference_helpers = script.split("function kpiReferencePeriodText", 1)[1].split("function overviewPortfolioItem", 1)[0]
    assert "function kpiCurrentPeriodText" in reference_helpers
    assert "function kpiCompactPeriodText" in reference_helpers
    assert "monthLabelsShort()[date.getMonth()]" in reference_helpers
    assert 'String(date.getFullYear()).slice(-2)' in reference_helpers
    assert "formatValue(comparison.comparison_value, model.entry.format)" in kpi_renderer
    assert 'return Number(comparison.delta) === 0 ? "ZERO_CHANGE" : "COMPLETE_COMPARE";' in state_helpers
    assert 'if (!isComparisonDisplayMode()) return "CURRENT_ONLY";' in state_helpers
    assert '"CURRENT_ONLY_NO_REFERENCE"' in state_helpers
    assert '"METRIC_UNSUPPORTED"' in state_helpers
    assert "kpiHasValidReference(comparison)" in state_helpers
    assert "comparison.current_value !== null" in state_helpers
    assert "comparison.comparison_value !== null" in state_helpers
    assert "comparison.delta !== null" in state_helpers
    assert "const explicitReference = document.getElementById(\"period-b\")?.value || \"\";" in reference_helpers
    assert "if (explicitReference) return explicitReference;" in reference_helpers
    assert 'if (selectedComparisonMode() === "YOY") return offsetPeriodMonth(current, -12);' in reference_helpers
    assert 'if (selectedComparisonMode() === "MOM") return offsetPeriodMonth(current, -1);' in reference_helpers
    assert 'if (selectedComparisonMode() === "PREVIOUS_AVAILABLE") return previousAvailablePeriod(current);' in reference_helpers
    assert 'if (state.periodMode === "AVAILABLE_MONTH_SET") return "сопоставимые месяцы";' in reference_helpers
    assert "function previousAvailablePeriod(current)" in reference_helpers
    assert ".filter((period) => period < current)" in reference_helpers
    assert ".at(-1) || \"\";" in reference_helpers
    assert "function offsetPeriodMonth(period, monthOffset)" in reference_helpers
    assert "toISOString()" not in reference_helpers


def test_overview_kpi_partial_comparison_notice_is_missing_reference_specific() -> None:
    script = html_or_script("app.js")
    notice_helpers = script.split("function renderKpiPartialComparisonNotice", 1)[1].split("function overviewKpiDefinitionsForGroup", 1)[0]

    assert "kpi-partial-comparison-notice" in notice_helpers
    assert 'models.get(definition.concept)?.state === "CURRENT_ONLY_NO_REFERENCE"' in notice_helpers
    assert "notice?.remove()" in notice_helpers
    assert "нет данных за" in notice_helpers
    assert "BUSINESS_RULE_REQUIRED" not in notice_helpers
    assert "METRIC_UNSUPPORTED" not in notice_helpers


def test_overview_portfolio_kpi_uses_backend_comparison_and_available_month_limitation() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )
    kpi_model = script.split("function overviewKpiModel", 1)[1].split("function overviewKpiHasBlockingLimitation", 1)[0]
    unavailable = script.split("function overviewKpiUnavailableText", 1)[1].split("function renderChart", 1)[0]

    assert "const comparison = overviewPortfolioKpiComparison(item);" in kpi_model
    assert "comparison," in kpi_model
    assert "item.reference_value" in kpi_model
    assert "item.delta" in kpi_model
    assert "item.pct_delta" in kpi_model
    assert "current_value: item.current_value" in kpi_model
    assert "comparison_value: item.reference_value" in kpi_model
    assert "comparison_period_start: kpiReferencePeriodCandidate()" in kpi_model
    assert "comparison_included_periods" in kpi_model
    assert "!overviewKpiPeriodUnsupported(definition)" in kpi_model
    assert "function overviewKpiPeriodUnsupported(definition)" in script
    assert '["active_sku_count"].includes(definition.concept)' in script
    assert "overviewKpiPeriodUnsupported(definition)" in unavailable


def test_overview_kpi_cards_are_compact_and_primary_only() -> None:
    css = html_or_script("styles.css")

    assert 'grid-template-areas:\n    "result result"\n    "coverage price"' in css
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in css
    assert ".kpi-group--result" in css
    assert ".kpi-group--coverage" in css
    assert ".kpi-group--price" in css
    assert ".kpi-group-label" in css
    kpi_block = css.split(".kpi-grid", 1)[1].split(".metric-value-button", 1)[0]
    assert "background: rgba(248, 250, 252, 0.78)" not in kpi_block
    assert "border: 1px solid rgba(219, 227, 238, 0.84)" not in kpi_block
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" not in kpi_block
    assert "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.18fr) minmax(0, 0.92fr)" in kpi_block
    assert "column-gap: 30px;" in kpi_block
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert "min-height: 104px" not in css
    assert "padding: 9px 10px 8px" not in css
    assert "min-height: 110px" not in css
    assert "padding: 4px 8px 5px" in kpi_block
    assert "padding: 5px 7px" not in kpi_block
    assert "border: 1px solid rgba(219, 227, 238, 0.66)" not in kpi_block
    assert ".kpi-headline" in kpi_block
    assert ".kpi-title" in kpi_block
    assert ".kpi-evidence-row" in kpi_block
    assert ".kpi-evidence-period" in kpi_block
    assert ".kpi-evidence-value" in kpi_block
    assert "display: flex;" in css.split(".kpi-evidence-row", 1)[1].split(".kpi-evidence-period", 1)[0]
    assert "font-size: 15px;" in css.split(".kpi-title", 1)[1].split(".kpi-evidence-row", 1)[0]
    assert "font-size: 18px;" in css.split(".kpi-meta--delta", 1)[1].split(".kpi-reference", 1)[0]
    assert "font-size: 18px;" in css.split(".kpi-evidence-value", 1)[1].split(".kpi-evidence-row--current", 1)[0]
    assert "font-size: 11.5px;" in css.split(".kpi-evidence-row--reference .kpi-evidence-value", 1)[1].split(".kpi-current-value", 1)[0]
    assert ".kpi-unit" not in css
    assert ".kpi-card-content" in css
    assert ".kpi-card-main" in css
    assert "align-items: flex-start" in css.split(".kpi-card-content", 1)[1].split(".kpi-card--primary", 1)[0]
    kpi_main_body = css.split(".kpi-card-main", 1)[1].split(".kpi-headline", 1)[0]
    assert "grid-template-rows: 23px 22px 13px;" in kpi_main_body
    assert "gap: 0" in kpi_main_body
    assert "min-height: 18px;" in css.split(".kpi-headline", 1)[1].split(".kpi-title", 1)[0]
    assert "min-height: 18px;" in css.split(".kpi-evidence-row", 1)[1].split(".kpi-evidence-period", 1)[0]
    assert ".kpi-evidence-row--reference {\n  min-height: 13px;" in css
    assert ".kpi-meta--delta" in css
    assert ".kpi-meta--delta-placeholder {\n  visibility: hidden;" in css
    assert '.kpi-meta--delta-placeholder::before {\n  content: "0";' in css
    assert ".kpi-card--primary .kpi-meta--delta" not in kpi_block
    assert ".kpi-reference" in css
    assert "gap: 5px" in css
    assert ".kpi-reference-value" in css
    assert ".kpi-reference-period" in css
    assert ".kpi-missing-reference" in css
    assert ".kpi-partial-comparison-notice" in css
    assert ".kpi-comparator" not in css
    assert ".kpi-comparator-track" not in css
    assert ".kpi-comparator-marker--reference" not in css
    assert ".kpi-comparator-marker--current" not in css
    assert ".kpi-microtrend" not in css
    assert ".kpi-sparkline-period" not in css
    assert ".kpi-sparkline-hitpoint" not in css
    assert ".kpi-sparkline-line" not in css
    kpi_card_body = css.split(".kpi-card {", 1)[1].split(".kpi-partial-comparison-notice", 1)[0]
    assert "font-weight: 700" not in kpi_card_body
    assert ".kpi-meta--delta .metric-delta-button {\n  font-weight: 400;" in css
    assert "white-space: nowrap" in css.split(".kpi-title", 1)[1].split(".kpi-evidence-row", 1)[0]
    selected_body = css.split(".kpi-card.is-chart-selected {", 1)[1].split(".kpi-card:hover", 1)[0]
    assert "background: var(--overview-brand-soft);" in selected_body
    assert "box-shadow: inset 0 -2px 0 var(--brand-menu-blue);" in selected_body
    assert ".kpi-card.is-chart-selected::before" in selected_body
    assert "content: none;" in selected_body
    assert ".kpi-card.is-chart-selected .kpi-title" in css
    assert "min-height: 132px" not in css
    assert "border-top: 2px solid var(--overview-section-line);" in kpi_block
    assert "border-left: 2px solid var(--overview-section-line);" in kpi_block
    assert "--overview-section-line: #c8d8e8;" in css
    label_body = css.split(".kpi-group-label", 1)[1].split(".kpi-group-cards", 1)[0]
    assert "padding-left: var(--kpi-group-label-inset, 8px);" in label_body
    assert "font-weight: 500;" in label_body
    assert "--kpi-group-label-inset: 6px;" in css.split(".kpi-group--result", 1)[1].split(".kpi-group--coverage", 1)[0]
    assert "--kpi-group-label-inset: 8px;" in css.split(".kpi-group--coverage", 1)[1].split(".kpi-group--price", 1)[0]
    assert "--kpi-group-label-inset: 8px;" in css.split(".kpi-group--price", 1)[1].split(".kpi-group-label", 1)[0]


def test_overview_chart_uses_month_axis_and_year_overlay_without_zero_fill() -> None:
    script = html_or_script("app.js")
    css = html_or_script("styles.css")

    assert "function chartYearSeries(points)" in script
    assert "function chartPathSegments(points)" in script
    assert "function chartGapBridgeSegments(points)" in script
    assert "function overviewMonthTooltip(monthIndex, series, entry)" in script
    assert "function chartYearClass(year)" in script
    assert "function monthLabelsShort()" in script
    assert "box.replaceChildren(buildOverviewSvgChart(points, entry))" in script
    assert "box.replaceChildren(buildSvgChart(points, entry))" in script
    assert 'return ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]' in script
    assert "monthIndex !== previous.monthIndex + 1" in script
    assert "point.monthIndex > previous.monthIndex + 1" in script
    assert "overview-chart-series-${paletteIndex}" in script
    assert "overview-chart-gap-bridge" in script
    assert "overview-chart-month-hover" in script
    assert "overview-chart-month-hitbox" in script
    assert "overview-chart-crosshair" in script
    assert "overviewMonthTooltip(monthIndex, series, entry)" in script
    assert "нет данных" in script
    assert "alignOverviewChartShell()" in script
    assert "function alignOverviewChartShell()" in script
    assert 'document.querySelector(\'#chart-box .month-grid-line[data-month-index="5"]\')' in script
    assert "shell.dataset.juneAlignmentDelta" in script
    assert "month-grid-line" in css
    assert "june-axis" not in css
    assert "#chart-box" in css
    assert "overview-chart-svg" in css
    assert "min-height: 320px" in css.split(".chart-svg", 1)[1].split(".overview-main .chart-svg", 1)[0]
    assert "height: 100%" in css.split(".overview-main .chart-svg", 1)[1].split("#chart-box", 1)[0]
    assert "height: 100%" in css.split(".overview-chart-svg", 1)[1].split(".grid-line", 1)[0]
    assert "#chart-box {\n  flex: 1 1 auto;" in css
    assert "min-height: 300px" not in css.split("#chart-box", 1)[1].split(".overview-chart-svg", 1)[0]
    assert "flex: 0 1 760px;" in css
    assert "width: min(760px, 100%);" in css
    assert "aspect-ratio: 1.72 / 1;" in css
    assert "stroke-dasharray: 7 6" in css
    assert "opacity: 0.38" in css
    assert ".overview-chart-point {" in css
    assert "fill: var(--chart-primary)" in css
    assert "cursor: crosshair" in css
    assert "white-space: pre-line" in css
    assert "stroke-width: 3" in css.split(".overview-chart-line", 1)[1].split(".overview-chart-gap-bridge", 1)[0]
    assert "font-weight: 400;" in css.split(".chart-legend", 1)[1].split(".chart-legend.overview-chart-series-1", 1)[0]
    assert "r: 4.2" in script
    overview_chart = script.split("function buildOverviewSvgChart", 1)[1].split("function buildSvgChart", 1)[0]
    assert "const width = 720;" in overview_chart
    assert "const height = 360;" in overview_chart
    assert "const pad = { left: 48, right: 24, top: 20, bottom: 40 };" in overview_chart
    assert "value || 0" not in overview_chart
    assert "comparison-point-marker" not in overview_chart
    assert "marker-label" not in overview_chart
    assert "chartYearClass(yearSeries.year)" in overview_chart
    assert "chartYearClass(seriesIndex)" not in overview_chart
    assert '"data-month-index": String(monthIndex)' in overview_chart
    assert "june-axis" not in overview_chart
    assert "data-gap-start" in overview_chart
    assert "data-gap-end" in overview_chart
    assert '"data-period": point.period' in overview_chart
    assert '"data-month-index": String(point.monthIndex)' in overview_chart
    assert '"data-value": String(point.value)' in overview_chart
    assert "r: 4.2" in overview_chart


def test_overview_comparative_trend_chart_uses_kpi_contract_and_local_limitations() -> None:
    script = html_or_script("app.js")
    html = html_or_script("index.html")
    css = html_or_script("styles.css")

    assert 'chartMetric: "units"' in script
    assert "const chartMetrics = overviewKpiDefinitions.map((definition) => definition.concept);" in script
    assert "renderChartMetricOptions()" in script
    assert "overviewKpiDefinitions.filter((definition) => definition.source !== \"reserved\")" in script
    assert "требуется правило" in script
    assert "function overviewTrendDefinition" in script
    assert "function overviewTrendModel" in script
    assert "function overviewTrendUnsupportedText" in script
    assert "function overviewTrendPoints" in script
    assert "function overviewTrendContextText" in script
    assert "function chronologicalMetricPoints" in script
    assert "chronologicalMetricPoints(rows, \"backend-trend-series\")" in script
    assert "recentChronologicalMetricPoints" not in script
    assert 'document.getElementById("chart-title").textContent = definition.label;' in script
    assert 'document.getElementById("chart-context").textContent = "· по месяцам · сравнение лет";' in script
    assert "backend-trend-series" in script
    assert "линии выровнены по месяцу" in script
    assert "сопоставимые доступные месяцы" in script
    assert "Показатель не поддерживает динамику сопоставимых месяцев." in script
    assert "Показатель недоступен для динамики по выбранной ТТ." in script
    assert "График не строит неподтверждённые или неподдержанные ряды." in script
    assert "Одна доступная точка:" not in script
    assert "Линия не строится без второй фактической точки." not in script
    assert "chartMetric === concept" in script
    assert "card.dataset.trendMetric = concept" in script
    assert "await selectOverviewTrendMetric(concept)" in script
    assert "if (event.target.closest(\"button, a, input, select, textarea\")) return;" in script
    assert 'state.activeProvenanceConcept = concept;' in script
    assert '"data-period": point.period' in script
    assert '"data-series-year": String(point.year)' in script
    assert '"data-value": String(point.value)' in script
    chart_year_series = script.split("function chartYearSeries(points)", 1)[1].split("function chartYearClass", 1)[0]
    assert "comparisonMarkerPeriods()" not in chart_year_series
    assert "yearPriority" not in chart_year_series
    assert ".sort(([left], [right]) => right - left)" in chart_year_series
    chart_year_class = script.split("function chartYearClass(year)", 1)[1].split("function chartPathSegments", 1)[0]
    assert "Math.abs(Number(year)) % 5" in chart_year_class
    assert "seriesIndex" not in chart_year_class
    assert "comparison_mode: \"NONE\"" in script.split("function buildChartQueryPayload", 1)[1].split("function buildOverviewPortfolioPayload", 1)[0]
    assert '<h2 id="chart-title">Продажи</h2>' in html
    assert '<div class="chart-title-line">' in html
    assert '<span id="chart-context">· по месяцам · сравнение лет</span>' in html
    assert ".chart-title-line" in css
    assert "white-space: nowrap;" in css.split(".chart-title-line", 1)[1].split(".panel-heading p", 1)[0]
    assert 'Динамика показателя' not in html.split('id="overview"', 1)[1].split('id="sales-drivers"', 1)[0]
    assert 'id="chart-metric"' not in html
    assert "● данные · пунктир — пропуск" in html
    assert ".overview-main .chart-footnote" in css
    assert "document.getElementById(\"chart-metric\")?.addEventListener" in script
    assert "if (!select) return;" in script
    assert "is-chart-selected" in css


def test_overview_decision_layout_uses_contribution_and_driver_guardrails() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    assert html.index('id="kpi-grid"') < html.index('class="surface chart-panel"')
    assert html.index('id="chart-box"') < html.index('id="table-title"')
    assert html.index('id="overview-table"') < html.index('id="diagnosis-grid"')
    assert html.index('id="diagnosis-grid"') < html.index('id="attention-list"')
    assert "contributionMetricForOverview()" in script
    assert 'return catalogEntry("revenue") ? "revenue" : null;' in script
    assert "state.overviewPreviewRowLimit" in script
    assert "driverBucketsByGrain" in script
    assert "Объём" in script
    assert "Цена" in script
    assert "Присутствие" in script
    assert "Скорость" in script
    assert "Экономика" in script
    assert "Структура" in script
    assert "причина" not in script.lower()
    assert "из-за" not in script.lower()
    assert "вызвано" not in script.lower()
    assert "привело к" not in script.lower()
    assert "существен" not in script.lower()
    assert "Без изменения относительно периода сравнения." in script
    assert "const usedConcepts = new Set();" in script
    assert "representativeConcept(group.concepts, usedConcepts)" in script
    assert "!excludedConcepts.has(concept)" in script
    assert ".slice(0, 3).map" in script
    assert "Есть показатели только по периодам" not in script
    overview_block = script.split("function renderOverview()", 1)[1].split("function renderSalesDrivers()", 1)[0]
    assert "Изменение оборота" not in overview_block


def test_browser_script_uses_runtime_options_and_resets_child_filters() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    assert "async function loadOptions()" in script
    assert "populatePeriodSelects" in script
    assert "populateEntityFilters" in script
    refresh_body = script.split("async function refreshRuntimeOptions", 1)[1].split("function populatePeriodSelects", 1)[0]
    assert refresh_body.index("if (resetEntities) resetAllEntityFilters();") < refresh_body.index("await loadOptions();")
    reset_body = script.split("function resetAllEntityFilters", 1)[1].split("function applyFilterDrilldown", 1)[0]
    assert 'state.currentGrain = "network";' in reset_body
    assert "state.drilldownPath = [];" in reset_body
    assert "renderBreadcrumb();" in reset_body
    assert "updatePreviewGrain();" in reset_body
    assert "resetChildFilters(id)" in script
    filter_body = script.split("function applyFilterDrilldown(filterId)", 1)[1].split("async function drillIntoEntity", 1)[0]
    assert "trimDrilldownFrom(filterId);" in filter_body
    assert "state.currentGrain = nearestDrilldownGrain();" in filter_body
    assert 'state.currentGrain = "store";' not in filter_body
    assert "nearestSelectedGrain" not in script
    assert "await refreshRuntimeOptions();" in script
    assert 'category: {' in script
    assert 'childFilters: ["manufacturer", "brand", "sku"]' in script
    assert 'manufacturer: {' in script
    assert 'childFilters: ["brand", "sku"]' in script
    assert "contextFilterText()" in script
    assert "grainLabels[state.currentGrain]" in script
    assert "manufacturer-search" in html_or_script("index.html")
    assert "populateEntityFilter(id)" in script
    assert "Все категории · ${state.grain}" not in script
    assert "const syntheticPeriods" not in script
    assert "const filters = {" not in script


def test_stores_screen_uses_store_ranking_without_fake_contribution() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    stores_panel = html.split('data-view-panel="stores"', 1)[1].split('data-view-panel="signals"', 1)[0]
    assert 'id="stores-title">Точки продаж</h2>' in stores_panel
    assert 'id="stores-ranking"' in stores_panel
    assert 'id="stores-metric"' in stores_panel
    assert 'id="stores-selected-kpi"' in stores_panel
    assert 'id="stores-table"' in stores_panel
    assert 'id="stores-detail"' in stores_panel
    assert "Раздел будет подключён для анализа продаж" not in stores_panel
    assert "Сейчас экран использует подтверждённые store-level показатели" in stores_panel

    stores_query_body = script.split("async function runStoresQuery()", 1)[1].split("function buildQueryPayload", 1)[0]
    assert 'postJson("/api/dashboard/query", buildStoresPayload())' in stores_query_body
    assert 'postJson("/api/dashboard/contribution"' not in stores_query_body
    assert 'buildQueryPayload("store", entityIdsForStores(), storeConcepts())' in script
    assert 'const storeRankingMetrics = ["revenue", "units", "retailer_margin_abs"]' in script
    assert 'const storeKpiConcepts = ["revenue", "units", "retailer_margin_abs", "sku_count"]' in script
    assert 'const storeTableConcepts = ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct", "sku_count"]' in script
    store_constants = script.split("const storeRankingMetrics", 1)[1].split("const portfolioPresentationFallback", 1)[0]
    assert "distribution" not in store_constants
    assert "velocity" not in store_constants
    assert "revenue_velocity" not in store_constants
    assert "margin_velocity" not in store_constants
    assert "Это не вклад в изменение" in script
    assert "вклад по ТТ не рассчитывается" in script
    assert "storesHasProductFilters()" not in script
    assert "renderStoresProductFilterUnsupported()" not in script
    assert "Разрез ТТ внутри выбранной категории, производителя, бренда или SKU пока не рассчитан." not in script
    assert "Store-level витрина не содержит подтверждённого разреза" not in script
    assert 'state.storesScopeStatus = "no_supported_metrics";' in script
    assert "renderStoresNoSupportedMetrics()" in script
    assert "buildStoresPayload()" not in script.split("async function runStoresQuery()", 1)[1].split("if (!storeConcepts().length)", 1)[0]
    assert "state.sortColumn = storeSortColumn();" in script
    assert "function storeSortColumn()" in script
    store_metric_options_body = script.split("function renderStoreMetricOptions()", 1)[1].split("function renderStoreRanking", 1)[0]
    assert "state.sortColumn = storeSortColumn();" in store_metric_options_body
    assert 'state.sortDirection = "desc";' in store_metric_options_body
    assert "renderStoresContextStripWithoutResponse()" in script
    assert "updateActiveFilterChips();" not in script.split("function renderStoresContextStripWithoutResponse()", 1)[1].split("function renderStoreMetricOptions", 1)[0]
    assert 'document.getElementById("context-coverage-note").textContent = coverageNote;' in script
    assert "Разрез ТТ по продуктным фильтрам пока не рассчитан" not in script


def test_store_filter_remains_filter_while_store_click_sets_drilldown() -> None:
    script = html_or_script("app.js")

    filter_body = script.split("function applyFilterDrilldown(filterId)", 1)[1].split("async function drillIntoEntity", 1)[0]
    assert 'state.currentGrain = "store";' not in filter_body
    assert "setExplicitDrilldown(" not in filter_body
    assert "trimDrilldownFrom(filterId);" in filter_body
    assert "async function selectStore(entityId)" in script
    select_store_body = script.split("async function selectStore(entityId)", 1)[1].split("function selectedRetailer", 1)[0]
    assert 'document.getElementById("store-filter")' in select_store_body
    assert 'state.currentGrain = "store";' in select_store_body
    assert 'setExplicitDrilldown("store", entityId);' in select_store_body
    assert "await refreshRuntimeOptions();" in select_store_body
    assert "await runStoresQuery();" in select_store_body
    assert "function entityIdsForStores()" in script
    assert "const selected = selectedStoreIds();" in script
    assert 'return firstEntityIds("store", state.tablePageSize);' in script


def test_stores_screen_provenance_and_period_guardrails() -> None:
    script = html_or_script("app.js")

    assert "function openStoreProvenance(result)" in script
    assert "function storeProvenanceButton(result)" in script
    assert "openMetricInspector({ concept: result.metric_concept, result, response: state.storesResponse, mode: \"value\" })" in script
    assert 'if (state.activeView === "stores")' in script
    assert "storeResultFor(concept, storeId)" in script
    assert "range_aggregation_period_only" in script
    assert "только по периодам" in script
    assert "Детализация выбранной ТТ по категориям, брендам и SKU будет подключена" in script


def test_browser_provenance_drawer_renders_backend_provenance_object() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    assert "result?.provenance" in script
    assert "provenanceSections(result.provenance" in script
    assert "current_analytical_scope" in script
    assert "source_evidence" in script
    assert "Provided by backend audit metadata" not in script
    assert "const lineage = result?.lineage" not in script
    assert "openContributionProvenance(row)" in script
    assert "contributionProvenanceSections(row.provenance || {}, row)" in script
    assert "entityDisplayLabel(state.previewGrain, row.child_entity_id)" in script


def test_metric_inspector_replaces_icon_only_provenance_affordance() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    assert 'aria-label="Проверка показателя"' in html
    assert 'id="metric-inspector-title">Проверка показателя</h2>' in html
    assert 'title="Откуда эта цифра?"' not in html
    assert "button.title" not in script

    assert "function openMetricInspector" in script
    assert "function metricValueButton" in script
    assert "function metricDeltaButton" in script
    assert "openMetricInspector({ concept, result, response, mode, sections })" in script
    assert "openMetricInspector({ concept, result, response, mode: \"comparison\", sections })" in script
    assert "contributionResultFromRow(row, cell.value)" in script
    assert 'heading.textContent = title || "Проверка показателя"' in script
    assert "label || \"Проверка показателя\"" not in script
    assert "Формула берётся" not in script
    assert "Определение берётся" not in script
    assert "Изменение объекта делится" not in script
    assert "closeMetricInspector();" in script
    assert "metric-value-button--kpi" in script
    assert "metric-delta-button" in script

    assert ".metric-value-button" in styles
    assert ".metric-value-button:focus-visible" in styles
    assert ".metric-inspector" in styles


def test_semantic_delta_classes_are_directional_not_good_bad() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    assert "OUTCOME_DIRECTIONAL" in script
    assert "NEUTRAL_DIRECTIONAL" in script
    assert "RANK_DIRECTIONAL" in script
    assert "lower" not in script.lower() or "меньшее значение означает движение вверх" in script
    assert "retailer_margin_pct" in script
    assert "function deltaFormatFor(format)" in script
    assert 'return format === "percent" ? "percentage_points" : format;' in script
    assert "function displayNormalizedDeltaValue(value, format)" in script
    assert "formatDeltaValue(comparison.delta, deltaFormatFor(entry.format))" in script
    assert "formatDeltaValue(row.delta, deltaFormatFor(metric?.format || \"decimal\"))" in script
    assert "delta-rank-improved" in script
    assert "delta-rank-declined" in script
    assert "delta-neutral-up" in script
    assert "delta-neutral-down" in script

    assert "--delta-outcome-up" in styles
    assert "--delta-outcome-down" in styles
    assert "--status-positive" in styles
    assert "--status-negative" in styles
    assert "--status-neutral" in styles
    assert "--reference-marker" in styles
    assert "--comparison-track" in styles
    assert "--brand-secondary-blue" in styles
    assert "--brand-berry" in styles
    assert "--delta-neutral-up" in styles
    assert "--delta-neutral-down" in styles
    assert "--delta-rank-improved" in styles
    assert "--delta-rank-declined" in styles
    assert ".delta-neutral-up,\n.delta-neutral-down,\n.delta-neutral {\n  color: var(--delta-neutral);" in styles


def test_zero_delta_display_is_normalized_before_text_and_direction() -> None:
    script = html_or_script("app.js")

    assert "const normalizedValue = displayNormalizedDeltaValue(value, format);" in script
    assert "if (Object.is(roundedScaledValue, -0) || roundedScaledValue === 0) return 0;" in script
    assert 'const prefix = normalizedValue > 0 ? "+" : "";' in script
    assert "formatValue(normalizedValue, format)" in script
    assert "function deltaSemanticClass(concept, value, format = null)" in script
    assert "const normalizedValue = displayNormalizedDeltaValue(value, format || deltaFormatFor(metricPresentation(concept)?.format || \"decimal\"));" in script
    assert "deltaSemanticClass(concept, value, format)" in script
    assert 'if (normalizedValue === null || normalizedValue === 0) return "kpi-direction-zero";' in script
    assert "Number(value) === 0" not in script.split("function kpiDirectionPresentationClass", 1)[1].split("function overviewPortfolioItem", 1)[0]
    assert "Number(value) === 0" not in script.split("function deltaSemanticClass", 1)[1].split("function deltaSemanticsText", 1)[0]


def test_zero_delta_formatter_and_direction_execute_against_app_js() -> None:
    node = shutil.which("node")
    bundled_node = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    if node is None and bundled_node.exists():
        node = str(bundled_node)
    if node is None:
        pytest.skip("node executable is required for dashboard JavaScript formatter contract")

    app_js = resources.files("retail_analytics.dashboard.static").joinpath("app.js")
    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const src = fs.readFileSync({str(app_js)!r}, "utf8");
        function extract(name) {{
          const start = src.indexOf(`function ${{name}}`);
          if (start < 0) throw new Error(`missing ${{name}}`);
          const open = src.indexOf("{{", start);
          let depth = 0;
          for (let index = open; index < src.length; index += 1) {{
            if (src[index] === "{{") depth += 1;
            if (src[index] === "}}") depth -= 1;
            if (depth === 0) return src.slice(start, index + 1);
          }}
          throw new Error(`unterminated ${{name}}`);
        }}
        eval([
          extract("formatValue"),
          extract("displayNormalizedDeltaValue"),
          extract("formatDeltaValue"),
          extract("kpiDirectionPresentationClass")
        ].join("\\n"));
        const cases = [
          ["exact zero", 0, "percent", "0%", "kpi-direction-zero"],
          ["negative zero", -0, "percent", "0%", "kpi-direction-zero"],
          ["positive zero", +0, "percent", "0%", "kpi-direction-zero"],
          ["small negative display zero", -0.00004, "percent", "0%", "kpi-direction-zero"],
          ["small positive display zero", 0.00004, "percent", "0%", "kpi-direction-zero"],
          ["real positive", 0.012, "percent", "+1,2%", "kpi-direction-up"],
          ["real negative", -0.012, "percent", "-1,2%", "kpi-direction-down"],
          ["zero percentage points", -0.00004, "percentage_points", "0 п.п.", "kpi-direction-zero"],
          ["integer rounded zero", -0.4, "integer", "0", "kpi-direction-zero"],
          ["currency rounded zero", 0.4, "currency", "0", "kpi-direction-zero"]
        ];
        for (const [label, value, format, expectedText, expectedClass] of cases) {{
          const actualText = formatDeltaValue(value, format);
          const actualClass = kpiDirectionPresentationClass(value, format);
          if (actualText !== expectedText || actualClass !== expectedClass) {{
            throw new Error(`${{label}}: got ${{actualText}}/${{actualClass}}, expected ${{expectedText}}/${{expectedClass}}`);
          }}
        }}
        """
    )

    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_excel_visual_grammar_tokens_and_portfolio_components_are_semantic() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    for token in (
        "--metric-current",
        "--metric-reference",
        "--delta-neutral",
        "--classification-a",
        "--classification-b",
        "--classification-c",
        "--ownership-own",
        "--ownership-competitor",
        "--attention",
        "--data-quality",
        "--limitation",
    ):
        assert token in styles

    assert "portfolio-decision-row" in script
    assert "portfolioContributionRows()" in script
    assert "portfolioCurrentReferenceCell(model)" in script
    assert "portfolioRankCell(model)" in script
    assert "portfolioShareCell(model)" in script
    assert "portfolioAbcCell(model)" in script
    assert ".portfolio-decision-row" in styles
    assert ".share-track" in styles
    assert ".cumulative-marker" in styles


def test_portfolio_visual_grammar_keeps_rank_share_and_abc_distinct() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    assert "rankMovementBadge(row)" in script
    assert "rankMovementText(stateValue, movement)" in script
    assert "↑" in script
    assert "↓" in script
    assert "Новый" in script
    assert "Вышел" in script
    assert "share_delta_pp" in script
    assert 'formatDeltaValue(row.share_delta_pp, "percentage_points")' in script
    assert "abcChip(model.abcRow?.abc_class)" in script
    assert "ABC недоступна" in script
    assert "quality" not in script.split("function abcChip", 1)[1].split("function portfolioAbcContextLabel", 1)[0].lower()
    assert ".abc-chip-c" in styles
    assert "var(--negative)" not in styles.split(".abc-chip-c", 1)[1].split(".abc-chip-na", 1)[0]
    assert ".rank-movement.is-improved" in styles
    assert ".rank-movement.is-declined" in styles


def test_current_reference_and_ownership_visual_hierarchy_is_not_color_only() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    assert 'row.className = `kpi-evidence-row kpi-evidence-row--${kind}`;' in script
    assert 'value.className = `kpi-evidence-value${valueClassName ? ` ${valueClassName}` : ""}`;' in script
    assert 'row.appendChild(value);' in script
    assert 'if (kind === "reference") {' in script
    assert 'appendText(row, "span", `· ${kpiCompactPeriodText(period)}`).className = "kpi-evidence-period";' in script
    assert 'left.appendChild(renderKpiEvidenceRow(' in script
    assert 'metric-current' in styles
    assert 'metric-reference' in styles
    assert "ownershipBadge(row)" in script
    assert "ownershipLabel(row)" in script
    assert "свой портфель" in script
    assert "конкуренты" in script
    assert ".ownership-badge" in styles
    assert ".portfolio-decision-row.is-own" in styles
    assert ".portfolio-decision-row.is-competitor" in styles
    assert "border-left-color: var(--ownership-own)" in styles
    assert "border-left-color: var(--ownership-competitor)" in styles


def test_cross_screen_visual_grammar_uses_shared_current_reference_delta_cells() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    assert "overview-brief" not in html
    assert "Что произошло, где изменился результат" not in html
    assert "function metricComparisonCell" in script
    assert 'metric-comparison-cell--${role}' in script
    assert 'role === "reference" ? "metric-reference"' in script
    assert 'role === "delta" ? "metric-delta"' in script
    assert "metric-table-cell--reference" in styles
    assert "metric-table-cell--delta" in styles
    assert "metric-comparison-cell--reference" in styles


def test_sales_drivers_and_stores_render_visual_hierarchy_without_frontend_calculation() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    sales_matrix = script.split("function renderSalesDriverMatrix()", 1)[1].split("function salesDriverMatrixHeaders()", 1)[0]
    assert 'cell.role === "reference"' in sales_matrix
    assert 'cell.role === "delta"' in sales_matrix
    assert "metricComparisonCell({" in sales_matrix
    assert "frontend" not in sales_matrix.lower()

    stores = script.split("function renderStoreRanking()", 1)[1].split("function storeRowsByMetric", 1)[0]
    assert "storeRankingValueNode(row.result" in stores
    assert "function storeRankingValueNode" in stores
    assert 'label: "Сейчас"' in stores
    assert 'label: "Δ"' in stores
    assert "store-value-stack" in styles


def test_signal_quality_limitation_and_error_roles_are_distinct() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    assert "--attention" in styles
    assert "--data-quality" in styles
    assert "--limitation" in styles
    assert "--application-error" in styles
    assert ".signal-row.commercial" in styles
    assert "border-left-color: var(--attention)" in styles
    assert ".signal-row.quality" in styles
    assert "border-left-color: var(--data-quality)" in styles
    assert "signal-limitation limitation-state" in script
    assert ".limitation-state" in styles
    assert ".error-state" in styles
    assert "var(--application-error)" in styles


def test_data_quality_visual_role_is_not_business_negative() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    data_quality = script.split("function renderDataQuality()", 1)[1].split("function renderDataRows()", 1)[0]
    assert "quality-list has-warning" in data_quality
    assert "quality-warning data-quality-state" in data_quality
    assert "quality-clear data-quality-state" in data_quality
    quality_styles = styles.split(".quality-warning", 1)[1].split(".data-audit-panel", 1)[0]
    assert "var(--data-quality)" in quality_styles
    assert "var(--negative)" not in quality_styles


def test_portfolio_surface_is_preserved_while_cross_screen_classes_are_shared() -> None:
    script = html_or_script("app.js")
    styles = html_or_script("styles.css")

    assert "portfolioContributionRows()" in script
    assert "portfolioDecisionRow(row)" in script
    assert "portfolioAnalysisGrain()" in script
    assert "selectedPortfolioExecutionFilters(grain)" in script
    assert "user_entity_filters: selectedFilterValuesForPortfolio()" in script
    assert "entity_filters: selectedPortfolioExecutionFilters(grain)" in script
    assert ".portfolio-decision-row.is-selected" in styles
    assert "metric-comparison-cell" in styles


def test_provenance_drawer_uses_russian_presentation_labels() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    expected = (
        "Что это за показатель",
        "Срез",
        "Сеть / источник",
        "Периоды",
        "Объект",
        "Определение показателя",
        "Числитель",
        "Знаменатель",
        "Стратегия диапазона",
        "Сравнение",
        "Бизнес-правило",
        "Запуск анализа",
        "Версия аналитической витрины",
        "Ревизия источника",
        "Доказательство по источнику",
        "Качество",
        "Учёт ассортимента",
        "Недостающие поля",
        "Технические детали",
        "Технический срез",
    )
    forbidden = (
        "Current analytical scope",
        "Retailer / source",
        "Period or comparison periods",
        "Grain / entity",
        "Metric definition",
        "Numerator",
        "Denominator",
        "Aggregation / range strategy",
        "Comparison type / quality",
        "Business rule",
        "Analysis run",
        "Mart build",
        "Source revision",
        "Source evidence",
        "Quality flags",
        "Scope including STM",
        "Missing provenance fields",
    )

    assert all(label in script for label in expected)
    assert not any(label in script for label in forbidden)
    assert "entityDisplayLabel(scope.grain_id, scope.entity_id)" in script
    assert "privateLabelScopeText(scope.private_label_scope)" in script



def test_metric_inspector_supports_private_alias_metadata() -> None:
    script = html_or_script("app.js")

    assert 'const metricFullNames = {' in script
    assert 'distribution: "Нумерическая дистрибуция"' in script
    assert 'weighted_distribution: "Взвешенная дистрибуция"' in script
    assert "function accessibleDisplayLabel(concept)" in script
    assert "metricPresentation(concept)?.display_alias" in script
    assert "function kpiAccessibleLabel(definition)" in script
    assert 'definition.fullLabel ? `${definition.fullLabel} (${definition.label})` : definition.label' in script
    assert "display_alias" in script
    assert "business_alias" in script
    assert "business_meaning" in script
    assert "unit_label" in script
    assert "definition.business_alias" in script
    assert "entry.display_alias || metricFullNames[concept] || null" in script
    assert "unitLabel(entry.format)" in script
    assert "inventory turnover" not in script.lower()


def test_public_tracked_files_do_not_hardcode_private_business_alias() -> None:
    alias = "V" + "P" + "O"
    tracked_public_paths = [
        Path("config/public/dashboard_metric_catalog.yaml"),
        Path("src/retail_analytics/dashboard/static/app.js"),
        Path("src/retail_analytics/mart/metric_catalog.py"),
        Path("src/retail_analytics/dashboard/runtime.py"),
    ]

    for path in tracked_public_paths:
        assert alias.casefold() not in path.read_text(encoding="utf-8").casefold()

def html_or_script(name: str) -> str:
    if name.endswith((".js", ".css")):
        return (
            resources.files("retail_analytics.dashboard.static")
            .joinpath(name)
            .read_text(encoding="utf-8")
        )
    return (
        resources.files("retail_analytics.dashboard.templates")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )
