"""Declarative rule condition primitives."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ConditionOperator = Literal["gt", "gte", "lt", "lte", "eq", "between", "in", "not_in"]

SUPPORTED_OPERATORS: frozenset[str] = frozenset(
    {"gt", "gte", "lt", "lte", "eq", "between", "in", "not_in"}
)


@dataclass(frozen=True)
class RuleCondition:
    field: str
    operator: ConditionOperator
    value: Any


def parse_condition(raw: dict[str, Any]) -> RuleCondition:
    field = str(raw.get("field", ""))
    operator = str(raw.get("operator", ""))
    if not field:
        raise ValueError("condition field is required")
    if operator not in SUPPORTED_OPERATORS:
        raise ValueError(f"unsupported condition operator: {operator}")
    return RuleCondition(field=field, operator=operator, value=raw.get("value"))
