"""Config-driven tax semantic classification."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import polars as pl

from retail_analytics.quality.report import QualityIssue, QualityReport

_ALLOWED_UNKNOWN_POLICIES = {
    "REVIEW_REQUIRED",
    "REVIEW_REQUIRED_FOR_UNREVIEWED_TAXONOMY_VALUES",
}


@dataclass(frozen=True)
class TaxSemanticRule:
    """Exact source taxonomy mapping to one tax semantic group."""
    output_value: str
    match: dict[str, Any]
    match_type: str


@dataclass(frozen=True)
class TaxSemanticMapping:
    """Retailer-configured taxonomy-to-tax-group mapping contract."""
    mapping_id: str
    mapping_version: str
    source_fields: tuple[str, ...]
    output_field: str
    rules: tuple[TaxSemanticRule, ...]
    scoped_standard_rule: TaxSemanticRule | None
    scope_assertion: str | None
    unknown_policy: str | None
    mapping_hash: str


@dataclass(frozen=True)
class TaxSemanticClassificationResult:
    """Frame plus semantic classification quality and lineage."""
    frame: pl.DataFrame
    quality_report: QualityReport
    mapping_hash: str


def parse_tax_semantic_mapping(payload: dict[str, Any]) -> tuple[TaxSemanticMapping | None, QualityReport]:
    """Parse optional tax semantic mapping from a tax config payload."""
    raw = payload.get("tax_semantic_mapping")
    if raw is None:
        return None, QualityReport()
    if not isinstance(raw, dict):
        return None, QualityReport((_config_issue("Tax semantic mapping must be a mapping."),))

    mapping_id = _non_empty_string(raw.get("mapping_id"))
    mapping_version = _non_empty_string(raw.get("mapping_version", payload.get("rule_version")))
    output_field = _non_empty_string(raw.get("output_field"))
    source_fields = _string_tuple(raw.get("source_fields"))
    issues: list[QualityIssue] = []
    if not mapping_id:
        issues.append(_config_issue("Tax semantic mapping must define mapping_id.", "mapping_id"))
    if not mapping_version:
        issues.append(_config_issue("Tax semantic mapping must define mapping_version.", "mapping_version"))
    if not output_field:
        issues.append(_config_issue("Tax semantic mapping must define output_field.", "output_field"))
    if not source_fields:
        issues.append(_config_issue("Tax semantic mapping must define source_fields.", "source_fields"))
    elif len(set(source_fields)) != len(source_fields):
        issues.append(_config_issue("Tax semantic source_fields must be unique.", "source_fields"))

    unknown_policy = _non_empty_string(raw.get("unknown_future_value_policy"))
    if unknown_policy and unknown_policy not in _ALLOWED_UNKNOWN_POLICIES:
        issues.append(_config_issue("Tax semantic unknown_future_value_policy is not supported.", "unknown_future_value_policy"))

    rules: list[TaxSemanticRule] = []
    for section_name in ("confirmed_reduced_mappings", "confirmed_mappings"):
        raw_rules = raw.get(section_name)
        if raw_rules is None:
            continue
        if not isinstance(raw_rules, list):
            issues.append(_config_issue(f"{section_name} must be a list.", section_name))
            continue
        for raw_rule in raw_rules:
            rule = _parse_mapping_rule(
                raw_rule,
                output_field=output_field,
                source_fields=source_fields,
                match_type="exact",
            )
            if rule is None:
                issues.append(_config_issue(f"{section_name} entry must define {output_field} and match.", section_name))
            else:
                rules.append(rule)

    standard_rule: TaxSemanticRule | None = None
    standard = raw.get("standard_mapping")
    scope_assertion: str | None = None
    if standard is not None:
        if not isinstance(standard, dict):
            issues.append(_config_issue("standard_mapping must be a mapping.", "standard_mapping"))
        else:
            scope_assertion = _non_empty_string(standard.get("scope_assertion"))
            standard_value = _non_empty_string(standard.get(output_field))
            if not standard_value:
                issues.append(_config_issue(f"standard_mapping must define {output_field}.", "standard_mapping"))
            reviewed = standard.get("reviewed_mappings", ())
            if reviewed:
                if not isinstance(reviewed, list):
                    issues.append(_config_issue("standard_mapping.reviewed_mappings must be a list.", "reviewed_mappings"))
                else:
                    for raw_rule in reviewed:
                        rule = _parse_mapping_rule(
                            {output_field: standard_value, "match": raw_rule},
                            output_field=output_field,
                            source_fields=source_fields,
                            match_type="reviewed_standard",
                        )
                        if rule is None:
                            issues.append(_config_issue("Reviewed standard mapping must define exact match values.", "reviewed_mappings"))
                        else:
                            rules.append(rule)
            elif scope_assertion and standard_value:
                standard_rule = TaxSemanticRule(standard_value, {}, "scoped_standard")

    mapping = None
    if not issues:
        mapping = TaxSemanticMapping(
            mapping_id=mapping_id,
            mapping_version=mapping_version,
            source_fields=source_fields,
            output_field=output_field,
            rules=tuple(rules),
            scoped_standard_rule=standard_rule,
            scope_assertion=scope_assertion,
            unknown_policy=unknown_policy,
            mapping_hash=_mapping_hash(
                mapping_id=mapping_id,
                mapping_version=mapping_version,
                source_fields=source_fields,
                output_field=output_field,
                rules=rules,
                scoped_standard_rule=standard_rule,
                scope_assertion=scope_assertion,
                unknown_policy=unknown_policy,
            ),
        )
    return mapping, QualityReport(tuple(issues))


def classify_tax_semantics(frame: pl.DataFrame, mapping: TaxSemanticMapping) -> TaxSemanticClassificationResult:
    """Append tax semantic group and mapping lineage without mutating source rows."""
    output_values: list[str | None] = []
    match_types: list[str | None] = []
    issues: list[QualityIssue] = []

    for row_number, row in enumerate(frame.to_dicts()):
        trace = _trace(row, row_number)
        missing_field = next((field for field in mapping.source_fields if field not in row or row.get(field) is None), None)
        if missing_field is not None:
            issues.append(
                QualityIssue(
                    "missing_tax_semantic_input",
                    "FATAL",
                    1,
                    (trace,),
                    f"Missing tax semantic input field: {missing_field}.",
                    missing_field,
                )
            )
            output_values.append(None)
            match_types.append(None)
            continue

        matches = [rule for rule in mapping.rules if _matches(rule, row)]
        if len(matches) > 1:
            issues.append(
                QualityIssue(
                    "ambiguous_tax_semantic_match",
                    "FATAL",
                    1,
                    (trace,),
                    "Multiple tax semantic mappings match row.",
                    mapping.output_field,
                )
            )
            output_values.append(None)
            match_types.append(None)
            continue
        if matches:
            output_values.append(matches[0].output_value)
            match_types.append(matches[0].match_type)
            continue
        if mapping.scoped_standard_rule is not None:
            output_values.append(mapping.scoped_standard_rule.output_value)
            match_types.append(mapping.scoped_standard_rule.match_type)
            continue
        issues.append(
            QualityIssue(
                "unknown_tax_semantic_key",
                "FATAL",
                1,
                (trace,),
                "No reviewed tax semantic mapping matches row.",
                mapping.output_field,
            )
        )
        output_values.append(None)
        match_types.append(None)

    enriched = frame.with_columns(
        pl.Series(mapping.output_field, output_values, dtype=pl.String),
        pl.lit(mapping.mapping_id).alias("tax_semantic_mapping_id"),
        pl.lit(mapping.mapping_version).alias("tax_semantic_mapping_version"),
        pl.lit(mapping.mapping_hash).alias("tax_semantic_mapping_hash"),
        pl.Series("tax_semantic_match_type", match_types, dtype=pl.String),
    )
    return TaxSemanticClassificationResult(enriched, QualityReport(tuple(issues)), mapping.mapping_hash)


def _parse_mapping_rule(
    raw_rule: Any,
    *,
    output_field: str,
    source_fields: tuple[str, ...],
    match_type: str,
) -> TaxSemanticRule | None:
    if not isinstance(raw_rule, dict):
        return None
    output_value = _non_empty_string(raw_rule.get(output_field))
    raw_match = raw_rule.get("match")
    if not output_value or not isinstance(raw_match, dict) or not raw_match:
        return None
    match = {str(key): value for key, value in raw_match.items()}
    if set(match) != set(source_fields):
        return None
    return TaxSemanticRule(output_value, match, match_type)


def _matches(rule: TaxSemanticRule, row: dict[str, Any]) -> bool:
    return all(row.get(field) == value for field, value in rule.match.items())


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    fields = tuple(str(item).strip() for item in value if isinstance(item, str) and item.strip())
    return fields if len(fields) == len(value) else ()


def _non_empty_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _config_issue(message: str, field: str | None = None) -> QualityIssue:
    return QualityIssue("invalid_tax_semantic_mapping_config", "FATAL", 1, (), message, field)


def _mapping_hash(
    *,
    mapping_id: str,
    mapping_version: str,
    source_fields: tuple[str, ...],
    output_field: str,
    rules: list[TaxSemanticRule],
    scoped_standard_rule: TaxSemanticRule | None,
    scope_assertion: str | None,
    unknown_policy: str,
) -> str:
    payload = {
        "mapping_id": mapping_id,
        "mapping_version": mapping_version,
        "source_fields": source_fields,
        "output_field": output_field,
        "rules": [
            {"output_value": rule.output_value, "match": rule.match, "match_type": rule.match_type}
            for rule in rules
        ],
        "scoped_standard_rule": (
            {
                "output_value": scoped_standard_rule.output_value,
                "match_type": scoped_standard_rule.match_type,
            }
            if scoped_standard_rule is not None
            else None
        ),
        "scope_assertion": scope_assertion,
        "unknown_policy": unknown_policy,
    }
    normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _trace(row: dict[str, Any], fallback: int) -> int:
    value = row.get("source_row_number")
    return int(value) if isinstance(value, int) else fallback
