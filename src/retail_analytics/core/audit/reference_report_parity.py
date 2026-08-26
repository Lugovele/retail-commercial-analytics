"""Retailer-neutral reference report parity governance helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

PARITY_STATUSES = (
    "EXACT_PARITY",
    "PARTIAL_PARITY",
    "BACKEND_READY_UI_MISSING",
    "BACKEND_MISSING",
    "SEMANTIC_RECONCILIATION_REQUIRED",
    "BUSINESS_RULE_REQUIRED",
    "SOURCE_MAPPING_REQUIRED",
    "NOT_APPLICABLE",
    "INTENTIONALLY_IMPROVED_PRESENTATION",
)

PARITY_STATUS_SET = frozenset(PARITY_STATUSES)

PARITY_IMPACT_CHANGE_TYPES = frozenset(
    {
        "metric_addition",
        "metric_removal",
        "metric_semantics",
        "comparison_semantics",
        "dashboard_screen_capability",
        "filter_dimension",
        "portfolio",
        "sales_drivers",
        "table_capability",
        "ranking",
        "share",
        "abc",
        "metric_inspector_definition",
    }
)

VISUAL_ONLY_CHANGE_TYPES = frozenset(
    {
        "css_only",
        "spacing_only",
        "color_token_only",
        "typography_only",
        "visual_polish_only",
    }
)

AUTHORITY_BOUNDARY_FORBIDDEN_SEMANTICS = frozenset(
    {
        "formulas",
        "thresholds",
        "labels",
        "classifications",
        "private_alias_semantics",
        "distribution_semantics",
        "ranking_universe",
        "abc_formula",
        "averaging_rules",
        "causal_claims",
    }
)

AUTHORITY_BOUNDARY_ALLOWED_EVIDENCE = frozenset(
    {
        "existing_business_analytical_content",
        "familiar_business_terminology",
        "existing_comparison_patterns",
        "expected_analytical_dimensions",
        "parity_acceptance_evidence",
    }
)


def validate_parity_statuses(statuses: Iterable[str]) -> None:
    """Raise ValueError when a configured parity vocabulary is invalid."""

    status_list = list(statuses)
    duplicate_statuses = sorted({status for status in status_list if status_list.count(status) > 1})
    if duplicate_statuses:
        raise ValueError(f"duplicate parity status values: {duplicate_statuses}")

    unknown_statuses = sorted(set(status_list) - PARITY_STATUS_SET)
    if unknown_statuses:
        raise ValueError(f"unsupported parity status values: {unknown_statuses}")


def requires_reference_report_parity_review(
    change: Mapping[str, object],
    *,
    private_reference_report_registered: bool,
) -> bool:
    """Return whether a change needs parity-impact consideration."""

    if not private_reference_report_registered:
        return False

    change_types = set(_string_list(change.get("change_types")))
    if change_types and change_types <= VISUAL_ONLY_CHANGE_TYPES:
        return False

    if change_types & PARITY_IMPACT_CHANGE_TYPES:
        return True

    affected_concepts = _string_list(change.get("affected_parity_concepts"))
    removes_analytical_access = change.get("removes_or_degrades_analytical_access") is True
    reinterprets_semantics = change.get("introduces_or_reinterprets_semantics") is True
    unresolved_gap = change.get("parity_gap_intentionally_unresolved") is True

    return bool(
        affected_concepts
        or removes_analytical_access
        or reinterprets_semantics
        or unresolved_gap
    )


def reference_report_evidence_can_authorize_semantics(semantic_subject: str) -> bool:
    """Reference report evidence never authorizes production calculation semantics."""

    normalized = semantic_subject.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in AUTHORITY_BOUNDARY_FORBIDDEN_SEMANTICS:
        return False
    return normalized in AUTHORITY_BOUNDARY_ALLOWED_EVIDENCE


def _string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(item for item in value if isinstance(item, str))
    return ()
