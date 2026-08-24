"""Public-safe lifecycle review evidence validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "review-evidence-v1"

REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_id",
        "lifecycle_unit_id",
        "issue_id",
        "change_scope",
        "git_base_ref",
        "git_head_ref",
        "originating_reviewer",
        "reviewer_role",
        "review_round",
        "rerun_of_evidence_id",
        "same_originating_reviewer",
        "review_status",
        "reviewed_public_paths",
        "private_context_used",
        "private_context_descriptor",
        "findings",
        "remediations",
        "validations",
        "approval_status",
        "created_at",
    }
)

REQUIRED_FINDING_FIELDS = frozenset(
    {
        "finding_id",
        "severity",
        "status",
        "public_summary",
        "affected_public_paths",
        "requires_private_followup",
    }
)

REVIEWER_ROLES = frozenset(
    {
        "architecture",
        "change",
        "business_rules",
        "contract",
        "test_planning",
    }
)

ORIGINATING_REVIEWERS = frozenset(
    {
        "retail_architecture_reviewer",
        "retail_change_reviewer",
        "retail_business_rules_reviewer",
        "retail_contract_reviewer",
        "retail_test_planner",
    }
)

REVIEW_STATUSES = frozenset(
    {
        "NEXT_LAYER_APPROVED",
        "APPROVED_FOR_COMMIT",
        "BUSINESS_RULES_APPROVED",
        "CHANGES_REQUIRED",
        "BUSINESS_RULE_CHANGES_REQUIRED",
        "ARCHITECTURE_CHANGES_REQUIRED",
        "BLOCKED",
        "BUSINESS_RULES_BLOCKED",
    }
)

APPROVAL_STATUSES = frozenset(
    {
        "NEXT_LAYER_APPROVED",
        "APPROVED_FOR_COMMIT",
        "BUSINESS_RULES_APPROVED",
        "CHANGES_REQUIRED",
        "BLOCKED",
    }
)

FINDING_SEVERITIES = frozenset({"Critical", "Major", "Minor", "Non-blocking"})
FINDING_STATUSES = frozenset(
    {
        "OPEN",
        "REMEDIATED_PENDING_REVIEW",
        "APPROVED",
        "CLOSED",
        "ACKNOWLEDGED_NO_REWRITE",
        "OUT_OF_SCOPE_FUTURE_WORK",
    }
)
UNRESOLVED_FINDING_STATUSES = frozenset({"OPEN", "REMEDIATED_PENDING_REVIEW"})
TERMINAL_APPROVAL_STATUSES = frozenset(
    {"NEXT_LAYER_APPROVED", "APPROVED_FOR_COMMIT", "BUSINESS_RULES_APPROVED"}
)

PRIVATE_PATH_MARKERS = ("config/private", "data/private", "docs/private")
SUSPICIOUS_PRIVATE_KEYS = frozenset(
    {
        "retailer_name",
        "source_column",
        "source_columns",
        "threshold_value",
        "private_notes",
        "private_payload",
        "business_rule_text",
        "private_config_snippet",
    }
)


@dataclass(frozen=True)
class ReviewEvidenceIssue:
    """Structured validation issue for review evidence metadata."""

    issue_code: str
    message: str


class ReviewEvidenceError(ValueError):
    """Raised when lifecycle review evidence is invalid or not public-safe."""

    def __init__(self, issues: Sequence[ReviewEvidenceIssue]) -> None:
        self.issues = tuple(issues)
        joined = "; ".join(f"{issue.issue_code}: {issue.message}" for issue in self.issues)
        super().__init__(joined)


class ReviewEvidence:
    """Public-safe validation API for lifecycle review evidence records."""

    @staticmethod
    def validate(record: Mapping[str, Any]) -> None:
        issues = validate_review_evidence(record)
        if issues:
            raise ReviewEvidenceError(issues)


class ReviewEvidenceBundle:
    """Validate unit-level evidence completeness across required reviewers."""

    @staticmethod
    def validate(
        records: Sequence[Mapping[str, Any]],
        *,
        required_reviewer_roles: Sequence[str],
        business_rules_required: bool = False,
    ) -> None:
        issues = validate_review_evidence_bundle(
            records,
            required_reviewer_roles=required_reviewer_roles,
            business_rules_required=business_rules_required,
        )
        if issues:
            raise ReviewEvidenceError(issues)


def validate_review_evidence(record: Mapping[str, Any]) -> tuple[ReviewEvidenceIssue, ...]:
    """Return validation issues for one public lifecycle evidence record."""

    issues: list[ReviewEvidenceIssue] = []
    _validate_required_fields(record, issues)
    if issues:
        return tuple(issues)

    _expect_value(record, "schema_version", SCHEMA_VERSION, issues)
    _expect_non_empty_string(record, "evidence_id", issues)
    _expect_non_empty_string(record, "lifecycle_unit_id", issues)
    _expect_non_empty_string(record, "change_scope", issues)
    _expect_non_empty_string(record, "git_base_ref", issues)
    _expect_non_empty_string(record, "git_head_ref", issues)
    _expect_member(record, "originating_reviewer", ORIGINATING_REVIEWERS, issues)
    _expect_member(record, "reviewer_role", REVIEWER_ROLES, issues)
    _expect_member(record, "review_status", REVIEW_STATUSES, issues)
    _expect_member(record, "approval_status", APPROVAL_STATUSES, issues)
    _expect_boolean(record, "same_originating_reviewer", issues)
    _expect_boolean(record, "private_context_used", issues)
    _expect_non_empty_string(record, "created_at", issues)

    review_round = record["review_round"]
    if not isinstance(review_round, int) or isinstance(review_round, bool) or review_round < 1:
        issues.append(ReviewEvidenceIssue("invalid_review_round", "review_round must be an integer >= 1"))

    rerun_of = record["rerun_of_evidence_id"]
    same_origin = record["same_originating_reviewer"]
    if same_origin and not isinstance(rerun_of, str):
        issues.append(
            ReviewEvidenceIssue(
                "missing_rerun_origin", "same-originating-reviewer re-review requires rerun_of_evidence_id"
            )
        )
    if not same_origin and rerun_of is not None:
        issues.append(
            ReviewEvidenceIssue(
                "unexpected_rerun_origin", "rerun_of_evidence_id is only allowed for same-originating re-review"
            )
        )

    reviewed_paths = record["reviewed_public_paths"]
    if not _is_string_sequence(reviewed_paths):
        issues.append(
            ReviewEvidenceIssue("invalid_reviewed_public_paths", "reviewed_public_paths must be strings")
        )

    findings = record["findings"]
    if not isinstance(findings, list):
        issues.append(ReviewEvidenceIssue("invalid_findings", "findings must be a list"))
    else:
        for index, finding in enumerate(findings):
            _validate_finding(finding, index, issues)
        if record["approval_status"] in TERMINAL_APPROVAL_STATUSES:
            unresolved = [
                finding.get("finding_id", f"finding-{index}")
                for index, finding in enumerate(findings)
                if isinstance(finding, Mapping)
                and finding.get("status") in UNRESOLVED_FINDING_STATUSES
            ]
            if unresolved:
                issues.append(
                    ReviewEvidenceIssue(
                        "unresolved_findings_in_approval",
                        f"final approval evidence has unresolved finding(s): {unresolved}",
                    )
                )

    if not isinstance(record["remediations"], list):
        issues.append(ReviewEvidenceIssue("invalid_remediations", "remediations must be a list"))
    if not isinstance(record["validations"], list):
        issues.append(ReviewEvidenceIssue("invalid_validations", "validations must be a list"))

    issues.extend(_private_leakage_issues(record))
    return tuple(issues)


def validate_review_evidence_bundle(
    records: Sequence[Mapping[str, Any]],
    *,
    required_reviewer_roles: Sequence[str],
    business_rules_required: bool = False,
) -> tuple[ReviewEvidenceIssue, ...]:
    """Validate evidence records are individually safe and contain required final approvals."""

    issues: list[ReviewEvidenceIssue] = []
    for record in records:
        issues.extend(validate_review_evidence(record))

    required_roles = set(required_reviewer_roles)
    invalid_required = required_roles - REVIEWER_ROLES
    if invalid_required:
        issues.append(
            ReviewEvidenceIssue(
                "invalid_required_reviewer", f"unknown required reviewer role(s): {sorted(invalid_required)}"
            )
        )
    if business_rules_required:
        required_roles.add("business_rules")

    records_by_id = {
        str(record.get("evidence_id")): record
        for record in records
        if isinstance(record.get("evidence_id"), str)
    }
    for record in records:
        if record.get("same_originating_reviewer") is True:
            rerun_id = record.get("rerun_of_evidence_id")
            origin = records_by_id.get(str(rerun_id)) if isinstance(rerun_id, str) else None
            if origin is None:
                issues.append(
                    ReviewEvidenceIssue(
                        "missing_rerun_evidence",
                        f"rerun_of_evidence_id does not reference bundle evidence: {rerun_id!r}",
                    )
                )
                continue
            if origin.get("originating_reviewer") != record.get("originating_reviewer"):
                issues.append(
                    ReviewEvidenceIssue(
                        "rerun_originating_reviewer_mismatch",
                        "same-originating-reviewer re-review must reference the same reviewer",
                    )
                )
            if origin.get("reviewer_role") != record.get("reviewer_role"):
                issues.append(
                    ReviewEvidenceIssue(
                        "rerun_reviewer_role_mismatch",
                        "same-originating-reviewer re-review must reference the same reviewer role",
                    )
                )
            current_round = record.get("review_round")
            origin_round = origin.get("review_round")
            if (
                not isinstance(current_round, int)
                or not isinstance(origin_round, int)
                or current_round <= origin_round
            ):
                issues.append(
                    ReviewEvidenceIssue(
                        "rerun_review_round_not_increasing",
                        "same-originating-reviewer review_round must be greater than original round",
                    )
                )

    approved_roles = {
        str(record.get("reviewer_role"))
        for record in records
        if record.get("approval_status") in TERMINAL_APPROVAL_STATUSES
    }
    missing = sorted(required_roles - approved_roles)
    if missing:
        issues.append(
            ReviewEvidenceIssue(
                "missing_required_reviewer_approval",
                f"missing final approval evidence for reviewer role(s): {missing}",
            )
        )

    return tuple(issues)


def _validate_required_fields(record: Mapping[str, Any], issues: list[ReviewEvidenceIssue]) -> None:
    missing = sorted(REQUIRED_EVIDENCE_FIELDS - set(record))
    if missing:
        issues.append(ReviewEvidenceIssue("missing_required_fields", f"missing fields: {missing}"))


def _validate_finding(finding: Any, index: int, issues: list[ReviewEvidenceIssue]) -> None:
    if not isinstance(finding, Mapping):
        issues.append(ReviewEvidenceIssue("invalid_finding", f"finding {index} must be a mapping"))
        return

    missing = sorted(REQUIRED_FINDING_FIELDS - set(finding))
    if missing:
        issues.append(ReviewEvidenceIssue("missing_finding_fields", f"finding {index} missing: {missing}"))
    if finding.get("severity") not in FINDING_SEVERITIES:
        issues.append(ReviewEvidenceIssue("invalid_finding_severity", f"finding {index} has invalid severity"))
    if finding.get("status") not in FINDING_STATUSES:
        issues.append(ReviewEvidenceIssue("invalid_finding_status", f"finding {index} has invalid status"))
    if not _is_string_sequence(finding.get("affected_public_paths")):
        issues.append(
            ReviewEvidenceIssue("invalid_finding_paths", f"finding {index} affected_public_paths must be strings")
        )
    if not isinstance(finding.get("requires_private_followup"), bool):
        issues.append(
            ReviewEvidenceIssue(
                "invalid_private_followup", f"finding {index} requires_private_followup must be boolean"
            )
        )


def _private_leakage_issues(value: Any, path: str = "record") -> tuple[ReviewEvidenceIssue, ...]:
    issues: list[ReviewEvidenceIssue] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            if key_text.lower() in SUSPICIOUS_PRIVATE_KEYS:
                issues.append(
                    ReviewEvidenceIssue("private_payload_key", f"private-like key is not allowed at {path}.{key_text}")
                )
            issues.extend(_private_leakage_issues(nested, f"{path}.{key_text}"))
    elif isinstance(value, str):
        normalized = value.replace("\\", "/").lower()
        if any(marker in normalized for marker in PRIVATE_PATH_MARKERS):
            issues.append(ReviewEvidenceIssue("private_path_leak", f"private path marker found at {path}"))
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for index, nested in enumerate(value):
            issues.extend(_private_leakage_issues(nested, f"{path}[{index}]"))
    return tuple(issues)


def _expect_value(
    record: Mapping[str, Any], field: str, expected: str, issues: list[ReviewEvidenceIssue]
) -> None:
    if record[field] != expected:
        issues.append(ReviewEvidenceIssue(f"invalid_{field}", f"{field} must be {expected!r}"))


def _expect_member(
    record: Mapping[str, Any], field: str, allowed: frozenset[str], issues: list[ReviewEvidenceIssue]
) -> None:
    if record[field] not in allowed:
        issues.append(ReviewEvidenceIssue(f"invalid_{field}", f"{field} has unsupported value"))


def _expect_non_empty_string(record: Mapping[str, Any], field: str, issues: list[ReviewEvidenceIssue]) -> None:
    if not isinstance(record[field], str) or not record[field].strip():
        issues.append(ReviewEvidenceIssue(f"invalid_{field}", f"{field} must be a non-empty string"))


def _expect_boolean(record: Mapping[str, Any], field: str, issues: list[ReviewEvidenceIssue]) -> None:
    if not isinstance(record[field], bool):
        issues.append(ReviewEvidenceIssue(f"invalid_{field}", f"{field} must be boolean"))


def _is_string_sequence(value: Any) -> bool:
    return isinstance(value, list | tuple) and all(isinstance(item, str) for item in value)
