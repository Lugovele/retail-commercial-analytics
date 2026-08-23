"""Config-driven tax normalization."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import yaml  # type: ignore[import-untyped]

from retail_analytics.economics.tax_semantics import TaxSemanticMapping, parse_tax_semantic_mapping
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport


@dataclass(frozen=True)
class TaxRule:
    """Tax rule resolved by date and match conditions."""
    rule_id: str
    valid_from: date
    valid_to: date | None
    rate: float | None
    match: dict[str, Any]
    rule_version: str
    retailer_id: str | None = None
    source_id: str | None = None

    def applies_to(self, row: dict[str, Any], context: AnalysisContext) -> bool:
        row_period = row.get("period")
        if not isinstance(row_period, date):
            return False
        if self.retailer_id is not None and self.retailer_id != context.retailer_id:
            return False
        if self.source_id is not None and self.source_id != context.source_id:
            return False
        if self.rule_version != context.rule_version:
            return False
        if row_period < self.valid_from:
            return False
        if self.valid_to is not None and row_period > self.valid_to:
            return False
        return all(row.get(column) == value for column, value in self.match.items())


@dataclass(frozen=True)
class TaxNormalizationResult:
    frame: pl.DataFrame
    quality_report: QualityReport
    tax_config_hash: str


@dataclass(frozen=True)
class TaxRuleConfigResult:
    rules: tuple[TaxRule, ...]
    quality_report: QualityReport
    tax_semantic_mapping: TaxSemanticMapping | None = None


def load_tax_rule_config(path: str | Path) -> TaxRuleConfigResult:
    """Load tax rules plus structured config quality issues."""
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return TaxRuleConfigResult(
            (),
            QualityReport(
                (
                    QualityIssue(
                        "invalid_tax_rule_config",
                        "FATAL",
                        1,
                        (),
                        f"Tax rule config is not valid YAML: {exc}",
                    ),
                )
            ),
        )
    if not isinstance(payload, dict):
        return TaxRuleConfigResult(
            (),
            QualityReport(
                (
                    QualityIssue(
                        "invalid_tax_rule_config",
                        "FATAL",
                        1,
                        (),
                        "Tax rule config root must be a mapping.",
                    ),
                )
            ),
        )
    semantic_mapping, semantic_report = parse_tax_semantic_mapping(payload)
    raw_rules = payload.get("rules", payload.get("tax_rules", ()))
    config_rule_version = payload.get("rule_version")
    if not isinstance(raw_rules, list):
        issue = QualityIssue(
            "invalid_tax_rule_config",
            "FATAL",
            1,
            (),
            "Tax rule config must define rules as a list.",
            "rules",
        )
        return TaxRuleConfigResult(
            (),
            semantic_report.extend(QualityReport((issue,))),
            semantic_mapping,
        )

    rules: list[TaxRule] = []
    issues: list[QualityIssue] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            issues.append(_config_issue("Tax rule entry must be a mapping."))
            continue
        raw_match = raw_rule.get("match", {})
        if not isinstance(raw_match, dict):
            raw_match = {}
        rule_id = str(raw_rule.get("rule_id", raw_rule.get("id", ""))).strip()
        rule_version = str(raw_rule.get("rule_version", raw_rule.get("version", config_rule_version or ""))).strip()
        if not rule_id or not rule_version:
            issues.append(_config_issue("Tax rule must define rule_id and rule_version."))
            continue
        valid_from = _parse_required_date(raw_rule.get("valid_from"), field_name="valid_from")
        if valid_from is None:
            issues.append(_config_issue(f"Tax rule {rule_id} has invalid valid_from.", "valid_from"))
            continue
        valid_to = _parse_optional_date(raw_rule.get("valid_to"), field_name="valid_to")
        if raw_rule.get("valid_to") is not None and valid_to is None:
            issues.append(_config_issue(f"Tax rule {rule_id} has invalid valid_to.", "valid_to"))
            continue
        rate = _parse_rate(raw_rule.get("rate"))
        if rate is None:
            issues.append(_config_issue(f"Tax rule {rule_id} has invalid rate.", "rate"))
        rules.append(
            TaxRule(
                rule_id=rule_id,
                valid_from=valid_from,
                valid_to=valid_to,
                rate=rate,
                match={str(key): value for key, value in raw_match.items()},
                rule_version=rule_version,
                retailer_id=raw_rule.get("retailer_id"),
                source_id=raw_rule.get("source_id"),
            )
        )
    return TaxRuleConfigResult(tuple(rules), semantic_report.extend(QualityReport(tuple(issues))), semantic_mapping)


def load_tax_rules(path: str | Path) -> tuple[TaxRule, ...]:
    """Load tax rules from a public demo or private retailer config path."""
    return load_tax_rule_config(path).rules


def normalize_tax(frame: pl.DataFrame, rules: Sequence[TaxRule], context: AnalysisContext) -> TaxNormalizationResult:
    """Resolve one tax rule per row and append tax metadata plus net values."""
    tax_rates: list[float | None] = []
    tax_rule_ids: list[str | None] = []
    tax_rule_versions: list[str | None] = []
    issues: list[QualityIssue] = []

    for row_number, row in enumerate(frame.to_dicts()):
        matches = [rule for rule in rules if rule.applies_to(row, context)]
        trace = _trace(row, row_number)
        if not matches:
            issues.append(QualityIssue("no_matching_tax_rule", "FATAL", 1, (trace,), "No matching tax rule."))
            tax_rates.append(None)
            tax_rule_ids.append(None)
            tax_rule_versions.append(None)
            continue
        if len(matches) > 1:
            issues.append(QualityIssue("multiple_matching_tax_rules", "FATAL", 1, (trace,), "Multiple tax rules match row."))
            tax_rates.append(None)
            tax_rule_ids.append(None)
            tax_rule_versions.append(None)
            continue
        rule = matches[0]
        if rule.rate is None or not 0 <= rule.rate < 1:
            issues.append(QualityIssue("invalid_tax_rate", "FATAL", 1, (trace,), "Tax rate must be >= 0 and < 1."))
            tax_rates.append(None)
            tax_rule_ids.append(rule.rule_id)
            tax_rule_versions.append(rule.rule_version)
            continue
        tax_rates.append(rule.rate)
        tax_rule_ids.append(rule.rule_id)
        tax_rule_versions.append(rule.rule_version)

    enriched = frame.with_columns(
        pl.Series("tax_rate", tax_rates, dtype=pl.Float64),
        pl.Series("tax_rule_id", tax_rule_ids, dtype=pl.String),
        pl.Series("tax_rule_version", tax_rule_versions, dtype=pl.String),
    )
    enriched = enriched.with_columns(
        (pl.col("revenue_vat") / (1 + pl.col("tax_rate"))).alias("revenue_net"),
        (
            (pl.col("shelf_price_vat") / (1 + pl.col("tax_rate"))).alias("shelf_price_net")
            if "shelf_price_vat" in enriched.columns
            else pl.lit(None, dtype=pl.Float64).alias("shelf_price_net")
        ),
        (
            (pl.col("input_price_vat") / (1 + pl.col("tax_rate"))).alias("input_price_net")
            if "input_price_vat" in enriched.columns
            else pl.lit(None, dtype=pl.Float64).alias("input_price_net")
        ),
    )
    return TaxNormalizationResult(enriched, QualityReport(tuple(issues)), _config_hash(rules))


def _parse_required_date(value: Any, *, field_name: str) -> date | None:
    if value is None:
        return None
    return _parse_optional_date(value, field_name=field_name)


def _parse_optional_date(value: Any, *, field_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_rate(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _config_issue(message: str, field: str | None = None) -> QualityIssue:
    return QualityIssue("invalid_tax_rule_config", "FATAL", 1, (), message, field)


def _config_hash(rules: Sequence[TaxRule]) -> str:
    payload = [
        {
            "rule_id": rule.rule_id,
            "valid_from": rule.valid_from.isoformat(),
            "valid_to": rule.valid_to.isoformat() if rule.valid_to else None,
            "rate": rule.rate,
            "match": rule.match,
            "rule_version": rule.rule_version,
            "retailer_id": rule.retailer_id,
            "source_id": rule.source_id,
        }
        for rule in rules
    ]
    normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _trace(row: dict[str, Any], fallback: int) -> int:
    value = row.get("source_row_number")
    return int(value) if isinstance(value, int) else fallback
