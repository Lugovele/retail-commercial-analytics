"""Config-driven store identity normalization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import yaml

from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.schema.validation import ValidationIssue, ValidationReport


@dataclass(frozen=True)
class StoreAliasMapping:
    """Exact source-store to canonical-store aliases scoped by retailer/source."""

    aliases: dict[str, str]
    rule_version: str | None = None
    retailer_id: str | None = None
    source_id: str | None = None

    @property
    def config_hash(self) -> str:
        payload = {
            "aliases": self.aliases,
            "rule_version": self.rule_version,
            "retailer_id": self.retailer_id,
            "source_id": self.source_id,
        }
        normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def for_context(self, context: AnalysisContext) -> StoreAliasMapping:
        if self.retailer_id is not None and self.retailer_id != context.retailer_id:
            return StoreAliasMapping({})
        if self.source_id is not None and self.source_id != context.source_id:
            return StoreAliasMapping({})
        if self.rule_version is not None and self.rule_version != context.rule_version:
            return StoreAliasMapping({})
        return self


def load_store_alias_mapping(path: str | Path) -> tuple[StoreAliasMapping, ValidationReport]:
    """Load generic store aliases from a caller-provided YAML path."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return StoreAliasMapping({}), ValidationReport((ValidationIssue("invalid_store_alias_config", "Store alias config root must be a mapping."),))
    aliases: dict[str, str] = {}
    issues: list[ValidationIssue] = []
    for raw in payload.get("alias_sets", ()):
        if not isinstance(raw, dict):
            issues.append(ValidationIssue("invalid_store_alias_config", "Store alias entry must be a mapping."))
            continue
        canonical = raw.get("canonical_store_id")
        source_ids = raw.get("source_store_ids", ())
        if canonical is None or not isinstance(source_ids, list):
            issues.append(ValidationIssue("invalid_store_alias_config", "Store alias entry requires canonical_store_id and source_store_ids."))
            continue
        for source_id in source_ids:
            source_key = str(source_id)
            canonical_value = str(canonical)
            if source_key in aliases and aliases[source_key] != canonical_value:
                issues.append(ValidationIssue("conflicting_store_alias", f"Conflicting alias for source store: {source_key}", source_column="source_store_id"))
                continue
            aliases[source_key] = canonical_value
    return (
        StoreAliasMapping(
            aliases=aliases,
            rule_version=payload.get("rule_version"),
            retailer_id=payload.get("retailer_id"),
            source_id=payload.get("source_id"),
        ),
        ValidationReport(tuple(issues)),
    )


def normalize_store_aliases(frame: pl.DataFrame, mapping: StoreAliasMapping | None, context: AnalysisContext) -> pl.DataFrame:
    """Preserve source_store_id and derive canonical_store_id from exact aliases."""
    if mapping is None or "source_store_id" not in frame.columns:
        return frame
    scoped = mapping.for_context(context)
    if not scoped.aliases:
        return frame
    return frame.with_columns(
        pl.col("source_store_id")
        .cast(pl.String, strict=False)
        .replace_strict(scoped.aliases, default=pl.col("source_store_id").cast(pl.String, strict=False))
        .alias("canonical_store_id")
    )
