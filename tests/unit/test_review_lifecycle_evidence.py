from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from retail_analytics.core.audit.review_evidence import (
    SCHEMA_VERSION,
    ReviewEvidence,
    ReviewEvidenceBundle,
    ReviewEvidenceError,
    validate_review_evidence,
    validate_review_evidence_bundle,
)

SCHEMA_PATH = Path("config/public/review_lifecycle_evidence_schema.yaml")


def test_valid_minimal_public_evidence_passes() -> None:
    ReviewEvidence.validate(_evidence_record())


def test_schema_file_matches_validator_contract() -> None:
    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))["review_lifecycle_evidence_schema"]

    assert schema["schema_version"] == SCHEMA_VERSION
    assert set(schema["required_fields"]) <= set(_evidence_record())
    assert "config/private" in schema["privacy_rules"]["forbidden_public_path_markers"]
    assert "private_notes" in schema["privacy_rules"]["forbidden_payload_keys"]


def test_missing_required_fields_fail() -> None:
    record = _evidence_record()
    del record["approval_status"]

    issues = validate_review_evidence(record)

    assert {issue.issue_code for issue in issues} == {"missing_required_fields"}


def test_invalid_reviewer_status_and_severity_fail() -> None:
    record = _evidence_record(
        originating_reviewer="ad_hoc_reviewer",
        reviewer_role="informal",
        review_status="OK",
        approval_status="DONE",
        findings=[
            {
                "finding_id": "OVN-AUD-005",
                "severity": "Warning",
                "status": "FIXED",
                "public_summary": "Reviewer lifecycle evidence was not durable.",
                "affected_public_paths": [".codex/agents/retail-change-lifecycle-orchestrator.toml"],
                "requires_private_followup": False,
            }
        ],
    )

    issue_codes = {issue.issue_code for issue in validate_review_evidence(record)}

    assert "invalid_originating_reviewer" in issue_codes
    assert "invalid_reviewer_role" in issue_codes
    assert "invalid_review_status" in issue_codes
    assert "invalid_approval_status" in issue_codes
    assert "invalid_finding_severity" in issue_codes
    assert "invalid_finding_status" in issue_codes


def test_private_path_leakage_fails() -> None:
    record = _evidence_record(reviewed_public_paths=["docs/private/business-rules/example.docx"])

    issue_codes = {issue.issue_code for issue in validate_review_evidence(record)}

    assert "private_path_leak" in issue_codes


@pytest.mark.parametrize("payload_key", ["retailer_name", "source_column", "threshold_value", "private_notes"])
def test_suspicious_private_payload_keys_fail(payload_key: str) -> None:
    record = _evidence_record()
    record[payload_key] = "synthetic-looking value"

    issue_codes = {issue.issue_code for issue in validate_review_evidence(record)}

    assert "private_payload_key" in issue_codes


def test_same_originating_reviewer_rerun_requires_prior_evidence_id() -> None:
    record = _evidence_record(same_originating_reviewer=True, rerun_of_evidence_id=None, review_round=2)

    issue_codes = {issue.issue_code for issue in validate_review_evidence(record)}

    assert "missing_rerun_origin" in issue_codes


def test_required_reviewer_missing_cannot_final_approve() -> None:
    records = [_evidence_record(reviewer_role="architecture", approval_status="NEXT_LAYER_APPROVED")]

    with pytest.raises(ReviewEvidenceError) as exc_info:
        ReviewEvidenceBundle.validate(records, required_reviewer_roles=["architecture", "change"])

    assert "missing_required_reviewer_approval" in {issue.issue_code for issue in exc_info.value.issues}


def test_business_reviewer_requirement_is_explicit() -> None:
    records = [
        _evidence_record(reviewer_role="architecture", approval_status="NEXT_LAYER_APPROVED"),
        _evidence_record(
            evidence_id="review-change-1",
            originating_reviewer="retail_change_reviewer",
            reviewer_role="change",
            approval_status="APPROVED_FOR_COMMIT",
            review_status="APPROVED_FOR_COMMIT",
        ),
    ]

    with pytest.raises(ReviewEvidenceError) as exc_info:
        ReviewEvidenceBundle.validate(
            records,
            required_reviewer_roles=["architecture", "change"],
            business_rules_required=True,
        )

    assert "missing_required_reviewer_approval" in {issue.issue_code for issue in exc_info.value.issues}


def test_same_reviewer_rerun_record_passes_with_origin_id() -> None:
    ReviewEvidence.validate(
        _evidence_record(
            evidence_id="review-change-2",
            originating_reviewer="retail_change_reviewer",
            reviewer_role="change",
            review_status="APPROVED_FOR_COMMIT",
            approval_status="APPROVED_FOR_COMMIT",
            review_round=2,
            same_originating_reviewer=True,
            rerun_of_evidence_id="review-change-1",
        )
    )


def test_final_approval_with_open_finding_fails() -> None:
    record = _evidence_record(
        approval_status="APPROVED_FOR_COMMIT",
        review_status="APPROVED_FOR_COMMIT",
        originating_reviewer="retail_change_reviewer",
        reviewer_role="change",
        findings=[
            {
                "finding_id": "OVN-AUD-005",
                "severity": "Major",
                "status": "OPEN",
                "public_summary": "Lifecycle approval metadata is incomplete.",
                "affected_public_paths": ["src/retail_analytics/core/audit/review_evidence.py"],
                "requires_private_followup": False,
            }
        ],
    )

    issue_codes = {issue.issue_code for issue in validate_review_evidence(record)}

    assert "unresolved_findings_in_approval" in issue_codes


def test_final_approval_with_pending_review_finding_fails_bundle_validation() -> None:
    records = [
        _evidence_record(
            findings=[
                {
                    "finding_id": "OVN-AUD-005",
                    "severity": "Major",
                    "status": "REMEDIATED_PENDING_REVIEW",
                    "public_summary": "Lifecycle approval metadata awaits reviewer confirmation.",
                    "affected_public_paths": ["src/retail_analytics/core/audit/review_evidence.py"],
                    "requires_private_followup": False,
                }
            ]
        )
    ]

    with pytest.raises(ReviewEvidenceError) as exc_info:
        ReviewEvidenceBundle.validate(records, required_reviewer_roles=["architecture"])

    assert "unresolved_findings_in_approval" in {issue.issue_code for issue in exc_info.value.issues}


def test_same_reviewer_rerun_bundle_requires_existing_origin() -> None:
    records = [
        _evidence_record(
            evidence_id="review-change-2",
            originating_reviewer="retail_change_reviewer",
            reviewer_role="change",
            review_status="APPROVED_FOR_COMMIT",
            approval_status="APPROVED_FOR_COMMIT",
            review_round=2,
            same_originating_reviewer=True,
            rerun_of_evidence_id="review-change-1",
        )
    ]

    issues = validate_review_evidence_bundle(records, required_reviewer_roles=["change"])

    assert "missing_rerun_evidence" in {issue.issue_code for issue in issues}


def test_same_reviewer_rerun_bundle_requires_same_reviewer_role() -> None:
    original = _evidence_record(
        evidence_id="review-1",
        originating_reviewer="retail_architecture_reviewer",
        reviewer_role="architecture",
        review_round=1,
    )
    rerun = _evidence_record(
        evidence_id="review-2",
        originating_reviewer="retail_change_reviewer",
        reviewer_role="change",
        review_status="APPROVED_FOR_COMMIT",
        approval_status="APPROVED_FOR_COMMIT",
        review_round=2,
        same_originating_reviewer=True,
        rerun_of_evidence_id="review-1",
    )

    issues = validate_review_evidence_bundle([original, rerun], required_reviewer_roles=["change"])
    issue_codes = {issue.issue_code for issue in issues}

    assert "rerun_originating_reviewer_mismatch" in issue_codes
    assert "rerun_reviewer_role_mismatch" in issue_codes


def test_same_reviewer_rerun_bundle_requires_increasing_round() -> None:
    original = _evidence_record(evidence_id="review-1", review_round=2)
    rerun = _evidence_record(
        evidence_id="review-2",
        review_round=2,
        same_originating_reviewer=True,
        rerun_of_evidence_id="review-1",
    )

    issues = validate_review_evidence_bundle([original, rerun], required_reviewer_roles=["architecture"])

    assert "rerun_review_round_not_increasing" in {issue.issue_code for issue in issues}


def test_private_payload_key_detection_is_case_insensitive() -> None:
    record = _evidence_record()
    record["Retailer_Name"] = "synthetic-looking value"

    issue_codes = {issue.issue_code for issue in validate_review_evidence(record)}

    assert "private_payload_key" in issue_codes


def _evidence_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": "review-ovn-aud-005-architecture-1",
        "lifecycle_unit_id": "unit-c2-review-evidence",
        "issue_id": "OVN-AUD-005",
        "change_scope": "durable public-safe lifecycle review evidence",
        "git_base_ref": "origin/main",
        "git_head_ref": "HEAD",
        "originating_reviewer": "retail_architecture_reviewer",
        "reviewer_role": "architecture",
        "review_round": 1,
        "rerun_of_evidence_id": None,
        "same_originating_reviewer": False,
        "review_status": "NEXT_LAYER_APPROVED",
        "reviewed_public_paths": [
            "src/retail_analytics/core/audit/review_evidence.py",
            "docs/public/architecture/review-lifecycle-evidence.md",
        ],
        "private_context_used": False,
        "private_context_descriptor": None,
        "findings": [
            {
                "finding_id": "OVN-AUD-005",
                "severity": "Minor",
                "status": "CLOSED",
                "public_summary": "Lifecycle approval metadata is represented by a public-safe contract.",
                "affected_public_paths": [".codex/agents/retail-change-lifecycle-orchestrator.toml"],
                "requires_private_followup": False,
            }
        ],
        "remediations": [
            {
                "remediation_id": "unit-c2-contract",
                "public_summary": "Added review evidence validator and lifecycle instructions.",
            }
        ],
        "validations": [
            {"command": "pytest tests/unit/test_review_lifecycle_evidence.py", "status": "PASS"}
        ],
        "approval_status": "NEXT_LAYER_APPROVED",
        "created_at": "2026-08-24T00:00:00Z",
    }
    record.update(overrides)
    return record
