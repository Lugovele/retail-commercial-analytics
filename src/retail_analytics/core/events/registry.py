"""Config loading for deterministic event rules."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from retail_analytics.core.concepts.events import EVENT_FAMILIES, EVENT_TYPES
from retail_analytics.core.events.contracts import EventRule, EventRuleRegistry
from retail_analytics.core.rule_engine.conditions import parse_condition
from retail_analytics.quality.report import QualityIssue, QualityReport


def load_event_rule_config(path: str | Path) -> EventRuleRegistry:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    config_hash = _config_hash(payload)
    rules: list[EventRule] = []
    issues: list[QualityIssue] = []
    seen: set[str] = set()
    for raw in payload.get("event_rules", ()):
        if not isinstance(raw, dict):
            continue
        rule_id = str(raw.get("event_rule_id", raw.get("rule_id", raw.get("id", ""))))
        if rule_id in seen:
            issues.append(QualityIssue("DUPLICATE_EVENT_RULE_ID", "ERROR", 1, (), f"Duplicate event rule id: {rule_id}."))
            continue
        seen.add(rule_id)
        try:
            rule = _event_rule(raw, payload)
        except ValueError as exc:
            issues.append(QualityIssue(_issue_code(str(exc)), "ERROR", 1, (), str(exc)))
            continue
        rules.append(rule)
    return EventRuleRegistry(tuple(rules), QualityReport(tuple(issues)), config_hash)


def _event_rule(raw: dict[str, Any], payload: dict[str, Any]) -> EventRule:
    event_type = str(raw.get("event_type", raw.get("event_concept", "")))
    event_family = str(raw.get("event_family", ""))
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event concept: {event_type}")
    if event_family not in EVENT_FAMILIES:
        raise ValueError(f"unknown event family: {event_family}")
    conditions = tuple(parse_condition(condition) for condition in raw.get("conditions", ()))
    if not conditions:
        raise ValueError("event rule requires at least one condition")
    return EventRule(
        rule_id=str(raw.get("event_rule_id", raw.get("rule_id", raw.get("id", "")))),
        rule_version=str(raw.get("rule_version", payload.get("rule_version", ""))),
        retailer_id=str(raw.get("retailer_id", "")),
        source_id=raw.get("source_id"),
        event_type=event_type,
        event_family=event_family,
        input_source=str(raw.get("input_source", "")),
        required_features=tuple(str(value) for value in raw.get("required_features", ())),
        required_metrics=tuple(str(value) for value in raw.get("required_metrics", ())),
        entity_types=tuple(str(value) for value in raw.get("entity_types", ("sku",))),
        comparison_types=tuple(str(value) for value in raw.get("comparison_types", ())),
        conditions=conditions,
        severity=raw.get("severity", "MEDIUM"),
        confidence=raw.get("confidence", "HIGH"),
        observed_drivers=tuple(str(value) for value in raw.get("observed_drivers", ())),
        hypothesis_candidates=tuple(str(value) for value in raw.get("hypothesis_candidates", ())),
        optional_evidence=tuple(str(value) for value in raw.get("optional_evidence", ())),
        enabled=bool(raw.get("enabled", True)),
    )


def _issue_code(message: str) -> str:
    if "operator" in message:
        return "UNSUPPORTED_EVENT_OPERATOR"
    if "concept" in message:
        return "UNKNOWN_EVENT_CONCEPT"
    if "condition" in message:
        return "INVALID_EVENT_CONDITION"
    return "INVALID_EVENT_RULE"


def _config_hash(payload: object) -> str:
    normalized = json.dumps(payload, default=str, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
