"""Event engine contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import polars as pl

from retail_analytics.core.rule_engine.conditions import RuleCondition
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityReport

EventSeverity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
EventConfidence = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass(frozen=True)
class EventRule:
    rule_id: str
    rule_version: str
    retailer_id: str
    event_type: str
    event_family: str
    input_source: str
    conditions: tuple[RuleCondition, ...]
    required_features: tuple[str, ...] = ()
    required_metrics: tuple[str, ...] = ()
    entity_types: tuple[str, ...] = ("sku",)
    comparison_types: tuple[str, ...] = ()
    severity: EventSeverity = "MEDIUM"
    confidence: EventConfidence = "HIGH"
    observed_drivers: tuple[str, ...] = ()
    hypothesis_candidates: tuple[str, ...] = ()
    optional_evidence: tuple[str, ...] = ()
    enabled: bool = True
    source_id: str | None = None


@dataclass(frozen=True)
class EventRuleRegistry:
    rules: tuple[EventRule, ...]
    quality_report: QualityReport
    config_hash: str

    def for_context(self, context: AnalysisContext) -> tuple[EventRule, ...]:
        return event_rules_for_context(self.rules, context)


@dataclass(frozen=True)
class EventFactResult:
    event_facts: pl.DataFrame
    quality_report: QualityReport = field(default_factory=QualityReport)


@dataclass(frozen=True)
class EventResult:
    events: pl.DataFrame
    quality_report: QualityReport
    event_config_hash: str


@dataclass(frozen=True)
class Slice4EventResult:
    context: AnalysisContext
    events: pl.DataFrame
    event_facts: pl.DataFrame
    quality_report: QualityReport
    event_config_hash: str


def event_rules_for_context(rules: tuple[EventRule, ...], context: AnalysisContext) -> tuple[EventRule, ...]:
    return tuple(
        rule
        for rule in rules
        if rule.enabled
        and rule.retailer_id == context.retailer_id
        and (rule.source_id is None or rule.source_id == context.source_id)
        and rule.rule_version == context.rule_version
    )
