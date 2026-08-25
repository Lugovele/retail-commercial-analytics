import tomllib
from pathlib import Path

import yaml  # type: ignore[import-untyped]

POLICY_PATH = Path("config/public/dashboard_visualization_policy.yaml")
CATALOG_PATH = Path("config/public/dashboard_metric_catalog.yaml")
CAPABILITY_PATH = Path("config/public/dashboard_capability_matrix.yaml")
SCREEN_SPEC_PATH = Path("docs/public/dashboard/dashboard-screen-specification.md")
HUMAN_POLICY_PATH = Path("docs/public/dashboard/dashboard-visualization-and-screen-design-policy.md")
EVIDENCE_SCHEMA_PATH = Path("config/public/review_lifecycle_evidence_schema.yaml")

AGENT_PATHS = [
    Path(".codex/agents/retail-change-lifecycle-orchestrator.toml"),
    Path(".codex/agents/retail-change-reviewer.toml"),
    Path(".codex/agents/retail-architecture-reviewer.toml"),
    Path(".codex/agents/retail-business-rules-reviewer.toml"),
]

EXPECTED_SCREENS = [
    "overview",
    "sales_drivers",
    "portfolio_market",
    "stores",
    "signals",
    "data",
]

PROHIBITED_PUBLIC_MARKERS = [
    "private source workbook",
    f"config/{'private'}",
    f"data/{'private'}",
    f"docs/{'private'}",
]


def test_visualization_policy_defines_approved_screens_and_vocabularies() -> None:
    policy = _load_policy()
    screens = policy["screens"]
    screen_ids = [screen["id"] for screen in screens]

    assert screen_ids == EXPECTED_SCREENS
    assert len(screen_ids) == len(set(screen_ids))
    assert policy["policy_version"] == "dashboard_visualization_policy.v1.0.0"

    visualizations = set(policy["enums"]["visualization_types"])
    assert {
        "KPI",
        "LINE",
        "RANKED_TABLE",
        "DRIVER_MATRIX",
        "SIGNAL_LIST",
        "PROVENANCE_DRAWER",
    }.issubset(visualizations)
    assert {"PIE", "DONUT", "RADAR", "GAUGE", "MULTI_AXIS_CHART"}.issubset(
        set(policy["enums"]["discouraged_visualizations"])
    )
    assert "PIE" not in visualizations
    assert "DONUT" not in visualizations


def test_visualization_policy_references_current_catalog_and_capabilities() -> None:
    policy = _load_policy()
    catalog_concepts = {
        item["metric_concept"]
        for item in yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))["metrics"]
    }
    capability_concepts = {
        item["concept_id"]
        for item in yaml.safe_load(CAPABILITY_PATH.read_text(encoding="utf-8"))["capabilities"]
    }
    policy_concepts = {item["concept_id"] for item in policy["metric_rules"]}

    assert capability_concepts == policy_concepts
    assert catalog_concepts.issubset(policy_concepts)

    allowed_visualizations = set(policy["enums"]["visualization_types"])
    allowed_forbidden_values = allowed_visualizations | set(policy["enums"]["discouraged_visualizations"])
    screen_ids = {screen["id"] for screen in policy["screens"]}
    grains = set(policy["enums"]["grains"])
    periods = set(policy["enums"]["period_modes"])
    readiness = set(policy["enums"]["readiness"])

    for rule in policy["metric_rules"]:
        assert set(rule["allowed_screens"]).issubset(screen_ids)
        assert rule["preferred_visualization"] in allowed_visualizations
        assert set(rule["alternative_visualizations"]).issubset(allowed_visualizations)
        assert set(rule["forbidden_visualizations"]).issubset(allowed_forbidden_values)
        assert set(rule["grain_support"]).issubset(grains)
        assert set(rule["period_modes"]).issubset(periods)
        assert rule["readiness_requirement"] in readiness


def test_contribution_policy_is_additive_only_and_table_first() -> None:
    policy = _load_policy()
    contribution = policy["business_concept_rules"]["contribution_to_delta"]
    rule = _metric_rule(policy, "contribution_to_delta")

    assert contribution["supported_metric_concepts"] == [
        "revenue_vat",
        "revenue",
        "units",
        "retailer_margin_abs",
    ]
    assert contribution["preferred_visualization"] == "RANKED_TABLE"
    assert "PIE" in contribution["forbidden_visualizations"]
    assert "DONUT" in contribution["forbidden_visualizations"]
    assert "WATERFALL" in contribution["forbidden_visualizations"]
    assert "never_clamp_to_0_100" in contribution["guardrails"]
    assert contribution["period_modes"]["COMPARE"] == "READY_QUERY"
    assert contribution["period_modes"]["SINGLE_PERIOD"] == "NOT_APPLICABLE"

    assert rule["allowed_screens"] == ["overview"]
    assert rule["period_modes"] == ["COMPARE"]
    assert rule["readiness_requirement"] == "READY_QUERY"


def test_store_policy_blocks_distribution_and_velocity() -> None:
    policy = _load_policy()
    stores = next(screen for screen in policy["screens"] if screen["id"] == "stores")

    assert {"distribution", "velocity", "revenue_velocity", "margin_velocity"}.issubset(
        set(stores["forbidden_concepts"])
    )
    store_table = policy["table_policy"]["grains"]["store"]
    assert {"distribution", "velocity", "revenue_velocity", "margin_velocity"}.issubset(
        set(store_table["forbidden_columns"])
    )
    assert "contribution_to_delta" not in store_table["default_columns"]
    assert store_table["default_sort"] == "current_value_desc"

    for concept in ("distribution", "velocity", "revenue_velocity", "margin_velocity"):
        rule = _metric_rule(policy, concept)
        assert "store" not in rule["grain_support"]


def test_sku_to_store_contribution_requires_backend_route() -> None:
    policy = _load_policy()
    sku_table = policy["table_policy"]["grains"]["sku"]
    store_table = policy["table_policy"]["grains"]["store"]
    contribution_rule = _metric_rule(policy, "contribution_to_delta")

    assert sku_table["drilldown_target"] == "store"
    assert sku_table["store_contribution_support"] == "BACKEND_ROUTE_REQUIRED"
    assert "store" not in contribution_rule["grain_support"]
    assert "contribution_to_delta" not in store_table["default_columns"]


def test_overview_density_and_forbidden_semantics_are_gated() -> None:
    policy = _load_policy()
    overview = next(screen for screen in policy["screens"] if screen["id"] == "overview")

    assert overview["max_kpi"] == 4
    assert overview["max_primary_charts"] == 1
    assert overview["max_preview_rows"] == 8
    assert overview["max_signal_preview"] == 3
    assert {"recommendations", "direct_peers", "abc", "delisting"}.issubset(
        set(overview["forbidden_concepts"])
    )

    recommendation_rule = _metric_rule(policy, "recommendations")
    assert recommendation_rule["allowed_screens"] == []
    assert recommendation_rule["readiness_requirement"] == "FUTURE"
    assert "KPI" in recommendation_rule["forbidden_visualizations"]


def test_screen_spec_matches_approved_overview_flow() -> None:
    screen_spec = SCREEN_SPEC_PATH.read_text(encoding="utf-8")

    kpi_index = screen_spec.index("KPI:")
    chart_index = screen_spec.index("Main trend:")
    contribution_index = screen_spec.index("Вклад в изменение")
    driver_index = screen_spec.index("Картина изменений")
    attention_index = screen_spec.index("Что проверить", driver_index)

    assert kpi_index < chart_index < contribution_index < driver_index < attention_index
    assert "Где произошло изменение? / Где смотреть" not in screen_spec


def test_public_policy_docs_and_config_are_public_safe() -> None:
    public_paths = [POLICY_PATH, SCREEN_SPEC_PATH, HUMAN_POLICY_PATH]
    for path in public_paths:
        text = path.read_text(encoding="utf-8")
        for pattern in PROHIBITED_PUBLIC_MARKERS:
            assert pattern not in text


def test_screen_spec_and_human_policy_cover_all_screens() -> None:
    spec = SCREEN_SPEC_PATH.read_text(encoding="utf-8")
    human_policy = HUMAN_POLICY_PATH.read_text(encoding="utf-8")

    for label in ["Обзор", "Продажи и драйверы", "Портфель и рынок", "Точки продаж", "Сигналы", "Данные"]:
        assert label in spec
        assert label in human_policy

    assert "Metric Catalog is the taxonomy of data" in human_policy
    assert "Dashboard navigation is the taxonomy of business questions" in human_policy
    assert "distribution, velocity" in spec


def test_lifecycle_agents_enforce_dashboard_visualization_policy() -> None:
    for path in AGENT_PATHS:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        instructions = payload["instructions"]
        assert "dashboard_visualization_policy.yaml" in instructions
        assert "dashboard-screen-specification.md" in instructions

    orchestrator = tomllib.loads(AGENT_PATHS[0].read_text(encoding="utf-8"))["instructions"]
    assert "SENIOR_FMCG_ANALYST" in orchestrator
    assert "SENIOR_BI_VISUALIZATION_SPECIALIST" in orchestrator
    assert "SENIOR_B2B_UI_UX_DESIGNER" in orchestrator
    assert "PRIVATE rendered acceptance status" in orchestrator


def test_review_evidence_schema_allows_dashboard_ui_review_metadata() -> None:
    schema = yaml.safe_load(EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8"))[
        "review_lifecycle_evidence_schema"
    ]
    fields = set(schema["optional_dashboard_ui_fields"])

    assert {
        "screen",
        "business_question",
        "visualization_types_reviewed",
        "metrics_reviewed",
        "fmcg_review_status",
        "bi_visualization_status",
        "b2b_ui_ux_status",
        "private_rendered_acceptance_status",
    }.issubset(fields)


def _load_policy() -> dict:
    return dict(yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")))


def _metric_rule(policy: dict, concept_id: str) -> dict:
    matches = [rule for rule in policy["metric_rules"] if rule["concept_id"] == concept_id]
    assert len(matches) == 1
    return dict(matches[0])
