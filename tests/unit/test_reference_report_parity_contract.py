from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from retail_analytics.core.audit.reference_report_parity import (
    PARITY_STATUSES,
    reference_report_evidence_can_authorize_semantics,
    requires_reference_report_parity_review,
    validate_parity_statuses,
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


def test_duplicate_or_unknown_parity_statuses_fail_validation() -> None:
    with pytest.raises(ValueError, match="duplicate parity status"):
        validate_parity_statuses(["EXACT_PARITY", "EXACT_PARITY"])

    with pytest.raises(ValueError, match="unsupported parity status"):
        validate_parity_statuses(["EXACT_PARITY", "LAYOUT_MATCH"])


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


def test_no_registered_reference_report_disables_parity_gate() -> None:
    change = {"change_types": ["abc"], "affected_parity_concepts": ["abc_class"]}

    assert not requires_reference_report_parity_review(
        change,
        private_reference_report_registered=False,
    )


def test_reference_report_evidence_cannot_override_business_rule_authority() -> None:
    contract = _contract()
    for semantic_subject in (
        "formulas",
        "thresholds",
        "labels",
        "classifications",
        "vpo semantics",
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


def test_public_contract_preserves_analytical_not_layout_parity() -> None:
    contract = _contract()

    assert contract["parity_rule"]["analytical_content_parity_required"] is True
    assert contract["parity_rule"]["layout_parity_required"] is False
    assert contract["excel_authority_boundary"]["role"] == "evidence_of_business_usage"
    assert contract["excel_authority_boundary"]["not_executable_calculation_authority"] is True


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
