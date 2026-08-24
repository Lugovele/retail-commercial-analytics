from __future__ import annotations

from datetime import date
from importlib import resources
from pathlib import Path

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
    assert runtime.query_service.metric_facts_path == tmp_path / "demo" / "synthetic_metric_facts.parquet"
    assert len(runtime.catalog) == 1


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
    assert "Обзор" in html
    assert "Рынок и ассортимент" in html
    assert "Сигналы" in html
    assert "Данные и качество" in html
    assert "Рекомендации" not in html
    assert "Показатели" not in html
    assert "Бизнес-оценки" not in html
    assert "Откуда эта цифра?" in html
    assert "Один период" in html
    assert "Сравнение" in html
    assert "Весь диапазон" in html
    assert "Год к году" in html
    assert "Месяц к месяцу" in html
    assert "Предыдущий доступный период" in html
    assert "period-b-derived" in html
    assert "private-label-scope" in html
    assert "Картина изменений" in html
    assert "Где смотреть" in html
    assert "Что проверить" in html
    assert 'id="period-b"' not in html


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
        "Данные обновлены",
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
    css = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("styles.css")
        .read_text(encoding="utf-8")
    )

    assert ".workflow-nav" in css
    assert "flex-wrap: wrap" in css
    assert ".folder-tabs" not in css


def test_browser_script_sends_backend_scope_fields_without_metric_formulas() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    assert "private_label_scope" in script
    assert "comparison_mode" in script
    assert "period_mode" in script
    assert "grain_id" in script
    assert "metric_concepts" in script
    assert "entity_ids: entityIds" in script
    assert "entity_filters: selectedParentFiltersForGrain(grain)" in script
    assert "/api/dashboard/options" in script
    assert "state.options.periods" in script
    assert "state.tablePageSize: 50" not in script
    assert "tablePageSize: 40" in script
    assert "entityIdsForSummary" in script
    assert "entityIdsForPreview" in script
    assert "canActivateSummaryGrain(targetGrain)" in script
    assert 'state.currentGrain = "network";' in script
    assert 'if (state.currentGrain === "network") return firstEntityIds("network", 1);' in script
    assert 'return ["network"]' not in script
    assert "selectedParentFiltersForGrain" in script
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
    assert "ONLY: `${scopeName}: только`" in script
    assert "ONLY: `только ${scopeName}`" in script
    assert 'entry.format === "percent" ? "percentage_points" : entry.format' in script
    assert "п.п." in script
    assert "retailer_margin_pct" in script
    assert "margin / revenue" not in script
    assert "sum(" not in script.lower()


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
    assert "updateBreadcrumb();" in reset_body
    assert "updatePreviewGrain();" in reset_body
    assert "resetChildFilters(id)" in script
    assert "await refreshRuntimeOptions();" in script
    assert 'category: { label: "Все категории", childFilters: ["manufacturer", "brand", "sku"] }' in script
    assert 'manufacturer: { label: "Все производители", childFilters: ["brand", "sku"] }' in script
    assert "contextFilterText()" in script
    assert "grainLabels[state.currentGrain]" in script
    assert "manufacturer-search" in html_or_script("index.html")
    assert "populateEntityFilter(id)" in script
    assert "Все категории · ${state.grain}" not in script
    assert "const syntheticPeriods" not in script
    assert "const filters = {" not in script


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
    if name.endswith(".js"):
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
