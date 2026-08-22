"""Generic rule resolver helpers."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

from retail_analytics.pipeline.context import AnalysisContext


class ContextRule(Protocol):
    retailer_id: str
    source_id: str | None
    rule_version: str
    enabled: bool


RuleT = TypeVar("RuleT", bound=ContextRule)


def rules_for_context(rules: Iterable[RuleT], context: AnalysisContext) -> tuple[RuleT, ...]:
    return tuple(
        rule
        for rule in rules
        if rule.enabled
        and rule.retailer_id == context.retailer_id
        and (rule.source_id is None or rule.source_id == context.source_id)
        and rule.rule_version == context.rule_version
    )
