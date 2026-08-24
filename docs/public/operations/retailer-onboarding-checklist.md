# Retailer Onboarding Checklist

## Status

Publication-safe operational checklist for adding and running a retailer/source.

This checklist is written for an ordinary company system administrator. It
describes what to verify, where to look, and when to escalate. It does not expose
private business configuration contents.

## Roles

| Role | Responsibility |
| --- | --- |
| System administrator | File arrival, storage, scheduled runs, health checks, backup, restore, and operational incident handling. |
| Developer | Adapter defects, schema support, performance defects, failed tests, and code changes. |
| Business owner | Source meaning, metric definitions, rule approval, ownership, unsupported facts, and dashboard sign-off. |
| Reviewer | Architecture, change safety, and business-rules approval. |

## Intake Checklist

Before processing a new retailer/source:

- [ ] Retailer/source onboarding record exists.
- [ ] Source owner is named.
- [ ] Technical owner is named.
- [ ] Expected cadence is known: daily, weekly, monthly, or ad hoc.
- [ ] Expected source size range is known.
- [ ] Expected history coverage is known.
- [ ] File arrival location is configured.
- [ ] Private source storage path is ignored by Git.
- [ ] Source file hash and size are recorded.
- [ ] Corrected/reissued file policy is known.
- [ ] Source retention class is assigned.

Do not move a real source file into a tracked public path.

## File Arrival

Expected admin actions:

1. Confirm the file or feed arrived in the approved private landing location.
2. Confirm the filename or object key matches the operational naming policy.
3. Record arrival timestamp, size, and checksum.
4. Register the file as a source artifact/revision.
5. Confirm the source file is ignored by Git.

Escalate to developer if:

- source cannot be read;
- file size or encoding is far outside expected range;
- source registration fails;
- source schema version is unknown.

Escalate to business owner if:

- the file is not the expected report/source type;
- legal or ownership permission is unclear;
- business period coverage is unexpected.

## Processing Health

For each run, verify:

- [ ] source registration completed;
- [ ] source profile generated or reused appropriately;
- [ ] canonical ingestion completed;
- [ ] reconciliation status is pass or explicitly reviewed;
- [ ] tax/economics validation completed where applicable;
- [ ] metrics validation completed where applicable;
- [ ] mart build completed;
- [ ] dashboard smoke completed for supported features.

Operational run status should distinguish:

```text
received
registered
profiled
ingested
validated
mart_built
dashboard_ready
failed
blocked
```

## Logs and Artifacts

Admin should be able to locate:

| Artifact | Purpose |
| --- | --- |
| Source ledger | Registered source revisions, active state, source hash, period coverage. |
| Run metadata | Ingestion and analysis run identifiers. |
| Source profile | Columns, period coverage, quality observations. |
| Validation reports | Reconciliation, quality, metric, and dashboard smoke results. |
| Mart build metadata | `mart_build_id`, source revisions, analysis runs, status. |
| Capability matrix | What the dashboard may show and in what state. |
| Provenance audit | Whether "Откуда эта цифра?" can be shown for supported values. |

Private artifacts belong under ignored private storage. Public docs and generic
configs must not contain private source values.

## Storage Checklist

Verify storage coverage:

- [ ] raw source artifact stored immutably;
- [ ] source ledger retained;
- [ ] canonical Parquet retained;
- [ ] analysis outputs retained;
- [ ] mart Parquet retained;
- [ ] private config manifest retained;
- [ ] validation artifacts retained;
- [ ] backups cover raw, canonical, mart, metadata, and private config.

Dashboard navigation must read the mart, not raw source files.

## Failed Run Behavior

When a run fails:

1. Do not overwrite the previous approved mart build.
2. Preserve failed run logs and validation artifacts.
3. Keep old source revisions and mart builds immutable.
4. Mark current onboarding or run status as `BLOCKED` or failed.
5. Identify whether the failure is operational, developer, or business-semantic.
6. Reprocess only after the owner or developer resolves the cause.

Examples:

| Symptom | Likely owner |
| --- | --- |
| Missing file or unreadable file | System administrator |
| New or renamed source columns | Developer and business owner |
| Unknown category/tax/private-label meaning | Business owner |
| Reconciliation mismatch | Developer and business owner |
| Unsupported metric requested by dashboard | Developer or catalog owner |
| Ambiguous active source revisions | System administrator and developer |

## Reprocessing

Use reprocessing when:

- corrected source file arrives;
- mapping changes;
- business rules change;
- metric definitions change;
- previous run failed after source registration;
- dashboard mart needs rebuild for affected periods.

Rules:

- corrected files create new source revisions;
- old revisions remain immutable;
- active revision changes are metadata/state transitions;
- only affected periods should be invalidated when possible;
- full history rebuild requires a documented reason.

## Backup and Restore

Backup must include:

- raw source artifacts;
- source ledger;
- canonical Parquet;
- deterministic analysis outputs;
- mart Parquet or DuckDB files;
- private configuration;
- config manifest;
- validation and approval artifacts.

Restore checklist:

1. Restore raw source storage.
2. Restore private config and manifest.
3. Restore source ledger and run metadata.
4. Restore canonical and mart Parquet.
5. Verify checksums where available.
6. Run dashboard smoke.
7. Rebuild affected marts only if restored mart artifacts are missing or invalid.

Escalate if restored private config hash does not match mart metadata.

## Daily Feed Operations

For daily feeds:

- [ ] daily arrival is monitored;
- [ ] missing date alerts exist;
- [ ] late-arriving file policy is known;
- [ ] corrected-day policy is known;
- [ ] affected partition invalidation is configured;
- [ ] source revisions can be active per business date;
- [ ] old daily revisions remain auditable;
- [ ] archive policy prevents unbounded hot storage growth;
- [ ] dashboard range queries use mart partitions only.

Do not trigger a full-history rebuild for one corrected day unless a mapping or
semantic rule changed globally.

## Large-File Operations

For large files:

- [ ] source size is compared to expected range;
- [ ] ingestion runtime is recorded;
- [ ] mart build runtime is recorded;
- [ ] dashboard query latency is sampled after build;
- [ ] Parquet partition count is monitored;
- [ ] excessive small files are flagged for compaction review;
- [ ] raw XLSX parsing is not part of dashboard navigation.

Escalate to developer if dashboard latency becomes slow after mart build.

## Dashboard Readiness Checklist

A source may be exposed to dashboard users only when:

- [ ] status is `DASHBOARD_READY` or `ACTIVE`;
- [ ] active source revision is unambiguous;
- [ ] mart build is approved;
- [ ] effective metric catalog is available;
- [ ] presentation catalog labels are accurate;
- [ ] capability matrix exists for the retailer/source;
- [ ] unsupported features are explicit;
- [ ] private-label scope behavior is known;
- [ ] provenance coverage is accurate;
- [ ] dashboard smoke passes for supported grains;
- [ ] no private identifiers leaked into public code/config/docs.

Do not mark a dashboard feature as ready because a similarly named feature works
for another retailer.

## Developer Intervention Points

Developer intervention is required when:

- source adapter cannot parse the file;
- schema version is new and unmapped;
- generic public engine lacks a needed mechanic;
- validation failure indicates a code defect;
- performance audit finds a proven bottleneck;
- active revision logic is ambiguous;
- tests or publication safety checks fail;
- private config would otherwise require hardcoded public code.

## Business Owner Intervention Points

Business owner input is required when:

- revenue, cost, margin, tax, or VAT meaning is unclear;
- private-label or ownership mapping is unclear;
- product hierarchy semantics are ambiguous;
- comparison or sparse-period behavior needs a decision;
- ABC, peer, price segment, promo, event, or signal rules are undefined;
- a dashboard label could imply unsupported business meaning;
- unsupported facts must be accepted as limitations.

Ask concrete questions tied to observed source values. Do not ask the business
owner to redesign the system.

## Review Gates

Before activation, confirm:

- [ ] architecture reviewer approved any new generic contract;
- [ ] business-rules reviewer approved retailer/source semantics;
- [ ] change reviewer approved code or contract changes;
- [ ] reviewer findings were remediated and re-reviewed;
- [ ] final validation passed.

## Publication Safety

Before commit or release:

- [ ] `config/private/` is ignored;
- [ ] `data/private/` is ignored;
- [ ] `docs/private/` is ignored;
- [ ] public tests use synthetic identifiers;
- [ ] public docs contain no real retailer-specific rules;
- [ ] public code has no retailer-specific hardcoding;
- [ ] source files are absent from tracked Git files.

## Routine Operations Summary

```text
file arrives
-> register source revision
-> run ingestion/validation
-> build or update mart
-> run dashboard smoke
-> monitor health
```

If any step fails, preserve the previous approved mart and escalate to the
appropriate owner.
