from __future__ import annotations

from datetime import date
from importlib import resources

import pytest

from retail_analytics.dashboard import (
    DashboardUiQueryPayload,
    build_backend_query_request,
    build_synthetic_dashboard_runtime,
    serialize_dashboard_query_response,
)
from retail_analytics.mart import ComparisonMode, PeriodMode, PrivateLabelScope


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
    assert "Данные" in html
    assert "Показатели" in html
    assert "Бизнес-оценки" in html
    assert "Сигналы" in html
    assert "Рекомендации" in html
    assert "В разработке" in html
    assert "Откуда эта цифра?" in html
    assert "Год к году" in html
    assert "Месяц к месяцу" in html
    assert "Предыдущий доступный период" in html
    assert "period-b-derived" in html
    assert "private-label-scope" in html
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
        "Объект",
        "Период источника",
        "Оборот",
        "Качество данных",
        "Доля в категории",
        "Место производителя",
        "Покрытие периода",
        "Ограничения диапазона",
        "Окна событий",
        "Контекст витрины готов",
        "Определяется витриной",
        "Группа колонок пока не поддержана каталогом витрины",
        "Ошибка витрины",
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
        "n/a",
    )

    assert all(label in surface for label in expected)
    assert not any(label in surface for label in forbidden)


def test_folder_tabs_use_wrapping_without_visible_horizontal_scrollbar() -> None:
    css = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("styles.css")
        .read_text(encoding="utf-8")
    )

    assert ".folder-tabs" in css
    assert "flex-wrap: wrap" in css
    assert "overflow-x: hidden" in css


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
    assert "entity_filters: { entity_id" in script
    assert "selectedEntityForGrain" in script
    assert "private-label-scope" in script
    assert 'YOY: "Год к году"' in script
    assert 'MOM: "Месяц к месяцу"' in script
    assert 'PREVIOUS_AVAILABLE: "Предыдущий доступный период"' in script
    assert "comparisonLabel(state.comparisonMode)" in script
    assert "innerHTML" not in script
    assert "ONLY: `${scopeName}: только`" in script
    assert "ONLY: `только ${scopeName}`" in script
    assert "formatDeltaValue(row[3], row[5])" in script
    assert 'formatValue(value, "percentage_points")' in script
    assert "п.п." in script
    assert "retailer_margin_pct" in script
    assert "margin / revenue" not in script
    assert "sum(" not in script.lower()


def test_browser_provenance_drawer_renders_backend_provenance_object() -> None:
    script = (
        resources.files("retail_analytics.dashboard.static")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )

    assert "const provenance = result?.provenance" in script
    assert "provenanceFields(provenance" in script
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
        "Текущий срез",
        "Сеть / источник",
        "Период или периоды сравнения",
        "Гранулярность / объект",
        "Определение показателя",
        "Числитель",
        "Знаменатель",
        "Агрегация / стратегия диапазона",
        "Тип сравнения / качество",
        "Бизнес-правило",
        "Запуск анализа",
        "Версия аналитической витрины",
        "Ревизия источника",
        "Доказательство по источнику",
        "Качество данных",
        "Срез с учётом выбранного ассортимента",
        "Недостающие поля происхождения",
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
