"""Safe deterministic rule evaluator primitives."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import polars as pl

from retail_analytics.core.rule_engine.conditions import RuleCondition
from retail_analytics.quality.report import QualityIssue, QualityReport


def evaluate_conditions(frame: pl.DataFrame, conditions: Sequence[RuleCondition]) -> tuple[pl.Series, QualityReport]:
    """Evaluate declarative conditions as a boolean mask over a frame."""
    issues: list[QualityIssue] = []
    if frame.is_empty():
        return pl.Series("__condition_match", [], dtype=pl.Boolean), QualityReport()

    mask = pl.Series("__condition_match", [True] * frame.height, dtype=pl.Boolean)
    for condition in conditions:
        if condition.field not in frame.columns:
            issues.append(
                QualityIssue(
                    "MISSING_EVENT_FEATURE",
                    "WARNING",
                    frame.height,
                    (),
                    f"Missing condition field: {condition.field}.",
                    condition.field,
                )
            )
            return pl.Series("__condition_match", [False] * frame.height, dtype=pl.Boolean), QualityReport(tuple(issues))
        condition_mask = frame.select(_condition_expr(condition).fill_null(False).alias("__match")).get_column("__match")
        mask = mask & condition_mask
    return mask, QualityReport(tuple(issues))


def _condition_expr(condition: RuleCondition) -> pl.Expr:
    column = pl.col(condition.field)
    value: Any = condition.value
    if condition.operator == "gt":
        return column > value
    if condition.operator == "gte":
        return column >= value
    if condition.operator == "lt":
        return column < value
    if condition.operator == "lte":
        return column <= value
    if condition.operator == "eq":
        return column == value
    if condition.operator == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("between condition requires a two-value list")
        return column.is_between(value[0], value[1], closed="both")
    if condition.operator == "in":
        return column.is_in(value if isinstance(value, (list, tuple, set)) else [value])
    if condition.operator == "not_in":
        return ~column.is_in(value if isinstance(value, (list, tuple, set)) else [value])
    raise ValueError(f"unsupported condition operator: {condition.operator}")
