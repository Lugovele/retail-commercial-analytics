# Review Lifecycle Evidence

This contract defines the public-safe metadata required to make lifecycle reviewer gates auditable after a change has landed. It records review status and scope metadata only. It does not store reviewer transcripts, private business-rule text, private source values, or private configuration snippets.

## Purpose

The review lifecycle remains:

```text
repository state -> architecture review -> implementation -> validation -> change review -> business review when semantic -> remediation -> same-originating-reviewer re-review -> approval
```

For every commit-ready unit, the orchestrator or main lifecycle runner should produce compact evidence that can later answer:

- which unit was reviewed;
- which reviewer role reviewed it;
- which public files or diff scope were reviewed;
- whether private context was used without exposing it;
- what public-safe findings existed;
- what remediation was performed;
- whether the same originating reviewer approved the re-review;
- which validation commands supported the approval.

## Storage Model

Tracked public artifacts may contain only the schema and public-safe lifecycle metadata. Detailed reviewer transcripts or private semantic findings belong under ignored private storage such as `data/private/reviews/`.

The public schema lives at:

```text
config/public/review_lifecycle_evidence_schema.yaml
```

Reference report parity governance lives at:

```text
config/public/reference_report_parity_contract.yaml
```

The validation API lives at:

```text
src/retail_analytics/core/audit/review_evidence.py
```

## Required Evidence Fields

Each evidence record must include:

```text
schema_version
evidence_id
lifecycle_unit_id
issue_id
change_scope
git_base_ref
git_head_ref
originating_reviewer
reviewer_role
review_round
rerun_of_evidence_id
same_originating_reviewer
review_status
reviewed_public_paths
private_context_used
private_context_descriptor
findings
remediations
validations
approval_status
created_at
```

`issue_id` may refer to an audit finding, remediation finding, or lifecycle unit. If no external issue exists, it should use the lifecycle unit id.

## Same-Originating-Reviewer Re-Review

A remediation re-review must preserve reviewer identity with:

```text
originating_reviewer
rerun_of_evidence_id
same_originating_reviewer: true
review_round
```

The remediation agent can record remediation metadata, but it cannot approve the finding. Final approval must come from the same originating reviewer role that raised the finding.

## Privacy Boundary

Public evidence must never include:

- private paths under `config/private`, `data/private`, or `docs/private`;
- real retailer names;
- real source column names;
- private thresholds;
- private business-rule excerpts;
- private reviewer notes or payloads.

If private context was used, record only:

```text
private_context_used: true
private_context_descriptor: private business-rule/config context inspected; details retained in ignored review storage
```

## Agent Responsibilities

The lifecycle orchestrator is responsible for requiring or writing final public-safe evidence after approval. Read-only reviewers remain read-only and report statuses only. The change reviewer verifies evidence shape and publication safety when evidence files are in scope. The business-rules reviewer may say whether private context was used, but must not place private payloads into tracked evidence. The remediation agent may update remediation metadata but cannot mark reviewer approval.

## Reference Report Parity

When a private analytical reference report is registered, meaningful analytical
or product-semantic changes must include parity-impact consideration. This asks
whether registered reference content exists, which parity concepts are affected,
whether analytical access is removed or degraded, whether semantics are
introduced or reinterpreted, and whether any unresolved gap is explicitly
surfaced.

This applies to metric additions or removals, comparison semantics, dashboard
screen capability, filters and dimensions, Portfolio, Sales Drivers, tables,
ranking, share, ABC, and Metric Inspector definitions. Trivial CSS or purely
cosmetic work does not require a full workbook re-audit.
