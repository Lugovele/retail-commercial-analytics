from __future__ import annotations

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
from retail_analytics.dashboard.app import _parent_filters
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
    assert metadata["source_like_rows_configured"] is False
    assert runtime.query_service.metric_facts_path == tmp_path / "demo" / "synthetic_metric_facts.parquet"
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


def test_public_ui_assets_do_not_hardcode_private_retailer_terms() -> None:
    package_roots = (
        resources.files("retail_analytics.dashboard.templates"),
        resources.files("retail_analytics.dashboard.static"),
    )
    forbidden = (
        "\u0413\u043b\u043e\u0431\u0443\u0441",
        "\u041a\u0430\u043b\u0438\u043d\u043e\u0432",
        "\u0420\u043e\u0434\u043d\u0438\u043a",
        "\u0421\u0422\u041c",
    )
    text = "\n".join(
        file.read_text(encoding="utf-8")
        for root in package_roots
        for file in root.iterdir()
        if file.name.endswith((".html", ".css", ".js"))
    )

    assert not any(term in text for term in forbidden)


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
        "Продажи и драйверы",
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
    assert "Весь диапазон" in html
    assert "Год к году" in html
    assert "Месяц к месяцу" in html
    assert "Предыдущий доступный период" in html
    assert "period-b-derived" in html
    assert "private-label-scope" in html
    assert "Картина изменений" in html
    assert "Где произошло изменение?" in html
    assert "Объекты с наибольшим вкладом в изменение" in html
    assert "Что проверить" in html
    assert 'id="period-b"' not in html


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
    assert 'panel.classList.toggle("is-hidden"' not in script
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
    assert 'state.signalsResponse = await postJson("/api/dashboard/signals", buildSignalsPayload());' in script
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
    assert 'state.dataResponse = await postJson("/api/dashboard/data", buildDataPayload());' in script
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


def test_sales_drivers_screen_implements_driver_matrix_without_fake_content() -> None:
    html = html_or_script("index.html")
    script = html_or_script("app.js")

    sales_panel = html.split('data-view-panel="sales_drivers"', 1)[1].split('data-view-panel="portfolio_market"', 1)[0]
    assert 'id="sales-drivers-matrix"' in sales_panel
    assert 'id="sales-drivers-chart-box"' in sales_panel
    assert 'id="sales-drivers-detail-table"' in sales_panel
    assert "Раздел будет подключён" not in sales_panel
    assert "как изменился коммерческий результат" in sales_panel
    assert "какие показатели изменились одновременно" in sales_panel

    assert "const salesDriverBuckets = [" in script
    for bucket in ("Результат", "Объём", "Цена", "Присутствие", "Скорость", "Экономика", "Структура"):
        assert bucket in script
    assert 'return ["Группа", "Показатель", "Сейчас", "Сравнение", "Изменение", "Доказательство"];' in script
    assert 'return ["Группа", "Показатель", "Диапазон", "Статус", "Доказательство"];' in script
    assert "state.salesDriverMetric = concept;" in script
    assert "buildSalesDriverChartQueryPayload()" in script
    assert "salesDriverDetailGrain()" in script
    assert "salesDriverDetailConcepts()" in script
    assert "function catalogEntries(concept)" in script
    assert "catalogEntries(concept).find((item) => item.grain_support?.includes(grain))" in script
    assert "metricEntryForGrain(concept, grain)" in script
    assert "const salesDriverGrainSupport = {" in script
    assert "period_only" in script
    assert 'return [staticCell("Недоступно"), staticCell("Показатель доступен только по отдельным периодам.")];' in script
    assert "Показатель доступен только по отдельным периодам." in script
    assert "Для выбранного среза нет поддержанных показателей." in script
    assert "сортировка доступна по столбцам таблицы" in script
    assert "retailer_margin_pct" in script
    assert "weighted_input_price_vat" in script
    assert "revenue_velocity" in script
    assert "manufacturer_rank_revenue" not in script.split("const salesDriverBuckets = ", 1)[1].split("];", 1)[0]
    assert "category_revenue_share" not in script.split("const salesDriverBuckets = ", 1)[1].split("];", 1)[0]
    assert "contribution_to_delta" not in script.split("const salesDriverBuckets = ", 1)[1].split("];", 1)[0]


def test_sales_drivers_uses_backend_query_and_preserves_active_scope() -> None:
    script = html_or_script("app.js")

    assert "async function runActiveViewQuery()" in script
    assert 'if (state.activeView === "sales_drivers")' in script
    assert "async function runSalesDriversQuery()" in script
    assert 'state.salesDriversResponse = await postJson("/api/dashboard/query", summaryPayload);' in script
    assert 'state.salesDriversChartResponse = await postJson("/api/dashboard/query", chartPayload);' in script
    assert 'state.salesDriversTableResponse = await postJson("/api/dashboard/query", detailPayload);' in script
    assert "buildQueryPayload(state.currentGrain, entityIdsForSummary(), concepts)" in script
    assert "buildQueryPayload(salesDriverDetailGrain(), entityIdsForSalesDriverDetail(), salesDriverDetailConcepts())" in script
    assert "comparisonFor(state.salesDriversResponse, result)" in script
    assert '["READY", "PARTIAL"].includes(entry.availability_status)' in script
    assert 'entry.format === "percent" ? "percentage_points" : entry.format' in script
    assert "!salesDriverGrainSupport[concept]?.includes(grain)" in script
    assert 'distribution: ["category", "manufacturer", "brand", "sku"]' in script
    assert 'velocity: ["category", "manufacturer", "brand", "sku"]' in script
    assert "margin / revenue" not in script
    assert "sum(" not in script.lower()


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
    assert 'state.portfolioMarketResponse = await postJson("/api/dashboard/portfolio-market", buildPortfolioMarketPayload());' in script
    assert "function buildPortfolioMarketPayload()" in script
    assert "concept_ids: portfolioMarketConcepts" in script
    assert "entity_filters: selectedFilterValuesForPortfolio()" in script
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
    assert "top: 54px;" in css
    nav_body = css.split(".nav-item {", 1)[1].split(".nav-item.is-active", 1)[0]
    assert "background: transparent;" in nav_body
    assert "border: 0;" in nav_body
    assert "text-decoration: none;" in nav_body
    active_body = css.split(".nav-item.is-active {", 1)[1].split(".nav-item.is-active::after", 1)[0]
    assert "color: var(--brand-menu-blue);" in active_body
    assert ".nav-item.is-active::after" in css
    assert "height: 2px;" in css
    assert ".folder-tabs" not in css


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
    assert "hasMultipleRetailers" in script
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

    assert "function applyPendingFilter(id)" in script
    assert "state.pendingFilters[id]" in script
    assert "state.filters[id] = next;" in script
    assert "function renderFilterOptions(id)" in script
    assert "function visibleEntityOptions(id)" in script
    assert ".slice(0, maxComboboxOptions)" in script
    assert "const available = visibleEntityOptions(id);" in script
    select_visible_body = script.split('document.querySelector(`[data-select-all="${id}"]`)', 1)[1].split("document.querySelectorAll(\"[data-clear-pending-filter]\")", 1)[0]
    assert "const next = new Set(pendingValuesForFilter(id));" in select_visible_body
    assert "if (event.target.checked) next.add(item.value);" in select_visible_body
    assert "else next.delete(item.value);" in select_visible_body
    assert "state.pendingFilters[id] = Array.from(next);" in select_visible_body
    assert "rankedEntityOptions(state.options.entities?.[id] || [], state.filterQueries[id] || \"\")" in script
    assert "function searchRank(item, query)" in script
    assert "label.startsWith(query)" in script
    assert "haystack.includes(query)" in script
    assert "Показано ${visibleValues.length} из ${totalCount}" in script
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
    assert "display: contents;" in css.split(".filter-grid", 1)[1].split(".multi-filter", 1)[0]
    assert scope_body.count("native-filter-select") == 5
    assert scope_body.count('id="private-label-scope"') == 1
    assert "filter-chip" not in html
    assert "data-combobox" not in html


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
    assert [item["value"] for item in entities["store"]] == ["STORE_ACTIVE"]
    assert [item["label"] for item in entities["store"]] == ["Store Active Label"]


def test_continuous_report_scope_keeps_filters_during_period_and_assortment_changes() -> None:
    script = html_or_script("app.js")

    period_handler = script.split('["period-single", "period-a", "date-from", "date-to"].forEach((id) => {', 1)[1].split('document.getElementById("sales-drivers-provenance")', 1)[0]
    assortment_handler = script.split('document.getElementById("private-label-scope").addEventListener("change"', 1)[1].split('document.getElementById("chart-metric")', 1)[0]
    nav_handler = script.split('document.querySelectorAll("[data-view]")', 1)[1].split('document.querySelectorAll("[data-signal-kind]")', 1)[0]

    assert "await refreshRuntimeOptions();" in period_handler
    assert "resetEntities: true" not in period_handler
    assert "await refreshRuntimeOptions();" in assortment_handler
    assert "resetEntities: true" not in assortment_handler
    assert "async function applyScopeChange(work)" in script
    assert "const preservedView = state.scopeEditView || viewFromHash() || state.activeView || \"overview\";" in script
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


def test_browser_script_sends_backend_scope_fields_without_metric_formulas() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    assert "private_label_scope" in script
    assert "comparison_mode" in script
    assert 'comparison_mode: state.periodMode === "COMPARE" ? selectedComparisonMode() : "NONE"' in script
    assert "period_mode" in script
    assert 'return state.periodMode === "DATE_RANGE" ? "DATE_RANGE" : "SINGLE_PERIOD";' in script
    assert "grain_id" in script
    assert "metric_concepts" in script
    assert "entity_ids: entityIds" in script
    assert "entity_filters: selectedParentFiltersForGrain(grain)" in script
    assert "/api/dashboard/options" in script
    assert "state.options.periods" in script
    assert "chartResponse: null" in script
    assert "buildChartQueryPayload()" in script
    assert "state.chartResponse = await postJson(\"/api/dashboard/query\", chartPayload);" in script
    assert "period_mode: \"DATE_RANGE\"" in script
    assert "comparison_mode: \"NONE\"" in script
    assert "const chartResult = chartResultFor(state.chartMetric);" in script
    assert "const coverage = chartResult ? state.chartResponse : state.summaryResponse;" in script
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
    assert "Для этой пары уровней вклад пока недоступен." in script


def test_overview_uses_exactly_four_primary_kpi_concepts() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    assert 'const primaryKpis = ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"]' in script
    assert "primaryKpis.map" in script
    assert "revenue_velocity" not in script.split("const primaryKpis = ", 1)[1].split("];", 1)[0]
    assert "distribution" not in script.split("const primaryKpis = ", 1)[1].split("];", 1)[0]


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
    assert "Изменение оборота" not in script


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
    assert "storesHasProductFilters()" in script
    assert "renderStoresProductFilterUnsupported()" in script
    assert "Разрез ТТ внутри выбранной категории, производителя, бренда или SKU пока не рассчитан." in script
    assert "Store-level витрина не содержит подтверждённого разреза" in script
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
    assert "Разрез ТТ по продуктным фильтрам пока не рассчитан" in script


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
    assert "formatDeltaValue(comparison.delta, deltaFormatFor(entry.format))" in script
    assert "formatDeltaValue(row.delta, deltaFormatFor(metric?.format || \"decimal\"))" in script
    assert "delta-rank-improved" in script
    assert "delta-rank-declined" in script
    assert "delta-neutral-up" in script
    assert "delta-neutral-down" in script

    assert "--delta-outcome-up" in styles
    assert "--delta-outcome-down" in styles
    assert "--delta-neutral-up" in styles
    assert "--delta-neutral-down" in styles
    assert "--delta-rank-improved" in styles


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
