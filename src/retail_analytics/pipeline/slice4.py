"""Thin Slice 4 deterministic event engine orchestrator."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from retail_analytics.core.events.contracts import (
    EventRule,
    EventRuleRegistry,
    Slice4EventResult,
    event_rules_for_context,
)
from retail_analytics.core.events.engine import detect_events
from retail_analytics.core.events.facts import build_event_facts
from retail_analytics.core.events.registry import load_event_rule_config
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityReport


def run_slice4_event_engine(
    *,
    metrics: pl.DataFrame | None = None,
    comparisons: pl.DataFrame | None = None,
    abc: pl.DataFrame | None = None,
    benchmark_features: pl.DataFrame | None = None,
    event_rules: EventRuleRegistry | tuple[EventRule, ...] | str | Path,
    context: AnalysisContext,
    upstream_quality_report: QualityReport | None = None,
) -> Slice4EventResult:
    """Run configured event rules over prepared analytic features."""
    registry = _resolve_rules(event_rules)
    context_rules = event_rules_for_context(registry.rules, context)
    fact_result = build_event_facts(
        metrics=metrics,
        comparisons=comparisons,
        abc=abc,
        benchmark_features=benchmark_features,
        context=context,
    )
    upstream = (upstream_quality_report or QualityReport()).extend(registry.quality_report).extend(
        fact_result.quality_report
    )
    event_result = detect_events(
        fact_result.event_facts,
        context_rules,
        context,
        upstream_quality_report=upstream,
        event_config_hash=registry.config_hash,
    )
    return Slice4EventResult(
        context=context,
        events=event_result.events,
        event_facts=fact_result.event_facts,
        quality_report=upstream.extend(event_result.quality_report),
        event_config_hash=registry.config_hash,
    )


def _resolve_rules(event_rules: EventRuleRegistry | tuple[EventRule, ...] | str | Path) -> EventRuleRegistry:
    if isinstance(event_rules, EventRuleRegistry):
        return event_rules
    if isinstance(event_rules, (str, Path)):
        return load_event_rule_config(event_rules)
    return EventRuleRegistry(event_rules, QualityReport(), "")
