# Retailer Onboarding Workflow

## Status

Publication-safe onboarding contract for adding a new retailer or source feed.

This document defines the required workflow, review gates, private configuration
areas, and dashboard readiness criteria. It does not define retailer-specific
business rules, private thresholds, source column names, or future retailer
semantics.

## Core Invariant

Canonical shape is not business meaning.

A new retailer is added through:

```text
Configured Source Adapter / mapping
+ private business rules
+ private metric definitions
+ private semantic mappings
+ private ownership and source configuration
```

The public engine must not fork per retailer and must not hardcode client logic.
Public code provides generic mechanics; private configuration and reviewed
business documents define exact meaning for each retailer/source.

## Identity Boundaries

Each onboarding package must preserve these identities:

| Identity | Purpose |
| --- | --- |
| `retailer_id` | Retailer or commercial account scope. |
| `source_id` | One configured source feed/report type under a retailer. |
| `source_revision_id` | Immutable registered source revision, including corrected files. |
| `mapping_config_hash` | Exact source-to-canonical mapping package. |
| `rule_version` | Private business-rule package version. |
| `metric_definition_id/version/hash` | Exact retailer/source metric semantics. |
| `analysis_run_id` | Deterministic analytics execution. |
| `mart_build_id` | Approved historical dashboard mart build. |

Display names are not identity keys. The same Russian UI label across retailers
does not imply semantic equivalence.

## Onboarding Status Model

Use one status per retailer/source onboarding record:

| Status | Meaning |
| --- | --- |
| `SOURCE_RECEIVED` | Source artifact received and stored privately, but not profiled. |
| `PROFILED` | Source profile completed with columns, grain, periods, quality risks, and hierarchy. |
| `SEMANTICS_PENDING` | Source is profiled but business meaning is not fully resolved. |
| `PRIVATE_CONFIG_READY` | Private mapping/rules/catalog overrides are versioned and review-ready. |
| `INGESTION_VALIDATED` | Real-file canonical ingestion and reconciliation pass. |
| `ECONOMICS_VALIDATED` | Tax/economics semantics and calculations pass for real data. |
| `METRICS_VALIDATED` | Deterministic metric definitions pass focused and real-data validation. |
| `BENCHMARKING_VALIDATED` | Peer, ABC, price-segment, and ranking contracts pass where available. |
| `EVENTS_VALIDATED` | Event/signal rules pass where available; unsupported events are explicit. |
| `MART_READY` | Source ledger, active revision, mart build, and metric facts are available. |
| `DASHBOARD_READY` | Presentation catalog, capability matrix, provenance, and dashboard smoke pass. |
| `ACTIVE` | Retailer/source is approved for routine production runs. |
| `BLOCKED` | Onboarding cannot continue without business, source, or technical input. |

Do not skip from `PROFILED` to `DASHBOARD_READY`. Status transitions must be
backed by artifacts and review notes.

## Phase 1. Source Intake

Record source ownership and operational shape before profiling:

- business owner and technical owner;
- file arrival path or integration endpoint;
- source frequency and expected cadence;
- period grain: daily, weekly, monthly, or mixed;
- expected file size and row count range;
- expected schema version and source-system version if known;
- history coverage and expected backfill depth;
- whether files can be corrected, reissued, or overlap prior periods;
- whether one file can contain multiple business periods;
- whether identical duplicate files should be recorded or ignored operationally;
- retention and archive expectations.

Required output:

```text
source intake record
source artifact storage path
initial source ledger entry or registration plan
```

## Phase 2. Source Profiling

Profile the real file without applying business assumptions:

- columns and data types;
- observed periods and period labels;
- source grain and key candidates;
- duplicate row patterns;
- null and blank value rates;
- negative/correction rows;
- category, subcategory, brand, manufacturer, store, and SKU hierarchy;
- store aliases and source store identifiers;
- product identifiers and source SKU/PLU stability;
- geographic fields, if present;
- private-label candidate fields, if present;
- price, revenue, units, and cost fields;
- source anomalies and unsupported source fields.

Required output:

```text
private source profile
source quality report
unresolved source questions
```

Profiling is evidence collection, not semantic classification.

## Phase 3. Canonical Mapping

Create private source-to-canonical mapping:

- source field mapping to canonical fields;
- period parsing and calendar normalization;
- optional versus required fields;
- source hierarchy mapping;
- categorical semantic maps;
- product and store aliases;
- private-label semantic mapping;
- missing-value handling;
- correction-row preservation;
- source row traceability;
- mapping version and hash.

Mapping must be reviewed against real source evidence. Do not infer private-label
or tax semantics from names, brands, sizes, or other indirect clues unless the
business review explicitly approves that rule.

Required output:

```text
config/private/source_mapping.yaml
private semantic mapping files as needed
mapping_config_hash
canonical ingestion smoke result
```

## Phase 4. Business Rules Interview

Resolve business meaning explicitly. At minimum cover:

- revenue semantics: gross, net, VAT-inclusive, discounts, returns;
- VAT/tax categories and date-effective rules;
- retailer economics and cost/margin definitions;
- margin percentage denominator;
- distribution numerator and denominator;
- velocity numerator and denominator;
- comparison modes and sparse-period behavior;
- ABC scope, basis, thresholds, and period/range policy;
- peer rules: broad pools, direct comparable pools, and exclusions;
- price segment universe and boundaries;
- materiality thresholds;
- promo facts and promo unavailability;
- event/signal semantics and required evidence;
- ownership and private-label interpretation;
- known unavailable facts and unsupported dashboard claims.

Every resolved rule needs an identifier, version, source evidence, and owner.
Every unresolved rule needs a concrete question and blocking status.

Required reviewer:

```text
retail_business_rules_reviewer
```

## Phase 5. Ownership

Define private ownership scopes:

- own manufacturers;
- own brands;
- own SKUs, if ownership is SKU-level;
- private-label products;
- competitor universe;
- exclusions from competitor pools;
- source-specific ownership caveats.

Ownership is not a UI filter. It affects analytical universe, rankings,
benchmarks, comparisons, and signals where those semantics apply.

## Phase 6. Private Configs

Required versioned private files depend on the source, but a dashboard-ready
retailer/source normally needs:

```text
config/private/runtime_context.yaml
config/private/source_mapping.yaml
config/private/tax_rules.yaml
config/private/metric_definitions.yaml
config/private/dashboard_metric_catalog.yaml
config/private/ownership_rules.yaml
config/private/peer_rules.yaml
config/private/event_rules.yaml
config/private/config_manifest.yaml
config/private/unresolved_rules.yaml
```

Use only the files that are relevant for the source. If a feature is unavailable,
record that explicitly rather than creating placeholder business rules.

Private config must include:

- config version;
- owner/reviewer;
- effective dates where applicable;
- source document or interview reference;
- hash/provenance in the manifest;
- compatibility notes if definitions may be compared across sources.

Private config contents must stay ignored by Git.

## Phase 7. Business-Rules Review

Before real validation can be considered complete, the business reviewer checks:

- no assumption that all retailers share semantics;
- no use of source column names as meaning without mapping;
- no default tax/economics rule unless explicitly configured;
- ownership and private-label behavior;
- metric definitions and range behavior;
- comparison and sparse-period semantics;
- unsupported features and known limitations.

Outcome:

```text
BUSINESS_RULES_APPROVED
CHANGES_REQUIRED
BLOCKED
```

## Phase 8. Synthetic Validation

Add or reuse public-safe synthetic fixtures for:

- mapping mechanics;
- tax/economics mechanics;
- metric definitions;
- comparison behavior;
- source revision behavior;
- private-label scope;
- unsupported feature states.

Synthetic fixtures must use neutral identifiers such as:

```text
retailer_a
source_a
CATEGORY_STANDARD
SKU_A_001
STORE_A_001
```

They must not encode real client labels or private thresholds.

## Phase 9. Real-File Smoke

Run the real source through ingestion and focused validation in ignored storage:

- source exists in private source storage;
- source is ignored by Git;
- source hash and size recorded;
- canonical row count matches expectations;
- source row traceability is present;
- additive reconciliation passes;
- no private file appears in tracked status.

This step may remain smoke-level until all semantics are approved.

## Phase 10. Golden Cases

Create private golden cases for the retailer/source:

- representative SKU/store/month rows;
- returns or corrections;
- tax category examples;
- private-label examples;
- ownership examples;
- share denominator examples;
- comparison examples;
- known unavailable facts.

Golden cases should be small enough for business review and stable enough for
regression validation.

## Phase 11. Full Deterministic Validation

Run the approved pipeline over the real source:

- canonical ingestion;
- tax/economics enrichment;
- quality classification;
- reconciliation;
- core metrics;
- comparisons and ABC where available;
- benchmarking and peer pools where available;
- event/signal rules where available;
- publication safety.

Real validation must report unsupported features explicitly.

## Phase 12. Mart Build

Register source revisions and build the historical mart:

- source ledger entry exists;
- active revision policy is applied;
- corrected/reissued files do not overwrite history;
- affected periods are identified;
- mart build metadata records source revisions and analysis runs;
- `mart_metric_facts` preserve metric identity and lineage;
- duplicate semantic identities are zero;
- selected current mart build is explicit.

The dashboard must read the mart, not raw source files.

## Phase 13. Metric and Presentation Catalog

Create effective catalog entries:

- public generic catalog entry exists where applicable;
- private retailer/source override declares availability;
- exact metric definition id/version/hash is linked;
- range strategy is safe;
- comparison modes are supported or rejected;
- presentation label is accurate;
- limitations are visible.

The presentation catalog maps internal concepts to user-facing Russian labels.
It does not define formulas.

## Phase 14. Capability Matrix

Generate or update the effective capability matrix:

- backend fact source;
- presentation placement;
- grain support;
- single-period, comparison, date-range support;
- private-label scope support;
- provenance support;
- signal and future recommendation eligibility;
- availability status: `READY`, `PARTIAL`, `NOT_AVAILABLE`, or `NOT_APPLICABLE`;
- limitations.

No feature may be shown as `READY` if it cannot honor the selected analytical
scope and metric semantics.

## Phase 15. Dashboard Readiness

A retailer/source is dashboard-ready only when:

- source mapping is validated;
- business semantics are reviewed;
- real reconciliation passes;
- relevant metrics have catalog entries;
- presentation catalog terminology is accurate;
- capability matrix is generated and checked;
- unsupported features are explicit;
- private files remain private;
- historical source/revision model is configured;
- mart query smoke passes for supported grains;
- provenance coverage is accurate.

Dashboard readiness does not imply every possible feature is ready. It means the
dashboard can safely show the supported subset and limitations.

## Phase 16. Production Activation

Activation requires:

- approved private config manifest;
- active source revision policy;
- scheduled ingestion or manual runbook;
- dashboard runtime entry;
- monitoring and health check path;
- backup/restore coverage;
- owner sign-off;
- rollback or deactivation plan.

After activation, new files follow the source ledger and validation gates. A
schema or semantics change re-enters the workflow at the appropriate phase.

## Daily and Large-File Path

Daily and large sources require additional operational design:

- incremental ingestion by source revision and affected period partition;
- no full-history rebuild unless mapping or business-rule change requires it;
- active revision selection per retailer/source/business period;
- partition invalidation for canonical, metrics, comparisons, benchmarks, events,
  and mart facts;
- archive and retention policy hooks;
- periodic compaction if small files become a query problem;
- monitoring of file size, row count, runtime, and missing dates;
- late-arriving or corrected daily files handled as new revisions;
- dashboard queries against mart partitions only.

For files up to several hundred MB, the normal path remains:

```text
raw source storage
-> registered source revision
-> canonical Parquet
-> deterministic analytics
-> mart Parquet / DuckDB
-> dashboard query
```

Raw XLSX or source files must not be reread for ordinary dashboard navigation.

## Definition of Done

Retailer/source onboarding is done when:

- status is `ACTIVE`;
- current source revision set is approved;
- private config manifest is versioned;
- business-rule reviewer approval is recorded;
- real validation and reconciliation pass;
- mart build is approved;
- catalog and capability matrix match runtime behavior;
- dashboard smoke and provenance checks pass;
- operational handoff is complete;
- unsupported or unavailable facts are documented.

## Blockers

Use `BLOCKED` when:

- source file is missing or cannot be legally stored;
- source schema is unknown or unstable without owner input;
- business rules are unresolved for a required metric;
- private config would require hardcoding in public code;
- reconciliation fails without accepted explanation;
- active source revisions are ambiguous;
- dashboard would need to show unsupported semantics as if ready.

## Non-Responsibilities

This workflow does not:

- invent rules for future retailers;
- define private thresholds;
- require every dashboard feature for every retailer;
- replace business owner review;
- prescribe infrastructure beyond the current generic contracts;
- authorize cross-retailer comparison without semantic compatibility approval.
