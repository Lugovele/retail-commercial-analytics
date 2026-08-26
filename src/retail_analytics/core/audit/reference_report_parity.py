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

PLACEMENT_ORIGINS = (
    "XLSX",
    "XLSX→WEB",
    "WEB-DERIVED",
    "WEB-AUDIT",
    "XLSX-UNRESOLVED",
)

PLACEMENT_IMPLEMENTATION_STATUSES = (
    "VISIBLE",
    "BACKEND_READY",
    "BACKEND_ONLY",
    "PARTIAL",
    "GAP",
    "UNRESOLVED",
    "NOT_APPLICABLE",
)

PLACEMENT_REPRESENTATION_TYPES = (
    "TOP_KPI",
    "TREND",
    "DRIVER_MATRIX",
    "RANKED_DECISION_ROW",
    "CONTRIBUTION_BLOCK",
    "SHARE_TRACK",
    "CUMULATIVE_MARKER",
    "ABC_CHIP",
    "COMPARISON_STRIP",
    "DETAIL_TABLE",
    "AVAILABILITY_GRID",
    "QUALITY_SUMMARY",
    "METRIC_INSPECTOR",
    "LIMITATION_STATE",
)

PLACEMENT_STATUS_SET = frozenset(PLACEMENT_IMPLEMENTATION_STATUSES)
PLACEMENT_ORIGIN_SET = frozenset(PLACEMENT_ORIGINS)
PLACEMENT_REPRESENTATION_SET = frozenset(PLACEMENT_REPRESENTATION_TYPES)

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

PLACEMENT_IMPACT_CHANGE_TYPES = frozenset(
    {
        "dashboard_ui",
        "dashboard_screen_capability",
        "metric_presentation",
        "metric_placement",
        "excel_parity",
        "portfolio",
        "sales_drivers",
        "stores",
        "signals",
        "data",
        "overview",
        "table_capability",
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


def validate_placement_statuses(statuses: Iterable[str]) -> None:
    """Raise ValueError when placement implementation statuses are invalid."""

    _validate_unique_known_values(
        statuses,
        allowed=PLACEMENT_STATUS_SET,
        duplicate_label="duplicate placement status",
        unknown_label="unsupported placement status",
    )


def validate_placement_origins(origins: Iterable[str]) -> None:
    """Raise ValueError when placement origin values are invalid."""

    _validate_unique_known_values(
        origins,
        allowed=PLACEMENT_ORIGIN_SET,
        duplicate_label="duplicate placement origin",
        unknown_label="unsupported placement origin",
    )


def validate_placement_representations(representations: Iterable[str]) -> None:
    """Raise ValueError when representation values are invalid."""

    _validate_unique_known_values(
        representations,
        allowed=PLACEMENT_REPRESENTATION_SET,
        duplicate_label="duplicate placement representation",
        unknown_label="unsupported placement representation",
    )


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


def requires_dashboard_placement_review(
    change: Mapping[str, object],
    *,
    private_placement_contract_registered: bool,
) -> bool:
    """Return whether dashboard UI/parity work must consult placement and visual contracts."""

    if not private_placement_contract_registered:
        return False

    change_types = set(_string_list(change.get("change_types")))
    if change_types and change_types <= VISUAL_ONLY_CHANGE_TYPES:
        return False

    return bool(
        change_types & PLACEMENT_IMPACT_CHANGE_TYPES
        or _string_list(change.get("affected_concepts"))
        or change.get("changes_primary_home") is True
        or change.get("changes_representation") is True
        or change.get("changes_visual_semantics") is True
        or change.get("cosmetic_label_only") is True
    )


def placement_origin_can_claim_legacy_excel_kpi(origin: str) -> bool:
    """Only direct or generalized Excel origins may be described as legacy Excel content."""

    return origin in {"XLSX", "XLSX→WEB", "XLSX-UNRESOLVED"}


def placement_status_can_satisfy_visible_parity(
    *,
    status: str,
    semantics_approved: bool,
    backend_ready: bool,
    browser_visible: bool,
    correct_scope: bool,
    representation_answers_business_question: bool,
) -> bool:
    """Visible parity requires semantic, backend, rendered, scope and representation evidence."""

    return (
        status == "VISIBLE"
        and semantics_approved
        and backend_ready
        and browser_visible
        and correct_scope
        and representation_answers_business_question
    )


def cosmetic_change_alone_can_complete_parity(change: Mapping[str, object]) -> bool:
    """Labels, headings, duplicated values and text-only changes never complete analytical parity."""

    _ = change
    return False


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


def _validate_unique_known_values(
    values: Iterable[str],
    *,
    allowed: frozenset[str],
    duplicate_label: str,
    unknown_label: str,
) -> None:
    value_list = list(values)
    duplicates = sorted({value for value in value_list if value_list.count(value) > 1})
    if duplicates:
        raise ValueError(f"{duplicate_label} values: {duplicates}")

    unknown = sorted(set(value_list) - allowed)
    if unknown:
        raise ValueError(f"{unknown_label} values: {unknown}")
