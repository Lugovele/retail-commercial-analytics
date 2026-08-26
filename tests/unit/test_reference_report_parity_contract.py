from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from retail_analytics.core.audit.reference_report_parity import (
    PARITY_STATUSES,
    PLACEMENT_IMPLEMENTATION_STATUSES,
    PLACEMENT_ORIGINS,
    PLACEMENT_REPRESENTATION_TYPES,
    cosmetic_change_alone_can_complete_parity,
    placement_origin_can_claim_legacy_excel_kpi,
    placement_status_can_satisfy_visible_parity,
    reference_report_evidence_can_authorize_semantics,
    requires_dashboard_placement_review,
    requires_reference_report_parity_review,
    validate_parity_statuses,
    validate_placement_origins,
    validate_placement_representations,
    validate_placement_statuses,
)

CONTRACT_PATH = Path("config/public/reference_report_parity_contract.yaml")
LIFECYCLE_SCHEMA_PATH = Path("config/public/review_lifecycle_evidence_schema.yaml")
PRIVATE_REGISTRY_PATH = Path("config/private/reference_reports.yaml")
PUBLIC_GOVERNANCE_PATHS = (
    CONTRACT_PATH,
    LIFECYCLE_SCHEMA_PATH,
    Path("docs/public/architecture/reference-report-parity-contract.md"),
    Path("docs/public/architecture/review-lifecycle-evidence.md"),
    Path(".codex/agents/retail-change-lifecycle-orchestrator.toml"),
    Path(".codex/agents/retail-change-reviewer.toml"),
    Path(".codex/agents/retail-architecture-reviewer.toml"),
    Path(".codex/agents/retail-business-rules-reviewer.toml"),
)


def test_public_contract_uses_authoritative_unique_parity_statuses() -> None:
    contract = _contract()

    configured_statuses = contract["parity_statuses"]

    assert configured_statuses == list(PARITY_STATUSES)
    validate_parity_statuses(configured_statuses)


def test_public_contract_uses_authoritative_dashboard_placement_vocabularies() -> None:
    placement = _contract()["dashboard_metric_placement_governance"]

    assert placement["origin_taxonomy"] == list(PLACEMENT_ORIGINS)
    assert placement["implementation_statuses"] == list(PLACEMENT_IMPLEMENTATION_STATUSES)
    assert placement["representation_types"] == list(PLACEMENT_REPRESENTATION_TYPES)
    validate_placement_origins(placement["origin_taxonomy"])
    validate_placement_statuses(placement["implementation_statuses"])
    validate_placement_representations(placement["representation_types"])


def test_duplicate_or_unknown_parity_statuses_fail_validation() -> None:
    with pytest.raises(ValueError, match="duplicate parity status"):
        validate_parity_statuses(["EXACT_PARITY", "EXACT_PARITY"])

    with pytest.raises(ValueError, match="unsupported parity status"):
        validate_parity_statuses(["EXACT_PARITY", "LAYOUT_MATCH"])


def test_duplicate_or_unknown_dashboard_placement_vocabularies_fail_validation() -> None:
    with pytest.raises(ValueError, match="duplicate placement origin"):
        validate_placement_origins(["XLSX", "XLSX"])
    with pytest.raises(ValueError, match="unsupported placement status"):
        validate_placement_statuses(["VISIBLE", "DONE"])
    with pytest.raises(ValueError, match="unsupported placement representation"):
        validate_placement_representations(["TOP_KPI", "ANOTHER_COLUMN"])


def test_public_governance_contains_no_private_reference_identifiers() -> None:
    forbidden_terms = _private_reference_terms()

    for path in PUBLIC_GOVERNANCE_PATHS:
        text = path.read_text(encoding="utf-8").lower()
        leaked = [term for term in forbidden_terms if term in text]
        assert leaked == [], f"{path} leaks private reference identifiers"


def test_private_reference_registry_path_is_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", PRIVATE_REGISTRY_PATH.as_posix()],
        check=False,
    )

    assert result.returncode == 0


def test_private_registry_registers_metric_placement_and_visual_contracts() -> None:
    registry = yaml.safe_load(PRIVATE_REGISTRY_PATH.read_text(encoding="utf-8"))

    report = registry["reference_reports"][0]
    artifacts = report["contract_artifacts"]

    assert artifacts["metric_placement_contract"]["status"] == "registered_private_contract"
    assert artifacts["visual_semantics_contract"]["status"] == "registered_private_contract"
    assert "meaningful_dashboard_ui_work" in artifacts["metric_placement_contract"]["mandatory_for"]
    assert "rendered_visual_acceptance" in artifacts["visual_semantics_contract"]["mandatory_for"]


def test_private_placement_contract_uses_public_origin_taxonomy() -> None:
    registry = yaml.safe_load(PRIVATE_REGISTRY_PATH.read_text(encoding="utf-8"))
    contract_path = Path(registry["reference_reports"][0]["contract_artifacts"]["metric_placement_contract"]["path"])
    text = contract_path.read_text(encoding="utf-8")
    origins: set[str] = set()
    origin_table_active = False
    for line in text.splitlines():
        if not line.startswith("|"):
            origin_table_active = False
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[1] in {"Origin", "Происхождение"}:
            origin_table_active = True
            continue
        if line.startswith("|---") or not origin_table_active or len(cells) < 2:
            continue
        origin = cells[1]
        if origin:
            origins.add(origin)

    assert origins <= set(PLACEMENT_ORIGINS)


def test_semantic_dashboard_changes_require_parity_impact_consideration() -> None:
    change = {
        "change_types": ["metric_removal", "dashboard_screen_capability"],
        "affected_parity_concepts": ["manufacturer_rank"],
    }

    assert requires_reference_report_parity_review(
        change,
        private_reference_report_registered=True,
    )


def test_trivial_visual_only_changes_do_not_require_full_workbook_reaudit() -> None:
    change = {"change_types": ["css_only", "spacing_only"]}

    assert not requires_reference_report_parity_review(
        change,
        private_reference_report_registered=True,
    )


def test_meaningful_dashboard_ui_changes_require_placement_and_visual_review() -> None:
    change = {
        "change_types": ["dashboard_ui", "metric_presentation"],
        "affected_concepts": ["manufacturer_share"],
    }

    assert requires_dashboard_placement_review(
        change,
        private_placement_contract_registered=True,
    )


def test_trivial_css_changes_do_not_require_placement_contract_review() -> None:
    change = {"change_types": ["css_only", "typography_only"]}

    assert not requires_dashboard_placement_review(
        change,
        private_placement_contract_registered=True,
    )


def test_cosmetic_label_parity_work_still_requires_placement_contract_review() -> None:
    change = {"change_types": ["excel_parity"], "cosmetic_label_only": True}

    assert requires_dashboard_placement_review(
        change,
        private_placement_contract_registered=True,
    )


def test_no_registered_reference_report_disables_parity_gate() -> None:
    change = {"change_types": ["abc"], "affected_parity_concepts": ["abc_class"]}

    assert not requires_reference_report_parity_review(
        change,
        private_reference_report_registered=False,
    )


def test_no_registered_placement_contract_disables_placement_gate() -> None:
    change = {"change_types": ["dashboard_ui"], "affected_concepts": ["abc_class"]}

    assert not requires_dashboard_placement_review(
        change,
        private_placement_contract_registered=False,
    )


def test_web_derived_and_web_audit_concepts_cannot_masquerade_as_excel_kpis() -> None:
    assert not placement_origin_can_claim_legacy_excel_kpi("WEB-DERIVED")
    assert not placement_origin_can_claim_legacy_excel_kpi("WEB-AUDIT")
    assert placement_origin_can_claim_legacy_excel_kpi("XLSX")
    assert placement_origin_can_claim_legacy_excel_kpi("XLSX→WEB")


def test_xlsx_unresolved_and_backend_ready_do_not_satisfy_visible_parity() -> None:
    assert not placement_status_can_satisfy_visible_parity(
        status="UNRESOLVED",
        semantics_approved=False,
        backend_ready=False,
        browser_visible=True,
        correct_scope=True,
        representation_answers_business_question=True,
    )
    assert not placement_status_can_satisfy_visible_parity(
        status="BACKEND_READY",
        semantics_approved=True,
        backend_ready=True,
        browser_visible=False,
        correct_scope=True,
        representation_answers_business_question=True,
    )
    assert placement_status_can_satisfy_visible_parity(
        status="VISIBLE",
        semantics_approved=True,
        backend_ready=True,
        browser_visible=True,
        correct_scope=True,
        representation_answers_business_question=True,
    )


def test_cosmetic_label_changes_cannot_complete_parity() -> None:
    assert not cosmetic_change_alone_can_complete_parity({"label_repeated": True})
    assert not cosmetic_change_alone_can_complete_parity({"heading_added": True})
    assert not cosmetic_change_alone_can_complete_parity({"existing_value_duplicated": True})
    assert not cosmetic_change_alone_can_complete_parity({"tiny_badge_added": True})
    assert not cosmetic_change_alone_can_complete_parity({"explanatory_text_only": True})
    assert not cosmetic_change_alone_can_complete_parity({"query_support_added": True})


def test_reference_report_evidence_cannot_override_business_rule_authority() -> None:
    contract = _contract()
    for semantic_subject in (
        "formulas",
        "thresholds",
        "labels",
        "classifications",
        "private alias semantics",
        "distribution semantics",
        "ranking universe",
        "abc formula",
        "averaging rules",
        "causal claims",
        *contract["not_authoritative_for"],
    ):
        assert not reference_report_evidence_can_authorize_semantics(semantic_subject)


def test_reference_report_evidence_only_authorizes_explicit_evidence_roles() -> None:
    for evidence_role in _contract()["evidence_for"]:
        assert reference_report_evidence_can_authorize_semantics(evidence_role)

    assert not reference_report_evidence_can_authorize_semantics("production calculation logic")
    assert not reference_report_evidence_can_authorize_semantics("technical architecture")
    assert not reference_report_evidence_can_authorize_semantics("unsupported semantic assumptions")


def test_lifecycle_schema_references_parity_contract_for_conditional_gate() -> None:
    schema = yaml.safe_load(LIFECYCLE_SCHEMA_PATH.read_text(encoding="utf-8"))[
        "review_lifecycle_evidence_schema"
    ]

    parity = schema["reference_report_parity"]

    assert parity["contract_path"] == CONTRACT_PATH.as_posix()
    assert parity["applies_to_meaningful_analytical_or_product_semantic_changes"] is True
    assert parity["full_reference_audit_required_for_visual_only_changes"] is False
    assert "private_reference_report_registered" in schema["optional_reference_report_parity_fields"]
    assert parity["private_metric_placement_contract_required_for_meaningful_ui_parity"] is True
    assert parity["private_visual_semantics_contract_required_after_placement_review"] is True
    assert parity["backend_ready_is_not_visible_parity"] is True
    assert parity["cosmetic_label_change_satisfies_parity"] is False
    assert "pre_code_design_table_completed" in schema["optional_reference_report_parity_fields"]
    assert "post_code_parity_table_completed" in schema["optional_reference_report_parity_fields"]


def test_public_contract_preserves_analytical_not_layout_parity() -> None:
    contract = _contract()

    assert contract["parity_rule"]["analytical_content_parity_required"] is True
    assert contract["parity_rule"]["layout_parity_required"] is False
    assert contract["excel_authority_boundary"]["role"] == "evidence_of_business_usage"
    assert contract["excel_authority_boundary"]["not_executable_calculation_authority"] is True


def test_public_contract_preserves_source_of_truth_hierarchy() -> None:
    hierarchy = _contract()["dashboard_metric_placement_governance"]["source_of_truth_hierarchy"]

    assert hierarchy == [
        "deterministic_business_rules_and_metric_definitions",
        "excel_to_web_metric_placement_contract",
        "excel_visual_semantics_to_web_design_contract",
        "public_visualization_screen_and_presentation_policy",
        "current_ui_implementation",
    ]


def _contract() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))[
        "reference_report_parity_contract"
    ]


def _private_reference_terms() -> tuple[str, ...]:
    if not PRIVATE_REGISTRY_PATH.exists():
        return ()

    registry = yaml.safe_load(PRIVATE_REGISTRY_PATH.read_text(encoding="utf-8"))
    terms: set[str] = set()
    for report in registry["reference_reports"]:
        for value in (report["reference_report_id"], Path(report["path"]).name):
            for token in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", str(value).lower()):
                if len(token) > 3 and token not in {"analytics", "excel", "reference", "report", "xlsx"}:
                    terms.add(token)
    return tuple(sorted(terms))
