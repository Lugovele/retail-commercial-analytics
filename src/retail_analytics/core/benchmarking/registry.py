"""Config loaders for benchmarking rules."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from retail_analytics.core.benchmarking.contracts import PeerRule, PriceSegmentRule
from retail_analytics.pipeline.context import AnalysisContext


def load_peer_rule_config(path: str | Path) -> tuple[tuple[PeerRule, ...], str]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = tuple(_peer_rule(raw, payload) for raw in payload.get("peer_rules", ()) if isinstance(raw, dict))
    return rules, _config_hash(payload)


def load_price_segment_rule_config(path: str | Path) -> tuple[tuple[PriceSegmentRule, ...], str]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = tuple(
        _price_segment_rule(raw, payload)
        for raw in payload.get("price_segment_rules", ())
        if isinstance(raw, dict)
    )
    return rules, _config_hash(payload)


def peer_rules_for_context(rules: tuple[PeerRule, ...], context: AnalysisContext) -> tuple[PeerRule, ...]:
    return tuple(
        rule
        for rule in rules
        if rule.retailer_id == context.retailer_id
        and (rule.source_id is None or rule.source_id == context.source_id)
        and rule.rule_version == context.rule_version
    )


def price_segment_rules_for_context(
    rules: tuple[PriceSegmentRule, ...],
    context: AnalysisContext,
) -> tuple[PriceSegmentRule, ...]:
    return tuple(
        rule
        for rule in rules
        if rule.retailer_id == context.retailer_id
        and (rule.source_id is None or rule.source_id == context.source_id)
        and rule.rule_version == context.rule_version
    )


def _peer_rule(raw: dict, payload: dict) -> PeerRule:
    return PeerRule(
        rule_id=str(raw.get("peer_rule_id", raw.get("rule_id", raw.get("id", "")))),
        rule_version=str(raw.get("rule_version", payload.get("rule_version", ""))),
        retailer_id=str(raw.get("retailer_id", "")),
        peer_level=raw.get("peer_level", "BROAD_CATEGORY"),
        required_dimensions=tuple(raw.get("required_dimensions", ())),
        optional_dimensions=tuple(raw.get("optional_dimensions", ())),
        filters=raw.get("filters"),
        fallback_behavior=str(raw.get("fallback_behavior", "REPORT_EMPTY")),
        direct_peer_mode=raw.get("direct_peer_mode", "DIRECT_ONLY"),
        self_inclusion=raw.get("self_inclusion", "EXCLUDE_SELF"),
        top_n=int(raw.get("top_n", 10)),
        ranking_metrics=tuple(raw.get("ranking_metrics", ("revenue_net", "units", "units_per_selling_store"))),
        source_id=raw.get("source_id"),
    )


def _price_segment_rule(raw: dict, payload: dict) -> PriceSegmentRule:
    return PriceSegmentRule(
        rule_id=str(raw.get("price_segment_rule_id", raw.get("rule_id", raw.get("id", "")))),
        rule_version=str(raw.get("rule_version", payload.get("rule_version", ""))),
        retailer_id=str(raw.get("retailer_id", "")),
        source_id=raw.get("source_id"),
        segments=tuple(str(segment) for segment in raw.get("segments", ("ECONOMY", "MID", "PREMIUM"))),
        price_metric_name=str(raw.get("price_metric_name", "weighted_shelf_price_vat")),
        min_segment_population=int(raw.get("min_segment_population", 3)),
    )


def _config_hash(payload: object) -> str:
    normalized = json.dumps(payload, default=str, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
