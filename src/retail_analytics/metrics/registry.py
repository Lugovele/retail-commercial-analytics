"""Config-driven metric definition registry."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from retail_analytics.pipeline.context import AnalysisContext

MetricAggregation = Literal[
    "sum",
    "ratio_of_sums",
    "weighted_average",
    "distinct_count",
    "derived_ratio",
]


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    concept: str
    definition_id: str
    definition_version: str
    aggregation: MetricAggregation
    source_column: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    value_column: str | None = None
    weight_column: str | None = None
    distinct_column: str | None = None
    condition: dict[str, Any] | None = None
    grain: tuple[str, ...] = ("period", "canonical_product_id")
    broadcast_grain: tuple[str, ...] | None = None
    share_denominator_scope: str | None = None
    entity_type: str = "sku"
    retailer_id: str | None = None
    source_id: str | None = None
    rule_version: str | None = None


@dataclass(frozen=True)
class MetricDefinitionConfig:
    definitions: tuple[MetricDefinition, ...]
    config_hash: str


class MetricRegistry:
    """Lookup and context filtering for configured metric definitions."""

    def __init__(self, definitions: tuple[MetricDefinition, ...], config_hash: str) -> None:
        self.definitions = definitions
        self.config_hash = config_hash

    def get(self, name: str) -> MetricDefinition:
        for definition in self.definitions:
            if definition.name == name:
                return definition
        raise KeyError(name)

    def for_context(self, context: AnalysisContext) -> MetricRegistry:
        definitions = tuple(
            definition
            for definition in self.definitions
            if (definition.retailer_id is None or definition.retailer_id == context.retailer_id)
            and (definition.source_id is None or definition.source_id == context.source_id)
            and (definition.rule_version is None or definition.rule_version == context.rule_version)
        )
        return MetricRegistry(definitions, self.config_hash)


def load_metric_definition_config(path: str | Path) -> MetricRegistry:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw_definitions = payload.get("metrics", {})
    config_rule_version = payload.get("rule_version")
    definitions: list[MetricDefinition] = []

    if isinstance(raw_definitions, dict):
        items = raw_definitions.items()
    else:
        items = ((item.get("name", item.get("id")), item) for item in raw_definitions if isinstance(item, dict))

    for name, raw in items:
        if not isinstance(raw, dict) or not name:
            continue
        definitions.append(
            MetricDefinition(
                name=str(name),
                concept=str(raw.get("concept", name)),
                definition_id=str(raw.get("definition_id", raw.get("id", name))),
                definition_version=str(raw.get("definition_version", raw.get("version", config_rule_version or ""))),
                aggregation=raw.get("aggregation", "sum"),
                source_column=raw.get("source_column"),
                numerator=raw.get("numerator"),
                denominator=raw.get("denominator"),
                value_column=raw.get("value_column"),
                weight_column=raw.get("weight_column"),
                distinct_column=raw.get("distinct_column"),
                condition=raw.get("condition"),
                grain=tuple(raw.get("grain", ("period", "canonical_product_id"))),
                broadcast_grain=tuple(raw["broadcast_grain"]) if "broadcast_grain" in raw else None,
                share_denominator_scope=raw.get("share_denominator_scope"),
                entity_type=str(raw.get("entity_type", "sku")),
                retailer_id=raw.get("retailer_id"),
                source_id=raw.get("source_id"),
                rule_version=raw.get("rule_version", config_rule_version),
            )
        )
    return MetricRegistry(tuple(definitions), _config_hash(payload))


def _config_hash(payload: object) -> str:
    normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
