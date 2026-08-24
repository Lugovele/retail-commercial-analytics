from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from retail_analytics.mart import load_public_metric_catalog

MATRIX_PATH = Path("config/public/dashboard_capability_matrix.yaml")
PRESENTATION_CATALOG_PATH = Path("docs/public/dashboard/dashboard-metric-presentation-catalog.md")
APP_JS_PATH = Path("src/retail_analytics/dashboard/static/app.js")

CORE_PUBLIC_CONCEPTS = {
    "revenue_vat",
    "revenue",
    "units",
    "retailer_margin_abs",
    "retailer_margin_pct",
    "weighted_shelf_price_vat",
    "weighted_input_price_vat",
    "selling_store_count",
    "active_store_count",
    "distribution",
    "velocity",
    "revenue_velocity",
    "margin_velocity",
    "sku_count",
    "brand_count",
    "category_count",
    "category_revenue_share",
    "category_units_share",
    "category_margin_share",
}
FORMAT_VALUES = {"currency", "integer", "decimal", "percent", "percentage_points", "ratio", "text"}
GROUP_LABELS = {
    "sales": "Продажи",
    "economics": "Экономика",
    "distribution": "Присутствие",
    "price": "Цена",
    "share": "Доли",
    "assortment": "Структура",
    "competition": "Конкуренты",
    "quality": "Сигналы",
}


def test_capability_matrix_loads_required_contract_fields() -> None:
    rows = _matrix_rows()
    required = {
        "concept_id",
        "ui_label_ru",
        "ui_description_ru",
        "tab",
        "group",
        "presentation_level",
        "grain_support",
        "single_period_support",
        "comparison_support",
        "date_range_support",
        "range_aggregation_strategy",
        "private_label_scope_support",
        "format",
        "unit",
        "backend_fact_source",
        "availability_status",
        "limitations",
        "provenance_supported",
        "signal_eligible",
        "recommendation_eligible_future",
    }

    assert rows
    assert all(required <= set(row) for row in rows)
    assert len({row["concept_id"] for row in rows}) == len(rows)


def test_core_matrix_labels_match_public_metric_catalog() -> None:
    matrix = {row["concept_id"]: row for row in _matrix_rows()}
    public_catalog = load_public_metric_catalog("config/public/dashboard_metric_catalog.yaml")

    for entry in public_catalog:
        row = matrix[entry.metric_concept]
        assert row["ui_label_ru"] == entry.default_display_label
        assert row["ui_description_ru"] == entry.description
        assert row["format"] == entry.format.value
        assert row["group"] == GROUP_LABELS[entry.dashboard_group.value]
        assert row["comparison_support"] == list(entry.default_comparison_support)
        assert row["range_aggregation_strategy"] == entry.default_range_aggregation_strategy.value
        assert set(entry.generic_limitations) <= set(row["limitations"])
        assert row["private_label_scope_support"] == [
            scope.value for scope in entry.private_label_scope_support
        ]


def test_comparison_support_uses_machine_modes_with_display_labels_at_header() -> None:
    payload = _matrix_payload()
    comparison_modes = set(payload["comparison_labels"])

    assert comparison_modes == {"YOY", "MOM", "PREVIOUS_AVAILABLE", "NONE"}
    for row in payload["capabilities"]:
        assert set(row["comparison_support"]) <= comparison_modes


def test_presentation_catalog_concepts_are_in_capability_matrix() -> None:
    matrix_concepts = {row["concept_id"] for row in _matrix_rows()}
    text = PRESENTATION_CATALOG_PATH.read_text(encoding="utf-8")
    documented_concepts = {
        match.group(1)
        for match in re.finditer(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE)
        if re.fullmatch(r"[a-z][a-z0-9_]+", match.group(1)) and match.group(1) not in FORMAT_VALUES
    }

    assert documented_concepts <= matrix_concepts


def test_ui_referenced_metric_concepts_are_supported_by_matrix() -> None:
    matrix = {row["concept_id"]: row for row in _matrix_rows()}
    script = APP_JS_PATH.read_text(encoding="utf-8")
    array_concepts = set(re.findall(r'"([a-z_]+)"', script))
    ui_metric_concepts = array_concepts & CORE_PUBLIC_CONCEPTS

    assert ui_metric_concepts
    assert ui_metric_concepts <= set(matrix)
    assert all(matrix[concept]["availability_status"] != "NOT_AVAILABLE" for concept in ui_metric_concepts)


def test_top_kpis_are_ready_and_range_claims_are_safe() -> None:
    for row in _matrix_rows():
        if row["presentation_level"] == "TOP_KPI":
            assert row["availability_status"] == "READY"
        if row["range_aggregation_strategy"] == "period_only":
            assert row["date_range_support"] != "READY"
        if row["date_range_support"] == "READY":
            assert row["range_aggregation_strategy"] != "period_only"


def test_store_grain_does_not_expose_distribution_or_velocity() -> None:
    matrix = {row["concept_id"]: row for row in _matrix_rows()}

    for concept in ("distribution", "velocity", "revenue_velocity", "margin_velocity"):
        assert "store" not in matrix[concept]["grain_support"]


def test_private_label_scope_support_is_never_claimed_for_unavailable_features() -> None:
    for row in _matrix_rows():
        if row["availability_status"] in {"NOT_AVAILABLE", "NOT_APPLICABLE"}:
            assert row["private_label_scope_support"] == []
        if row["private_label_scope_support"]:
            assert set(row["private_label_scope_support"]) <= {"INCLUDE", "EXCLUDE", "ONLY"}


def test_recommendations_remain_not_available() -> None:
    matrix = {row["concept_id"]: row for row in _matrix_rows()}

    assert matrix["recommendations"]["availability_status"] == "NOT_AVAILABLE"
    assert matrix["recommendations"]["presentation_level"] == "AUDIT_ONLY"
    assert "no_fake_ai_content" in matrix["recommendations"]["limitations"]


def _matrix_rows() -> list[dict[str, Any]]:
    return list(_matrix_payload()["capabilities"])


def _matrix_payload() -> dict[str, Any]:
    return dict(yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8")))
