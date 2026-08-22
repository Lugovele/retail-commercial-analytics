"""Deterministic commercial event engine."""

from retail_analytics.core.events.contracts import (
    EventFactResult,
    EventResult,
    EventRule,
    EventRuleRegistry,
    Slice4EventResult,
    event_rules_for_context,
)
from retail_analytics.core.events.engine import detect_events
from retail_analytics.core.events.facts import build_event_facts
from retail_analytics.core.events.registry import load_event_rule_config

__all__ = [
    "EventFactResult",
    "EventResult",
    "EventRule",
    "EventRuleRegistry",
    "Slice4EventResult",
    "build_event_facts",
    "detect_events",
    "event_rules_for_context",
    "load_event_rule_config",
]
