"""Dashboard metric catalog contracts and validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from retail_analytics.mart.metric_facts import RangeAggregationStrategy
from retail_analytics.mart.scopes import PrivateLabelScope


class MetricFormat(StrEnum):
    """Presentation format hints for dashboard clients."""

    CURRENCY = "currency"
    INTEGER = "integer"
    DECIMAL = "decimal"
    PERCENT = "percent"
    PERCENTAGE_POINTS = "percentage_points"
    RATIO = "ratio"
    TEXT = "text"


class DashboardGroup(StrEnum):
    """Generic dashboard grouping metadata."""

    SALES = "sales"
    ECONOMICS = "economics"
    DISTRIBUTION = "distribution"
    PRICE = "price"
    SHARE = "share"
    ASSORTMENT = "assortment"
    COMPETITION = "competition"
    QUALITY = "quality"


class MetricAvailabilityStatus(StrEnum):
    """Resolved catalog availability for a retailer/source metric definition."""

    READY = "READY"
    PARTIAL = "PARTIAL"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CatalogIssueSeverity(StrEnum):
    """Structured catalog validation severity."""

    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class CatalogValidationIssue:
    """Structured catalog validation issue."""

    issue_code: str
    severity: CatalogIssueSeverity
    message: str
    metric_concept: str | None = None
    metric_definition_id: str | None = None


@dataclass(frozen=True)
class PublicMetricCatalogEntry:
    """Publication-safe generic metric metadata."""

    metric_concept: str
    default_display_label: str
    description: str
    format: MetricFormat
    dashboard_group: DashboardGroup
    default_range_aggregation_strategy: RangeAggregationStrategy
    default_comparison_support: tuple[str, ...] = ("NONE",)
    generic_limitations: tuple[str, ...] = ()
    private_label_scope_support: tuple[PrivateLabelScope, ...] = ()
    business_question: str = ""
    decision_use: str = ""
    formula_summary: str = ""
    delta_semantics: str = "NEUTRAL_DIRECTIONAL"


@dataclass(frozen=True)
class PrivateMetricCatalogOverride:
    """Retailer/source scoped metric metadata override."""

    retailer_id: str
    source_id: str | None
    metric_definition_id: str
    metric_definition_version: str
    metric_concept: str
    display_label: str | None = None
    description_override: str | None = None
    format_override: MetricFormat | None = None
    grain_support: tuple[str, ...] = ()
    period_support: tuple[str, ...] = ()
    comparison_support: tuple[str, ...] = ()
    range_aggregation_strategy: RangeAggregationStrategy | None = None
    share_scope: str | None = None
    semantic_definition_ref: str | None = None
    semantic_family: str | None = None
    semantic_compatibility_version: str | None = None
    cross_retailer_comparable: bool = False
    availability_status: MetricAvailabilityStatus = MetricAvailabilityStatus.READY
    limitations: tuple[str, ...] = ()
    rule_version: str | None = None
    metric_config_hash: str | None = None
    private_label_scope_support: tuple[PrivateLabelScope, ...] = ()

    @property
    def identity_key(self) -> tuple[str, str | None, str, str, str | None, str | None]:
        """Return the private semantic identity key for override merging."""

        return (
            self.retailer_id,
            self.source_id,
            self.metric_definition_id,
            self.metric_definition_version,
            self.rule_version,
            self.metric_config_hash,
        )


@dataclass(frozen=True)
class EffectiveMetricCatalogEntry:
    """Merged dashboard-ready metric catalog entry."""

    retailer_id: str
    source_id: str | None
    metric_definition_id: str
    metric_definition_version: str
    metric_concept: str
    display_label: str
    description: str
    format: MetricFormat
    dashboard_group: DashboardGroup
    grain_support: tuple[str, ...]
    period_support: tuple[str, ...]
    comparison_support: tuple[str, ...]
    range_aggregation_strategy: RangeAggregationStrategy
    share_scope: str | None
    semantic_definition_ref: str | None
    semantic_family: str | None
    semantic_compatibility_version: str | None
    cross_retailer_comparable: bool
    availability_status: MetricAvailabilityStatus
    limitations: tuple[str, ...]
    rule_version: str | None
    metric_config_hash: str | None
    private_label_scope_support: tuple[PrivateLabelScope, ...]
    business_question: str
    decision_use: str
    formula_summary: str
    delta_semantics: str
    default_visible: bool = True
    sort_order: int | None = None


SUPPORTED_GRAINS = frozenset({"network", "category", "manufacturer", "brand", "sku", "store"})
SUPPORTED_PERIOD_GRAINS = frozenset({"day", "week", "month", "quarter", "year"})
SUPPORTED_COMPARISONS = frozenset({"NONE", "YOY", "MOM", "PREVIOUS_AVAILABLE"})
DEFAULT_PRIVATE_LABEL_SCOPE_SUPPORT = (
    PrivateLabelScope.INCLUDE,
    PrivateLabelScope.EXCLUDE,
    PrivateLabelScope.ONLY,
)


def load_public_metric_catalog(path: str | Path) -> tuple[PublicMetricCatalogEntry, ...]:
    """Load publication-safe generic catalog metadata from YAML."""

    payload = _read_yaml(path)
    return tuple(_public_entry(row) for row in _iter_entries(payload, "metrics"))


def load_private_metric_catalog_overrides(path: str | Path) -> tuple[PrivateMetricCatalogOverride, ...]:
    """Load retailer/source scoped catalog overrides from YAML."""

    payload = _read_yaml(path)
    return tuple(_private_override(row) for row in _iter_entries(payload, "overrides"))


def merge_metric_catalog(
    public_entries: tuple[PublicMetricCatalogEntry, ...],
    private_overrides: tuple[PrivateMetricCatalogOverride, ...],
    *,
    retailer_id: str,
    source_id: str | None = None,
) -> tuple[EffectiveMetricCatalogEntry, ...]:
    """Merge public defaults with private authoritative availability overrides."""

    issues = validate_metric_catalog(public_entries, private_overrides)
    errors = [issue for issue in issues if issue.severity == CatalogIssueSeverity.ERROR]
    if errors:
        raise ValueError("; ".join(issue.message for issue in errors))

    public_by_concept = {entry.metric_concept: entry for entry in public_entries}
    resolved: list[EffectiveMetricCatalogEntry] = []
    seen: set[tuple[str, str | None, str, str, str | None, str | None]] = set()
    for override in private_overrides:
        if override.retailer_id != retailer_id:
            continue
        if source_id is not None and override.source_id not in (None, source_id):
            continue
        if override.identity_key in seen:
            raise ValueError(f"Duplicate metric catalog override identity: {override.identity_key}")
        seen.add(override.identity_key)
        public = public_by_concept[override.metric_concept]
        resolved.append(_merge_entry(public, override))
    return tuple(sorted(resolved, key=lambda entry: (entry.sort_order is None, entry.sort_order or 0, entry.metric_concept, entry.metric_definition_id)))


def validate_metric_catalog(
    public_entries: tuple[PublicMetricCatalogEntry, ...],
    private_overrides: tuple[PrivateMetricCatalogOverride, ...] = (),
) -> tuple[CatalogValidationIssue, ...]:
    """Validate catalog identity, enum values, and private capability claims."""

    issues: list[CatalogValidationIssue] = []
    concepts: set[str] = set()
    for entry in public_entries:
        if entry.metric_concept in concepts:
            issues.append(
                CatalogValidationIssue(
                    "duplicate_public_metric_concept",
                    CatalogIssueSeverity.ERROR,
                    f"Duplicate public metric_concept: {entry.metric_concept}",
                    metric_concept=entry.metric_concept,
                )
            )
        concepts.add(entry.metric_concept)

    seen_private: set[tuple[str, str | None, str, str, str | None, str | None]] = set()
    public_by_concept = {entry.metric_concept: entry for entry in public_entries}
    for override in private_overrides:
        if override.identity_key in seen_private:
            issues.append(
                CatalogValidationIssue(
                    "duplicate_private_metric_identity",
                    CatalogIssueSeverity.ERROR,
                    f"Duplicate private metric identity: {override.identity_key}",
                    metric_concept=override.metric_concept,
                    metric_definition_id=override.metric_definition_id,
                )
            )
        seen_private.add(override.identity_key)
        public = public_by_concept.get(override.metric_concept)
        if public is None:
            issues.append(
                CatalogValidationIssue(
                    "private_override_unknown_concept",
                    CatalogIssueSeverity.ERROR,
                    f"Private override references unknown metric_concept: {override.metric_concept}",
                    metric_concept=override.metric_concept,
                    metric_definition_id=override.metric_definition_id,
                )
            )
            continue
        issues.extend(_validate_override_capabilities(public, override))
    return tuple(issues)


def catalog_entry_for_fact(
    catalog: tuple[EffectiveMetricCatalogEntry, ...],
    *,
    retailer_id: str | None = None,
    source_id: str | None = None,
    metric_definition_id: str,
    metric_definition_version: str,
    metric_config_hash: str | None,
    rule_version: str | None,
) -> EffectiveMetricCatalogEntry | None:
    """Find the effective catalog entry matching a mart fact identity."""

    matches = [
        entry
        for entry in catalog
        if (retailer_id is None or entry.retailer_id == retailer_id)
        and (source_id is None or entry.source_id in (None, source_id))
        and entry.metric_definition_id == metric_definition_id
        and entry.metric_definition_version == metric_definition_version
        and (entry.metric_config_hash is None or entry.metric_config_hash == metric_config_hash)
        and (entry.rule_version is None or entry.rule_version == rule_version)
    ]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous catalog entries for metric_definition_id={metric_definition_id}")
    return matches[0] if matches else None


def _merge_entry(
    public: PublicMetricCatalogEntry,
    override: PrivateMetricCatalogOverride,
) -> EffectiveMetricCatalogEntry:
    limitations = (*public.generic_limitations, *override.limitations)
    return EffectiveMetricCatalogEntry(
        retailer_id=override.retailer_id,
        source_id=override.source_id,
        metric_definition_id=override.metric_definition_id,
        metric_definition_version=override.metric_definition_version,
        metric_concept=override.metric_concept,
        display_label=override.display_label or public.default_display_label,
        description=override.description_override or public.description,
        format=override.format_override or public.format,
        dashboard_group=public.dashboard_group,
        grain_support=override.grain_support,
        period_support=override.period_support,
        comparison_support=override.comparison_support or public.default_comparison_support,
        range_aggregation_strategy=override.range_aggregation_strategy
        or public.default_range_aggregation_strategy,
        share_scope=override.share_scope,
        semantic_definition_ref=override.semantic_definition_ref,
        semantic_family=override.semantic_family,
        semantic_compatibility_version=override.semantic_compatibility_version,
        cross_retailer_comparable=override.cross_retailer_comparable,
        availability_status=override.availability_status,
        limitations=limitations,
        rule_version=override.rule_version,
        metric_config_hash=override.metric_config_hash,
        private_label_scope_support=override.private_label_scope_support
        or public.private_label_scope_support,
        business_question=public.business_question,
        decision_use=public.decision_use,
        formula_summary=public.formula_summary,
        delta_semantics=public.delta_semantics,
    )


def _validate_override_capabilities(
    public: PublicMetricCatalogEntry,
    override: PrivateMetricCatalogOverride,
) -> tuple[CatalogValidationIssue, ...]:
    issues: list[CatalogValidationIssue] = []
    unknown_grains = sorted(set(override.grain_support) - SUPPORTED_GRAINS)
    if unknown_grains:
        issues.append(
            CatalogValidationIssue(
                "unknown_grain",
                CatalogIssueSeverity.ERROR,
                f"Unsupported grain_support values: {unknown_grains}",
                metric_concept=override.metric_concept,
                metric_definition_id=override.metric_definition_id,
            )
        )
    unknown_periods = sorted(set(override.period_support) - SUPPORTED_PERIOD_GRAINS)
    if unknown_periods:
        issues.append(
            CatalogValidationIssue(
                "unknown_period_grain",
                CatalogIssueSeverity.ERROR,
                f"Unsupported period_support values: {unknown_periods}",
                metric_concept=override.metric_concept,
                metric_definition_id=override.metric_definition_id,
            )
        )
    unknown_comparisons = sorted(set(override.comparison_support) - SUPPORTED_COMPARISONS)
    if unknown_comparisons:
        issues.append(
            CatalogValidationIssue(
                "unsupported_comparison_mode",
                CatalogIssueSeverity.ERROR,
                f"Unsupported comparison_support values: {unknown_comparisons}",
                metric_concept=override.metric_concept,
                metric_definition_id=override.metric_definition_id,
            )
        )
    strategy = override.range_aggregation_strategy
    if strategy is not None and _expands_period_only_strategy(public, override):
        issues.append(
            CatalogValidationIssue(
                "private_override_claims_unsupported_range_capability",
                CatalogIssueSeverity.ERROR,
                "Private override cannot expand a public PERIOD_ONLY or UNSUPPORTED range strategy",
                metric_concept=override.metric_concept,
                metric_definition_id=override.metric_definition_id,
            )
        )
    return tuple(issues)


def _expands_period_only_strategy(
    public: PublicMetricCatalogEntry,
    override: PrivateMetricCatalogOverride,
) -> bool:
    public_strategy = public.default_range_aggregation_strategy
    private_strategy = override.range_aggregation_strategy
    if private_strategy is None:
        return False
    concept = override.metric_concept.lower()
    if concept.endswith("_share") and private_strategy == RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE:
        return override.share_scope is None
    if any(marker in concept for marker in ("distribution", "velocity", "abc")):
        return public_strategy != private_strategy
    limited = {RangeAggregationStrategy.PERIOD_ONLY, RangeAggregationStrategy.UNSUPPORTED}
    return public_strategy in limited and private_strategy not in limited


def _public_entry(row: dict[str, Any]) -> PublicMetricCatalogEntry:
    return PublicMetricCatalogEntry(
        metric_concept=str(row["metric_concept"]),
        default_display_label=str(row["default_display_label"]),
        description=str(row.get("description") or ""),
        format=MetricFormat(str(row["format"])),
        dashboard_group=DashboardGroup(str(row["dashboard_group"])),
        default_range_aggregation_strategy=RangeAggregationStrategy(
            str(row["default_range_aggregation_strategy"])
        ),
        default_comparison_support=tuple(row.get("default_comparison_support") or ("NONE",)),
        generic_limitations=tuple(row.get("generic_limitations") or ()),
        private_label_scope_support=_private_label_scope_tuple(
            row.get("private_label_scope_support") or DEFAULT_PRIVATE_LABEL_SCOPE_SUPPORT
        ),
        business_question=str(row.get("business_question") or ""),
        decision_use=str(row.get("decision_use") or ""),
        formula_summary=str(row.get("formula_summary") or ""),
        delta_semantics=str(row.get("delta_semantics") or "NEUTRAL_DIRECTIONAL"),
    )


def _private_override(row: dict[str, Any]) -> PrivateMetricCatalogOverride:
    return PrivateMetricCatalogOverride(
        retailer_id=str(row["retailer_id"]),
        source_id=_optional_str(row.get("source_id")),
        metric_definition_id=str(row["metric_definition_id"]),
        metric_definition_version=str(row["metric_definition_version"]),
        metric_concept=str(row["metric_concept"]),
        display_label=_optional_str(row.get("display_label")),
        description_override=_optional_str(row.get("description_override")),
        format_override=MetricFormat(str(row["format_override"])) if row.get("format_override") else None,
        grain_support=tuple(row.get("grain_support") or ()),
        period_support=tuple(row.get("period_support") or ()),
        comparison_support=tuple(row.get("comparison_support") or ()),
        range_aggregation_strategy=RangeAggregationStrategy(str(row["range_aggregation_strategy"]))
        if row.get("range_aggregation_strategy")
        else None,
        share_scope=_optional_str(row.get("share_scope")),
        semantic_definition_ref=_optional_str(row.get("semantic_definition_ref")),
        semantic_family=_optional_str(row.get("semantic_family")),
        semantic_compatibility_version=_optional_str(row.get("semantic_compatibility_version")),
        cross_retailer_comparable=bool(row.get("cross_retailer_comparable", False)),
        availability_status=MetricAvailabilityStatus(
            str(row.get("availability_status") or MetricAvailabilityStatus.READY)
        ),
        limitations=tuple(row.get("limitations") or ()),
        rule_version=_optional_str(row.get("rule_version")),
        metric_config_hash=_optional_str(row.get("metric_config_hash")),
        private_label_scope_support=_private_label_scope_tuple(row.get("private_label_scope_support")),
    )


def _private_label_scope_tuple(values: object) -> tuple[PrivateLabelScope, ...]:
    raw_values: tuple[object, ...]
    if isinstance(values, str):
        raw_values = (values,)
    elif isinstance(values, Iterable):
        raw_values = tuple(values)
    else:
        raw_values = ()
    return tuple(PrivateLabelScope(str(value)) for value in raw_values)


def _iter_entries(payload: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    raw = payload.get(key) or ()
    if isinstance(raw, dict):
        return tuple({"metric_concept": name, **value} for name, value in raw.items())
    return tuple(raw)


def _read_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise TypeError(f"Catalog YAML must contain a mapping: {path}")
    return payload


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
