"""Deterministic event detection over prepared event facts."""
from __future__ import annotations

from typing import Any

import polars as pl

from retail_analytics.core.events.contracts import EventResult, EventRule, event_rules_for_context
from retail_analytics.core.events.identities import event_identity, stable_json
from retail_analytics.core.rule_engine.evaluator import evaluate_conditions
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport


def detect_events(
    event_facts: pl.DataFrame,
    event_rules: tuple[EventRule, ...],
    context: AnalysisContext,
    *,
    upstream_quality_report: QualityReport | None = None,
    event_config_hash: str = "",
) -> EventResult:
    """Apply configured rules to prepared facts without recomputing metrics."""
    upstream = upstream_quality_report or QualityReport()
    if upstream.blocking_issues:
        issue = QualityIssue(
            "UPSTREAM_QUALITY_BLOCKED",
            "ERROR",
            len(upstream.blocking_issues),
            (),
            "Upstream blocking quality issues prevent event generation.",
        )
        return EventResult(pl.DataFrame(), QualityReport((issue,)), event_config_hash)
    if event_facts.is_empty():
        return EventResult(pl.DataFrame(), QualityReport(), event_config_hash)

    rows: list[dict[str, Any]] = []
    issues: list[QualityIssue] = []
    scoped_rules = event_rules_for_context(event_rules, context)
    for rule in scoped_rules:
        if not rule.conditions:
            issues.append(
                QualityIssue(
                    "INVALID_EVENT_CONDITION",
                    "ERROR",
                    1,
                    (),
                    f"Event rule has no conditions: {rule.rule_id}.",
                )
            )
            continue
        candidates = _candidate_facts(event_facts, rule, context)
        missing_required = _missing_required_features(event_facts, rule, context)
        if missing_required:
            issues.append(
                QualityIssue(
                    "MISSING_EVENT_FEATURE",
                    "WARNING",
                    len(missing_required),
                    (),
                    f"Missing required event features: {','.join(missing_required)}.",
                )
            )
            continue
        mask, condition_report = evaluate_conditions(candidates, rule.conditions)
        issues.extend(condition_report.issues)
        matched = candidates.filter(mask) if not candidates.is_empty() else candidates
        for fact in matched.sort(_sort_columns(matched)).to_dicts():
            rows.append(_event_row(fact, rule, context, event_config_hash))
    events, dedupe_report = _dedupe_events(rows)
    issues.extend(dedupe_report.issues)
    return EventResult(events, QualityReport(tuple(issues)), event_config_hash)


def _candidate_facts(frame: pl.DataFrame, rule: EventRule, context: AnalysisContext) -> pl.DataFrame:
    scoped = frame.filter(
        (pl.col("analysis_run_id") == context.analysis_run_id)
        & (pl.col("retailer_id") == context.retailer_id)
        & (pl.col("source_id") == context.source_id)
        & (pl.col("rule_version") == context.rule_version)
        & (pl.col("input_source") == rule.input_source)
    )
    if rule.entity_types:
        scoped = scoped.filter(pl.col("entity_type").is_in(list(rule.entity_types)))
    if rule.required_metrics:
        scoped = scoped.filter(pl.col("metric_definition_id").is_in(list(rule.required_metrics)))
    if rule.comparison_types and "comparison_type" in scoped.columns:
        scoped = scoped.filter(pl.col("comparison_type").is_in(list(rule.comparison_types)))
    if len(rule.required_features) > 1:
        return _composite_candidates(scoped, rule)
    if rule.required_features:
        scoped = scoped.filter(pl.col("feature_name").is_in(list(rule.required_features)))
    return scoped


def _composite_candidates(frame: pl.DataFrame, rule: EventRule) -> pl.DataFrame:
    filtered = frame.filter(pl.col("feature_name").is_in(list(rule.required_features)))
    if filtered.is_empty():
        return filtered
    key_columns = [
        column
        for column in [
            "analysis_run_id",
            "retailer_id",
            "source_id",
            "rule_version",
            "entity_type",
            "entity_id",
            "category",
            "input_source",
            "period",
            "reference_period",
            "comparison_type",
            "comparison_quality",
            "benchmark_scope",
            "benchmark_scope_id",
            "pool_source",
        ]
        if column in filtered.columns
    ]
    rows: list[dict[str, Any]] = []
    for group in filtered.group_by(key_columns, maintain_order=True).agg(pl.struct(pl.all()).alias("__facts")).to_dicts():
        facts = group.pop("__facts")
        by_feature = {fact["feature_name"]: fact for fact in facts}
        if any(feature not in by_feature for feature in rule.required_features):
            continue
        row = dict(group)
        row["feature_name"] = "+".join(rule.required_features)
        row["observed_value"] = None
        row["reference_value"] = None
        row["observed_label"] = None
        row["reference_label"] = None
        row["label_changed"] = None
        row["metric_definition_id"] = None
        row["metric_definition_version"] = None
        row["metric_config_hash"] = None
        for feature, fact in by_feature.items():
            for value_column in [
                "observed_value",
                "reference_value",
                "delta_abs",
                "delta_pct",
                "delta_pp",
                "rank",
                "percentile",
                "population_size",
            ]:
                row[f"{feature}_{value_column}"] = fact.get(value_column)
        rows.append(row)
    return pl.DataFrame(rows)


def _missing_required_features(frame: pl.DataFrame, rule: EventRule, context: AnalysisContext) -> tuple[str, ...]:
    if not rule.required_features:
        return ()
    available = set(
        frame.filter(
            (pl.col("analysis_run_id") == context.analysis_run_id)
            & (pl.col("retailer_id") == context.retailer_id)
            & (pl.col("source_id") == context.source_id)
            & (pl.col("rule_version") == context.rule_version)
            & (pl.col("input_source") == rule.input_source)
        )
        .get_column("feature_name")
        .unique()
        .to_list()
    )
    return tuple(feature for feature in rule.required_features if feature not in available)


def _event_row(
    fact: dict[str, Any],
    rule: EventRule,
    context: AnalysisContext,
    event_config_hash: str,
) -> dict[str, Any]:
    thresholds = {condition.field: {"operator": condition.operator, "value": condition.value} for condition in rule.conditions}
    trigger_values = {
        field: fact.get(field)
        for field in [
            "observed_value",
            "reference_value",
            "observed_label",
            "reference_label",
            "delta_abs",
            "delta_pct",
            "delta_pp",
            "rank",
            "percentile",
            "population_size",
            *[key for key in fact if key.endswith(("_delta_pct", "_delta_pp", "_delta_abs"))],
        ]
        if field in fact
    }
    identity_payload = {
        "analysis_run_id": context.analysis_run_id,
        "retailer_id": context.retailer_id,
        "source_id": context.source_id,
        "rule_version": context.rule_version,
        "event_rule_id": rule.rule_id,
        "event_rule_version": rule.rule_version,
        "event_config_hash": event_config_hash,
        "event_type": rule.event_type,
        "event_family": rule.event_family,
        "entity_type": fact.get("entity_type"),
        "entity_id": fact.get("entity_id"),
        "period": fact.get("period"),
        "reference_period": fact.get("reference_period"),
        "input_source": rule.input_source,
        "feature_name": fact.get("feature_name"),
        "comparison_type": fact.get("comparison_type"),
        "benchmark_scope_id": fact.get("benchmark_scope_id"),
        "pool_source": fact.get("pool_source"),
        "peer_rule_id": fact.get("peer_rule_id"),
        "peer_rule_version": fact.get("peer_rule_version"),
        "peer_config_hash": fact.get("peer_config_hash"),
        "price_segment_rule_id": fact.get("price_segment_rule_id"),
        "price_segment_rule_version": fact.get("price_segment_rule_version"),
        "price_segment_config_hash": fact.get("price_segment_config_hash"),
    }
    return {
        "analysis_run_id": context.analysis_run_id,
        "retailer_id": context.retailer_id,
        "source_id": context.source_id,
        "rule_version": context.rule_version,
        "event_id": event_identity(identity_payload),
        "event_rule_id": rule.rule_id,
        "event_rule_version": rule.rule_version,
        "event_config_hash": event_config_hash,
        "event_type": rule.event_type,
        "event_family": rule.event_family,
        "entity_type": fact.get("entity_type"),
        "entity_id": fact.get("entity_id"),
        "category": fact.get("category"),
        "period": fact.get("period"),
        "reference_period": fact.get("reference_period"),
        "comparison_type": fact.get("comparison_type"),
        "input_source": rule.input_source,
        "feature_name": fact.get("feature_name"),
        "observed_value": fact.get("observed_value"),
        "reference_value": fact.get("reference_value"),
        "observed_label": fact.get("observed_label"),
        "reference_label": fact.get("reference_label"),
        "current_class": fact.get("observed_label"),
        "reference_class": fact.get("reference_label"),
        "delta_abs": fact.get("delta_abs"),
        "delta_pct": fact.get("delta_pct"),
        "delta_pp": fact.get("delta_pp"),
        "thresholds": stable_json(thresholds),
        "trigger_values": stable_json(trigger_values),
        "severity": rule.severity,
        "confidence": _confidence(rule, fact),
        "is_material": True,
        "observed_drivers": stable_json(list(rule.observed_drivers)),
        "hypothesis_candidates": stable_json(list(rule.hypothesis_candidates)),
        "missing_evidence": stable_json(list(rule.optional_evidence)),
        "metric_lineage": stable_json(_metric_lineage(fact)),
        "benchmark_lineage": stable_json(_benchmark_lineage(fact)),
    }


def _confidence(rule: EventRule, fact: dict[str, Any]) -> str:
    if rule.confidence == "HIGH" and fact.get("comparison_quality") == "LOW":
        return "MEDIUM"
    population_size = fact.get("population_size")
    if rule.confidence == "HIGH" and isinstance(population_size, int | float) and population_size < 2:
        return "MEDIUM"
    return rule.confidence


def _metric_lineage(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "metric_definition_id": fact.get("metric_definition_id"),
        "metric_definition_version": fact.get("metric_definition_version"),
        "metric_config_hash": fact.get("metric_config_hash"),
    }


def _benchmark_lineage(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "benchmark_scope": fact.get("benchmark_scope"),
        "benchmark_scope_id": fact.get("benchmark_scope_id"),
        "pool_source": fact.get("pool_source"),
        "peer_rule_id": fact.get("peer_rule_id"),
        "peer_rule_version": fact.get("peer_rule_version"),
        "peer_config_hash": fact.get("peer_config_hash"),
        "price_segment_rule_id": fact.get("price_segment_rule_id"),
        "price_segment_rule_version": fact.get("price_segment_rule_version"),
        "price_segment_config_hash": fact.get("price_segment_config_hash"),
    }


def _dedupe_events(rows: list[dict[str, Any]]) -> tuple[pl.DataFrame, QualityReport]:
    by_id: dict[str, dict[str, Any]] = {}
    issues: list[QualityIssue] = []
    for row in rows:
        event_id = row["event_id"]
        if event_id not in by_id:
            by_id[event_id] = row
            continue
        if by_id[event_id] != row:
            issues.append(QualityIssue("DUPLICATE_EVENT", "ERROR", 1, (), f"Conflicting duplicate event: {event_id}."))
    ordered = sorted(by_id.values(), key=lambda row: row["event_id"])
    return pl.DataFrame(ordered), QualityReport(tuple(issues))


def _sort_columns(frame: pl.DataFrame) -> list[str]:
    return [
        column
        for column in ["entity_type", "entity_id", "period", "reference_period", "feature_name", "benchmark_scope_id"]
        if column in frame.columns
    ]
