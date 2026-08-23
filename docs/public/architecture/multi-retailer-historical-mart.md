# Multi-Retailer Historical Dashboard Mart Architecture

## Status

Architecture checkpoint approved for documentation and future implementation planning.

This document defines the target architecture for historical dashboard analytics across multiple retailers and report sources. It is not a production implementation plan for UI, recommendations, LLM integration, or retailer-specific semantics.

## Core Invariants

The canonical model unifies data shape, not business meaning.

Public code and public documentation define generic contracts, generic mechanics, and synthetic examples. Private deployment configuration owns retailer-specific source mappings, tax rules, metric definitions, ownership rules, event rules, peer rules, semantic dictionaries, source files, and business documents.

The same metric concept or display label across retailers does not imply identical calculation semantics. The backend must preserve retailer-specific metric identity and rule lineage for every calculated value.

## Logical Pipeline

```text
Source File
-> Source Registration
-> Configured Source Adapter / Private Mapping
-> Canonical Historical Facts
-> Retailer-Specific Semantic / Metric Rules
-> Deterministic Analytics
-> Historical Dashboard Analytics Mart
-> Dashboard Queries
-> Future Recommendation Context
-> Decision Engine / LLM
```

Dashboard queries and future recommendation generation must consume deterministic mart or evidence outputs. They must not parse raw source files for ordinary requests and must not invent metric formulas.

## Identity Model

The architecture separates retailer, source, business-rule, metric, and run identity.

`retailer_id` identifies the retailer or commercial account context. It is a scope boundary, not a display label.

`source_id` identifies a configured source feed or report type within a retailer context. `source_type` identifies the broad source class. `source_file_id` or `source_hash` identifies one immutable raw artifact. `source_version` identifies the content version used by a run. `source_revision_id` identifies a registered source artifact revision, including corrected or reissued files.

`rule_version` identifies the private rule package applied during calculation. Mapping, tax, metric, peer, event, ownership, and alias hashes provide finer-grained reproducibility.

`metric_concept` is generic, such as `retailer_margin_pct`, `numeric_distribution`, or `units_per_selling_store`. `metric_definition_id`, `metric_definition_version`, and `metric_config_hash` identify the exact retailer/source/rule-specific calculation.

`ingestion_run_id` identifies source-to-canonical processing. `analysis_run_id` identifies deterministic analytics execution. `mart_build_id` identifies a materialized mart build over approved analysis runs.

## Metric Semantic Identity

A metric fact is uniquely identified by at least:

```text
retailer_id
source_id
analysis_run_id or mart_build_id
period_grain
period_start
period_end
grain_id
entity_id
metric_definition_id
metric_definition_version
metric_config_hash
rule_version
```

`metric_concept`, `metric_name`, and display labels are not sufficient identity keys. They may be used for filtering or presentation only after the query has preserved definition lineage.

Cross-retailer comparison is forbidden by default. It is allowed only when private configuration explicitly declares semantic compatibility.

## Semantic Compatibility

The optional compatibility contract is:

```text
semantic_family
semantic_compatibility_version
cross_retailer_comparable
compatibility_scope
compatibility_notes
```

If `cross_retailer_comparable` is false or absent, the dashboard may show metrics side by side with lineage but must not compute direct deltas, rankings, or pooled summaries across retailers.

## Historical Source Ledger

Source registration is append-oriented. A new source file creates a new immutable ledger entry.

Minimum ledger fields:

```text
source_revision_id
retailer_id
source_id
source_type
source_file_id
source_hash
raw_object_key
size_bytes
received_at
registered_at
period_grain
period_start
period_end
observed_periods
source_schema_version
mapping_config_hash
rule_package_hash
row_count
processing_status
supersedes_revision_id
superseded_by_revision_id
is_active_revision
status_reason
```

If a registered file has the same hash and source scope as an existing ledger entry, classify it as an identical duplicate and do not create duplicate active facts.

Overlapping periods are allowed in the ledger but cannot both be active for the same retailer/source/period coverage policy unless an approved rule explicitly defines additive coexistence.

Corrected or reissued files create new revisions. Raw files and historical analysis runs remain retained. Current dashboard mode uses the approved active revision set; audit mode can inspect older revisions.

A new source schema version requires an explicit mapping version and validation. Schema changes do not silently inherit prior mappings.

The same retailer may have multiple `source_id` values for different report types. The mart must preserve source scope and cannot merge sources unless a deterministic integration rule defines how.

## Temporal Model

The system must not assume that all sources are monthly.

Minimum temporal fields:

```text
period_grain
period_start
period_end
business_period_id
calendar_year
calendar_month
calendar_week
calendar_date
```

Current monthly sources map to `period_grain = month`, `period_start` as the first day of the month, and `period_end` as the last day of the month.

Daily and weekly sources can coexist with monthly sources if the mart partitions and query contracts always include `period_grain`.

## Available-Period Semantics

Dashboard requests separate requested range from available data.

Response metadata must include:

```text
requested_date_from
requested_date_to
available_periods
missing_periods
coverage_ratio
coverage_status
period_grain
```

The dashboard must not create artificial zeroes for missing periods unless a metric definition explicitly defines that behavior. Missing periods remain missing, and comparisons across gaps must carry quality metadata.

## Date-Range Aggregation Contract

Range-level values must be computed from validated components, not by averaging displayed period values.

| Metric family | Safe range behavior | Unsafe default |
|---|---|---|
| Additive metrics | Sum available periods. | Treat missing periods as zero without policy. |
| Margin percentage | Sum margin numerator and revenue denominator, then divide. | Mean monthly margin percentages. |
| Distribution | Recompute from declared distinct-store numerator and active-store denominator for the selected range, or mark range value unsupported until declared. | Mean monthly distribution. |
| Velocity | Recompute from range numerator and distinct selling-store denominator, or return period series only if range semantics are not declared. | Mean monthly or SKU velocity. |
| Weighted price | Sum weighted numerator and weight denominator, then divide. | Arithmetic mean SKU or period prices. |
| Shares | Recompute numerator and denominator within declared share scope for selected range. | Mean monthly shares. |
| ABC | Default is period-level or selected-period SKU-within-category classification. Range-level ABC requires a declared range policy. | Combine monthly ABC labels. |
| Comparisons | Compare equivalent period or range scopes with explicit quality. | Label through-gap comparison as true MoM. |

If a metric cannot be safely aggregated for a selected range, the query response must return a limitation rather than an invented number.

## Canonical Historical Storage

Raw source files belong in file or object storage, not in the analytical database. The ledger stores object keys and hashes.

Canonical and mart datasets should be stored as durable Parquet, partitioned for pruning and audit:

```text
retailer_id
source_id
period_grain
period_start
analysis_run_id or mart_build_id
```

DuckDB is the preferred local query and compute engine over Parquet for the current project scale. It can also materialize small helper tables for interactive dashboard queries. Parquet remains the durable analytical storage format.

## Dashboard Mart Datasets

The mart is a set of logical datasets, not a UI schema:

```text
mart_metric_facts
mart_metric_components
mart_comparison_facts
mart_entity_dimension
mart_period_dimension
mart_benchmark_facts
mart_event_facts
mart_quality_facts
mart_source_ledger
mart_run_metadata
mart_metric_catalog
```

Physical implementation may use Parquet files, DuckDB views, DuckDB tables, or a hybrid. The logical contract is more important than the initial physical layout.

## Metric Fact Contract

Primary metric facts should use a long model:

```text
retailer_id
source_id
source_revision_id
analysis_run_id
mart_build_id
period_grain
period_start
period_end
business_period_id
grain_id
entity_id
parent_entity_ids
metric_concept
metric_name
metric_definition_id
metric_definition_version
metric_config_hash
semantic_family
semantic_compatibility_version
cross_retailer_comparable
value
numerator_value
denominator_value
aggregation
range_aggregation_strategy
share_scope
rule_version
quality_status
quality_flags
created_at
```

Wide projections may be derived for dashboard performance, but they must preserve lineage and must not become the source of business formulas.

## Metric Catalog Contract

The catalog has public and private layers.

Public catalog fields:

```text
metric_concept
default_display_label
description
format
dashboard_group
default_range_aggregation_strategy
default_comparison_support
generic_limitations
```

Private retailer catalog fields:

```text
retailer_id
source_id
metric_definition_id
metric_definition_version
metric_concept
display_label
description_override
format_override
grain_support
period_support
comparison_support
range_aggregation_strategy
share_scope
semantic_definition_ref
semantic_family
semantic_compatibility_version
cross_retailer_comparable
availability_status
limitations
rule_version
metric_config_hash
```

The public catalog may describe generic UI behavior. Private configuration decides which metrics are actually available and what their exact definitions mean.

## Dashboard Query Contract

Minimum request fields:

```text
retailer_id
source_id
date_from
date_to
period_mode
period_grain
grain_id
entity_filters
metric_concepts
metric_definition_ids
comparison_mode
ownership_scope
quality_policy
include_lineage
```

Minimum response fields:

```text
requested_range
available_periods
missing_periods
coverage_ratio
coverage_status
values
comparisons
benchmark_context
events
quality_flags
metric_definition_lineage
analysis_run_ids
mart_build_id
limitations
```

The query layer may filter, select, and aggregate according to declared strategies. It must not invent formulas.

## Entity Hierarchy

Supported dashboard grains:

```text
network
category
manufacturer
brand
sku
store
```

Entity identity contract:

```text
retailer_id
source_id
grain_id
entity_id
parent_entity_ids
entity_display_label
valid_from
valid_to
source_revision_id
quality_status
```

Retailer-specific hierarchy semantics stay private. Public code treats hierarchy fields generically.

## Versioning and Reprocessing

Historical facts are immutable by run. Changes to source mapping, tax rules, store aliases, metric rules, ownership rules, peer rules, or event rules create new analysis runs and potentially new mart builds.

Current dashboard mode selects the active approved source revisions and active approved analysis or mart build. Audit mode may query older runs.

No process may silently overwrite historical meaning.

## Incremental Processing

Incremental processing should invalidate only affected partitions:

```text
source revision
-> affected canonical partitions
-> affected metric periods/entities
-> affected comparisons
-> affected benchmarks
-> affected event facts
-> affected mart build partitions
```

Daily feeds should process new or changed source partitions without reparsing unrelated historical raw files.

## Large-File Storage Strategy

Planning assumptions include many source feeds, mixed daily/monthly cadence, and large source files.

Use:

```text
raw file/object storage = immutable source artifacts
Parquet = durable analytical canonical and mart storage
DuckDB = local analytical query/compute engine
private config backup = rule and semantic reproducibility
```

Avoid repeated XLSX parsing for dashboard requests. Parse raw sources once per registered revision, then operate on canonical and mart Parquet.

## Retention and Backup

Retention is an operational policy, not a hardcoded business rule.

Configurable retention classes:

```text
raw hot retention
raw archive retention
canonical retention
mart retention
audit metadata retention
private config retention
```

Backup scope:

```text
raw object storage
canonical Parquet
mart Parquet or DuckDB files
source ledger
run metadata
private configuration
application configuration
```

Restore must be possible for an ordinary system administrator: restore raw files, Parquet/mart files, metadata, and private config, then rebuild affected marts if needed.

## Operational Simplicity

The architecture is compatible with a low-maintenance deployment:

```text
one application host
Docker Compose or managed equivalent
object or file storage
persistent data volume
reverse proxy
basic health checks and monitoring
scheduled jobs
```

It does not require microservices, a message broker, distributed database, or clustered compute for the current planning scenario.

## Future Recommendation Context

Recommendations must be generated from the same deterministic selected scope visible to the dashboard.

Recommendation context fields:

```text
retailer_id
source_id
selected_date_range
available_periods
coverage_status
grain_id
entity_scope
metric_facts
comparison_facts
benchmark_facts
event_facts
quality_constraints
business_rule_versions
analysis_run_ids
mart_build_id
```

Recommendation identity fields:

```text
recommendation_run_id
retailer_id
selected_scope_hash
date_range
analysis_run_ids
mart_build_id
decision_rule_version
llm_model_version
generated_at
evidence_refs
quality_status
```

Changing the selected period or entity scope creates a different recommendation context. Recommendation text must not be treated as timeless or scope-free.

## Current Code Reuse Matrix

| Current component | Decision | Notes |
|---|---|---|
| `AnalysisContext` | EXTEND_LATER | Reuse existing run, retailer, source, source version, and rule version fields. Add or pair later with source revision and mart build identity. |
| Metric definitions | REUSE | Definition id/version, aggregation, grain, scope filters, config hash, `grain_id`, and numerator/denominator fields align with mart metric facts. Add range policy later. |
| Comparison contracts | EXTEND_LATER | Existing period comparison can be reused for period facts. Arbitrary selected ranges need a separate range comparison contract. |
| Benchmarking lineage | REUSE | Existing benchmarking outputs preserve scope, rule, and metric lineage. |
| Event contracts | REUSE | Event facts are deterministic and lineage-aware. Future recommendation layer should consume them as evidence. |
| Source profile and ingestion metadata | EXTEND_LATER | Existing profiles and metadata are a base. Add source ledger, revision, active flag, and period coverage contracts. |
| Config manifest/versioning | EXTEND_LATER | Existing private manifest pattern is compatible. Add public schema docs and private manifest sections for source revisions and mart builds. |
| Public/private boundary | REUSE | Existing README policy remains authoritative. |
| Conflicts | none | Current gaps are missing historical mart contracts, not contradictions. |

## Dashboard MVP Path

1. Define source ledger and active revision schema.
2. Implement mart metric fact builder from approved deterministic outputs.
3. Add metric catalog loading with public defaults and private retailer overrides.
4. Implement dashboard query service over DuckDB/Parquet mart facts.
5. Add coverage-aware date-range aggregation and comparison responses.
6. Build the first dashboard UI against the query contract.
7. Add recommendation context builder from deterministic mart evidence.

Only steps 1 through 5 are mandatory before the first useful dashboard data API. UI framework selection is a separate decision.

## Non-Responsibilities

This architecture checkpoint does not implement:

```text
Dashboard UI
production mart builder
direct peer flavor remediation
EDLP/stability rules
promo effectiveness
recommendation/top-N engine
LLM integration
cross-retailer semantic compatibility declarations
```
