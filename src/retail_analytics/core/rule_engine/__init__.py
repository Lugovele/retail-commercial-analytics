"""Declarative rule engine primitives."""

from retail_analytics.core.rule_engine.conditions import (
    SUPPORTED_OPERATORS,
    RuleCondition,
    parse_condition,
)
from retail_analytics.core.rule_engine.evaluator import evaluate_conditions
from retail_analytics.core.rule_engine.resolver import rules_for_context

__all__ = [
    "SUPPORTED_OPERATORS",
    "RuleCondition",
    "evaluate_conditions",
    "parse_condition",
    "rules_for_context",
]
