from datetime import date

import polars as pl

from retail_analytics.core.events.contracts import EventRule
from retail_analytics.core.events.engine import detect_events
from retail_analytics.core.events.facts import build_event_facts
from retail_analytics.core.events.registry import load_event_rule_config
from retail_analytics.core.rule_engine.conditions import RuleCondition
from retail_analytics.core.rule_engine.evaluator import evaluate_conditions
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.pipeline.slice4 import run_slice4_event_engine
from retail_analytics.quality.report import QualityIssue, QualityReport


def _context(retailer_id: str = "retailer_a", source_id: str = "source_a") -> AnalysisContext:
    return AnalysisContext("run_a", retailer_id, source_id, "v1", "rules_v1")


def test_event_rules_load_from_config():
    registry = load_event_rule_config("config/public/demo/event_rules.yaml")

    assert registry.quality_report.is_valid
    assert any(rule.rule_id == "retailer_a.revenue_decline.v1" for rule in registry.rules)


def test_unknown_event_concept_fails(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
event_rules:
  - event_rule_id: retailer_a.unknown.v1
    retailer_id: retailer_a
    rule_version: rules_v1
    event_type: UNKNOWN_SIGNAL
    event_family: GROWTH_DECLINE
    input_source: comparison
    conditions: []
""",
        encoding="utf-8",
    )

    result = load_event_rule_config(path)

    assert result.quality_report.issues[0].issue_code == "UNKNOWN_EVENT_CONCEPT"


def test_duplicate_event_rule_id_fails(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
event_rules:
  - event_rule_id: retailer_a.duplicate.v1
    retailer_id: retailer_a
    rule_version: rules_v1
    event_type: MATERIAL_REVENUE_DECLINE
    event_family: GROWTH_DECLINE
    input_source: comparison
    conditions:
      - field: delta_pct
        operator: lte
        value: -0.10
  - event_rule_id: retailer_a.duplicate.v1
    retailer_id: retailer_a
    rule_version: rules_v1
    event_type: MATERIAL_REVENUE_DECLINE
    event_family: GROWTH_DECLINE
    input_source: comparison
    conditions:
      - field: delta_pct
        operator: lte
        value: -0.10
""",
        encoding="utf-8",
    )

    result = load_event_rule_config(path)

    assert result.quality_report.issues[0].issue_code == "DUPLICATE_EVENT_RULE_ID"


def test_empty_condition_rule_fails_validation(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
event_rules:
  - event_rule_id: retailer_a.empty_conditions.v1
    retailer_id: retailer_a
    rule_version: rules_v1
    event_type: MATERIAL_REVENUE_DECLINE
    event_family: GROWTH_DECLINE
    input_source: comparison
    conditions: []
""",
        encoding="utf-8",
    )

    result = load_event_rule_config(path)

    assert result.quality_report.issues[0].issue_code == "INVALID_EVENT_CONDITION"


def test_rule_version_is_preserved():
    registry = load_event_rule_config("config/public/demo/event_rules.yaml")

    assert {rule.rule_version for rule in registry.rules} == {"rules_v1"}


def test_invalid_operator_fails(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
event_rules:
  - event_rule_id: retailer_a.invalid_operator.v1
    retailer_id: retailer_a
    rule_version: rules_v1
    event_type: MATERIAL_REVENUE_DECLINE
    event_family: GROWTH_DECLINE
    input_source: comparison
    conditions:
      - field: delta_pct
        operator: __import__
        value: 0
""",
        encoding="utf-8",
    )

    result = load_event_rule_config(path)

    assert result.quality_report.issues[0].issue_code == "UNSUPPORTED_EVENT_OPERATOR"


def test_condition_evaluator_supports_all_configured_operators():
    frame = pl.DataFrame({"value": [2], "label": ["A"]})

    for condition in (
        RuleCondition("value", "gt", 1),
        RuleCondition("value", "gte", 2),
        RuleCondition("value", "lt", 3),
        RuleCondition("value", "lte", 2),
        RuleCondition("label", "eq", "A"),
        RuleCondition("value", "between", [1, 3]),
        RuleCondition("label", "in", ["A", "B"]),
        RuleCondition("label", "not_in", ["C"]),
    ):
        mask, report = evaluate_conditions(frame, (condition,))
        assert report.is_valid
        assert mask.to_list() == [True]


def test_revenue_decline_fires_at_threshold():
    result = detect_events(
        _facts(),
        (_rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10)),),
        _context(),
    )

    assert result.events["event_type"].to_list() == ["MATERIAL_REVENUE_DECLINE"]


def test_revenue_decline_does_not_fire_below_threshold():
    result = detect_events(
        _facts(revenue_delta=-0.099),
        (_rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10)),),
        _context(),
    )

    assert result.events.is_empty()


def test_revenue_decline_exact_boundary_is_inclusive():
    result = detect_events(
        _facts(revenue_delta=-0.10),
        (_rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10)),),
        _context(),
    )

    assert not result.events.is_empty()


def test_units_growth_event():
    result = detect_events(
        _facts(),
        (_rule("MATERIAL_UNITS_GROWTH", "units", RuleCondition("delta_pct", "gte", 0.10)),),
        _context(),
    )

    assert result.events["event_type"].to_list() == ["MATERIAL_UNITS_GROWTH"]


def test_margin_decline_event():
    result = detect_events(
        _facts(),
        (_rule("MATERIAL_MARGIN_DECLINE", "retailer_margin_abs", RuleCondition("delta_pct", "lte", -0.10)),),
        _context(),
    )

    assert result.events["feature_name"].to_list() == ["retailer_margin_abs"]


def test_event_preserves_current_and_base_values():
    result = detect_events(
        _facts(),
        (_rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10)),),
        _context(),
    )

    assert result.events["observed_value"].to_list() == [90.0]
    assert result.events["reference_value"].to_list() == [100.0]


def test_distribution_loss_uses_existing_distribution_metric():
    result = detect_events(
        _facts(),
        (_rule("DISTRIBUTION_LOSS", "distribution", RuleCondition("delta_pp", "lte", -0.05), family="DISTRIBUTION"),),
        _context(),
    )

    assert result.events["event_type"].to_list() == ["DISTRIBUTION_LOSS"]


def test_velocity_loss_uses_metric_definition_lineage():
    result = detect_events(
        _facts(),
        (_rule("VELOCITY_LOSS", "velocity", RuleCondition("delta_pct", "lte", -0.10), family="VELOCITY"),),
        _context(),
    )

    assert "retailer_a.velocity.v1" in result.events["metric_lineage"].to_list()[0]


def test_missing_velocity_metric_prevents_event():
    facts = _facts().filter(pl.col("feature_name") != "velocity")
    result = detect_events(
        facts,
        (_rule("VELOCITY_LOSS", "velocity", RuleCondition("delta_pct", "lte", -0.10), family="VELOCITY"),),
        _context(),
    )

    assert result.events.is_empty()
    assert result.quality_report.issues[0].issue_code == "MISSING_EVENT_FEATURE"


def test_price_increase_event():
    result = detect_events(
        _facts(),
        (_rule("PRICE_INCREASE", "weighted_shelf_price_vat", RuleCondition("delta_pct", "gte", 0.10), family="PRICE"),),
        _context(),
    )

    assert result.events["event_type"].to_list() == ["PRICE_INCREASE"]


def test_margin_pct_delta_uses_percentage_points():
    result = detect_events(
        _facts(),
        (_rule("MARGIN_PCT_EROSION", "retailer_margin_pct", RuleCondition("delta_pp", "lte", -0.02), family="MARGIN_PCT"),),
        _context(),
    )

    assert result.events["delta_pp"].to_list() == [-0.03]


def test_abc_class_change_event():
    facts = build_event_facts(abc=_abc(), context=_context()).event_facts
    result = detect_events(
        facts,
        (_rule("ABC_CLASS_CHANGE", "abc_revenue", RuleCondition("label_changed", "eq", True), source="abc", family="PORTFOLIO"),),
        _context(),
    )

    assert result.events["current_class"].to_list() == ["B"]
    assert result.events["reference_class"].to_list() == ["A"]


def test_same_abc_class_does_not_fire_change_event():
    abc = _abc().with_columns(pl.lit("B").alias("reference_abc_class"))
    facts = build_event_facts(abc=abc, context=_context()).event_facts
    result = detect_events(
        facts,
        (_rule("ABC_CLASS_CHANGE", "abc_revenue", RuleCondition("label_changed", "eq", True), source="abc", family="PORTFOLIO"),),
        _context(),
    )

    assert result.events.is_empty()


def test_high_velocity_low_distribution_pattern():
    facts = build_event_facts(benchmark_features=_benchmark(), context=_context()).event_facts
    result = detect_events(
        facts,
        (
            _rule(
                "HIGH_VELOCITY_LOW_DISTRIBUTION",
                "units_per_selling_store",
                RuleCondition("percentile", "gte", 0.80),
                source="benchmark",
                family="BENCHMARK",
            ),
        ),
        _context(),
    )

    assert result.events["event_family"].to_list() == ["BENCHMARK"]


def test_peer_outperformance_pattern():
    facts = build_event_facts(benchmark_features=_benchmark(), context=_context()).event_facts
    result = detect_events(
        facts,
        (_rule("PEER_OUTPERFORMANCE", "revenue_net", RuleCondition("percentile", "gte", 0.80), source="benchmark", family="BENCHMARK"),),
        _context(),
    )

    assert result.events["event_type"].to_list() == ["PEER_OUTPERFORMANCE"]


def test_empty_peer_context_does_not_create_false_event():
    facts = build_event_facts(benchmark_features=pl.DataFrame(), context=_context()).event_facts
    result = detect_events(
        facts,
        (_rule("PEER_OUTPERFORMANCE", "revenue_net", RuleCondition("percentile", "gte", 0.80), source="benchmark", family="BENCHMARK"),),
        _context(),
    )

    assert result.events.is_empty()


def test_price_pressure_is_not_causal_claim():
    result = detect_events(
        _facts(distribution_delta=-0.01),
        (
            _rule(
                "PRICE_PRESSURE_PATTERN",
                "weighted_shelf_price_vat",
                RuleCondition("weighted_shelf_price_vat_delta_pct", "gte", 0.10),
                family="PATTERN_CANDIDATE",
                confidence="MEDIUM",
                required_features=("weighted_shelf_price_vat", "velocity", "distribution"),
                hypothesis_candidates=("PRICE_ELASTICITY",),
            ),
        ),
        _context(),
    )

    assert result.events["event_type"].to_list() == ["PRICE_PRESSURE_PATTERN"]
    assert "PRICE_ELASTICITY" in result.events["hypothesis_candidates"].to_list()[0]
    assert "cause" not in result.events.columns


def test_entity_can_have_multiple_events():
    result = detect_events(
        _facts(),
        (
            _rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10)),
            _rule("PRICE_INCREASE", "weighted_shelf_price_vat", RuleCondition("delta_pct", "gte", 0.10), family="PRICE"),
        ),
        _context(),
    )

    assert set(result.events["event_type"].to_list()) == {"MATERIAL_REVENUE_DECLINE", "PRICE_INCREASE"}


def test_same_event_rule_does_not_duplicate():
    rule = _rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10))
    result = detect_events(pl.concat([_facts(), _facts()], how="diagonal"), (rule,), _context())

    assert result.events.height == 1


def test_event_identity_is_deterministic():
    rule = _rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10))
    first = detect_events(_facts(), (rule,), _context())
    second = detect_events(_facts(), (rule,), _context())

    assert first.events["event_id"].to_list() == second.events["event_id"].to_list()


def test_event_identity_includes_full_context_scope():
    rule_a = _rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10))
    rule_b = _rule(
        "MATERIAL_REVENUE_DECLINE",
        "revenue",
        RuleCondition("delta_pct", "lte", -0.10),
        retailer_id="retailer_b",
    )
    event_a = detect_events(_facts(), (rule_a,), _context()).events
    event_b = detect_events(_facts(retailer_id="retailer_b"), (rule_b,), _context("retailer_b")).events

    assert event_a["event_id"].to_list() != event_b["event_id"].to_list()


def test_event_rules_are_retailer_scoped():
    result = detect_events(
        _facts(),
        (_rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10), retailer_id="retailer_b"),),
        _context(),
    )

    assert result.events.is_empty()


def test_same_sku_id_across_retailers_produces_independent_events():
    rule = _rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10), retailer_id="retailer_b")
    facts = _facts(retailer_id="retailer_b")
    result = detect_events(facts, (rule,), _context("retailer_b"))

    assert result.events["retailer_id"].to_list() == ["retailer_b"]


def test_event_evaluation_does_not_cross_source_boundary():
    facts = _facts(source_id="source_b")
    result = detect_events(
        facts,
        (_rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10)),),
        _context(source_id="source_a"),
    )

    assert result.events.is_empty()


def test_event_records_missing_optional_evidence():
    result = detect_events(
        _facts(),
        (
            _rule(
                "PRICE_PRESSURE_PATTERN",
                "weighted_shelf_price_vat",
                RuleCondition("delta_pct", "gte", 0.10),
                family="PATTERN_CANDIDATE",
                optional_evidence=("promo_calendar", "stock"),
            ),
        ),
        _context(),
    )

    assert "promo_calendar" in result.events["missing_evidence"].to_list()[0]


def test_benchmark_lineage_preserves_slice3_rule_metadata():
    facts = build_event_facts(benchmark_features=_benchmark(), context=_context()).event_facts
    result = detect_events(
        facts,
        (_rule("PEER_OUTPERFORMANCE", "revenue_net", RuleCondition("percentile", "gte", 0.80), source="benchmark", family="BENCHMARK"),),
        _context(),
    )

    assert "retailer_a.category_pool.v1" in result.events["benchmark_lineage"].to_list()[0]
    assert "peer_hash" in result.events["benchmark_lineage"].to_list()[0]


def test_event_facts_are_rule_version_scoped():
    stale = _comparison_frame().with_columns(pl.lit("old_rules").alias("rule_version"))
    mixed = pl.concat([_comparison_frame(), stale], how="diagonal")
    facts = build_event_facts(comparisons=mixed, context=_context()).event_facts

    assert set(facts["rule_version"].to_list()) == {"rules_v1"}


def test_upstream_blocking_quality_prevents_events():
    result = detect_events(
        _facts(),
        (_rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10)),),
        _context(),
        upstream_quality_report=QualityReport((QualityIssue("UPSTREAM_FAILURE", "ERROR", 1),)),
    )

    assert result.events.is_empty()
    assert result.quality_report.issues[0].issue_code == "UPSTREAM_QUALITY_BLOCKED"


def test_event_enrichment_does_not_mutate_input_frame():
    facts = _facts()
    before = facts.clone()

    detect_events(facts, (_rule("MATERIAL_REVENUE_DECLINE", "revenue", RuleCondition("delta_pct", "lte", -0.10)),), _context())

    assert facts.equals(before)


def test_event_result_has_no_recommendation_leakage():
    result = run_slice4_event_engine(
        comparisons=_comparison_frame(),
        abc=_abc(),
        benchmark_features=_benchmark(),
        event_rules="config/public/demo/event_rules.yaml",
        context=_context(),
    )

    forbidden = {"recommended_action", "buyer_message", "next_step", "expected_revenue_gain", "investment"}
    assert not forbidden.intersection(result.events.columns)


def _rule(
    event_type: str,
    feature_name: str,
    condition: RuleCondition,
    *,
    source: str = "comparison",
    family: str = "GROWTH_DECLINE",
    retailer_id: str = "retailer_a",
    confidence: str = "HIGH",
    required_features: tuple[str, ...] | None = None,
    hypothesis_candidates: tuple[str, ...] = (),
    optional_evidence: tuple[str, ...] = (),
) -> EventRule:
    return EventRule(
        rule_id=f"{retailer_id}.{event_type.lower()}.v1",
        rule_version="rules_v1",
        retailer_id=retailer_id,
        event_type=event_type,
        event_family=family,
        input_source=source,
        required_features=required_features or (feature_name,),
        conditions=(condition,),
        confidence=confidence,
        hypothesis_candidates=hypothesis_candidates,
        optional_evidence=optional_evidence,
    )


def _facts(
    *,
    retailer_id: str = "retailer_a",
    source_id: str = "source_a",
    revenue_delta: float = -0.10,
    distribution_delta: float = -0.10,
) -> pl.DataFrame:
    return build_event_facts(
        comparisons=_comparison_frame(retailer_id, source_id, revenue_delta, distribution_delta),
        context=_context(retailer_id, source_id),
    ).event_facts


def _comparison_frame(
    retailer_id: str = "retailer_a",
    source_id: str = "source_a",
    revenue_delta: float = -0.10,
    distribution_delta: float = -0.10,
) -> pl.DataFrame:
    rows = [
        _comparison_row(retailer_id, source_id, "revenue", 90.0, 100.0, -10.0, revenue_delta, None),
        _comparison_row(retailer_id, source_id, "units", 120.0, 100.0, 20.0, 0.20, None),
        _comparison_row(retailer_id, source_id, "retailer_margin_abs", 80.0, 100.0, -20.0, -0.20, None),
        _comparison_row(retailer_id, source_id, "distribution", 0.80 + distribution_delta, 0.80, distribution_delta, distribution_delta / 0.80, distribution_delta),
        _comparison_row(retailer_id, source_id, "velocity", 8.0, 10.0, -2.0, -0.20, None),
        _comparison_row(retailer_id, source_id, "weighted_shelf_price_vat", 12.0, 10.0, 2.0, 0.20, None),
        _comparison_row(retailer_id, source_id, "retailer_margin_pct", 0.17, 0.20, -0.03, -0.15, -0.03),
    ]
    return pl.DataFrame(rows)


def _comparison_row(
    retailer_id: str,
    source_id: str,
    feature_name: str,
    current: float,
    reference: float,
    delta_abs: float,
    delta_pct: float,
    delta_pp: float | None,
) -> dict[str, object]:
    return {
        "analysis_run_id": "run_a",
        "retailer_id": retailer_id,
        "source_id": source_id,
        "rule_version": "rules_v1",
        "period": date(2026, 2, 1),
        "category": "CATEGORY_A",
        "entity_type": "sku",
        "entity_id": "SKU_A_001",
        "concept": feature_name,
        "metric_name": feature_name,
        "metric_definition_id": f"{retailer_id}.{feature_name}.v1",
        "metric_definition_version": "v1",
        "metric_config_hash": "metric_hash",
        "comparison_type": "YOY",
        "current_period": date(2026, 2, 1),
        "reference_period": date(2025, 2, 1),
        "comparison_quality": "HIGH",
        "current_value": current,
        "reference_value": reference,
        "delta_abs": delta_abs,
        "delta_pct": delta_pct,
        "delta_pp": delta_pp,
        "comparable": True,
    }


def _abc() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["run_a"],
            "retailer_id": ["retailer_a"],
            "source_id": ["source_a"],
            "rule_version": ["rules_v1"],
            "period": [date(2026, 2, 1)],
            "reference_period": [date(2025, 2, 1)],
            "category": ["CATEGORY_A"],
            "entity_type": ["sku"],
            "entity_id": ["SKU_A_001"],
            "abc_metric": ["abc_revenue"],
            "abc_class": ["B"],
            "reference_abc_class": ["A"],
        }
    )


def _benchmark() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["run_a", "run_a"],
            "retailer_id": ["retailer_a", "retailer_a"],
            "source_id": ["source_a", "source_a"],
            "rule_version": ["rules_v1", "rules_v1"],
            "reference_period": [date(2026, 2, 1), date(2026, 2, 1)],
            "target_entity_id": ["SKU_A_001", "SKU_A_001"],
            "entity_type": ["sku", "sku"],
            "category": ["CATEGORY_A", "CATEGORY_A"],
            "benchmark_scope": ["BROAD_CATEGORY", "BROAD_CATEGORY"],
            "benchmark_scope_id": ["scope_a", "scope_a"],
            "pool_source": ["CATEGORY_POOL", "CATEGORY_POOL"],
            "peer_rule_id": ["retailer_a.category_pool.v1", "retailer_a.category_pool.v1"],
            "peer_rule_version": ["rules_v1", "rules_v1"],
            "peer_config_hash": ["peer_hash", "peer_hash"],
            "metric_name": ["units_per_selling_store", "revenue_net"],
            "metric_definition_id": ["retailer_a.velocity.v1", "retailer_a.revenue_net.v1"],
            "metric_definition_version": ["v1", "v1"],
            "metric_value": [12.0, 99.0],
            "rank": [1, 1],
            "percentile": [0.90, 0.85],
            "population_size": [5, 5],
        }
    )
