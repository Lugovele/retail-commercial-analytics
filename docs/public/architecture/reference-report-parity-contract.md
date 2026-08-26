# Reference Report Parity Contract

Version: `reference-report-parity-v1`

This public contract defines how a retailer implementation may use one or more
private analytical reference reports as durable Excel-to-web parity evidence. It
is retailer-neutral and contains no private report names, file names, source
values, stores, products, or client identifiers.

The machine-readable contract lives at:

```text
config/public/reference_report_parity_contract.yaml
```

## Registry

Private reference reports are registered only in ignored private configuration.
Tracked files may define the registry schema and rules, but must not contain
real report names, workbook names, private source paths, retailer names, brands,
products, stores, or source values.

Each private registry entry identifies the report, its private path, status,
whether parity is required, the private audit artifacts that support it, and the
governance purposes it serves.

## Core Rule

When a private analytical reference report is registered, analytically useful
commercial content available in that report must remain accessible in the web
product unless one of these public-safe exceptions applies:

- business rules explicitly reject it;
- the source cannot support it;
- semantic reconciliation is unresolved.

Analytical content parity is required. Layout parity is not required.

The web product may improve presentation through visualization, dynamic scopes,
drilldown, progressive disclosure, grouped or optional columns, interactive
comparison, and the Metric Inspector. It must not reproduce spreadsheet layout
merely for parity.

## Evidence Boundary

Reference reports are evidence of business usage, not executable calculation
authority.

Never parse report formulas, thresholds, labels, classifications, or implied
semantics directly into production logic without an explicit deterministic
business-rule contract.

Presence in a reference report does not automatically approve:

- VPO semantics;
- distribution semantics;
- ranking universe;
- ABC formula;
- averaging rules;
- causal conclusions.

Business rules and reconciled deterministic metric definitions remain the
calculation authority.

## Parity Status Model

The standard parity status vocabulary is:

- `EXACT_PARITY`
- `PARTIAL_PARITY`
- `BACKEND_READY_UI_MISSING`
- `BACKEND_MISSING`
- `SEMANTIC_RECONCILIATION_REQUIRED`
- `BUSINESS_RULE_REQUIRED`
- `SOURCE_MAPPING_REQUIRED`
- `NOT_APPLICABLE`
- `INTENTIONALLY_IMPROVED_PRESENTATION`

## Change Lifecycle

Meaningful analytical or product-semantic changes must consider registered
private reference reports. The lifecycle asks:

1. Is a private reference analytical report registered?
2. Which parity concepts are affected?
3. Does this change remove or degrade existing analytical access?
4. Does it introduce or reinterpret semantics needing reconciliation?
5. Is any parity gap intentionally unresolved and correctly surfaced?

This applies to metric additions or removals, comparison semantics, dashboard
screen capability, filters and dimensions, Portfolio, Sales Drivers, tables,
ranking, share, ABC, and Metric Inspector definitions.

Trivial CSS or purely cosmetic work does not require a full workbook re-audit.

## Reviewer Responsibilities

Senior FMCG and business review owns commercial analytical content parity.
Product information architecture owns whether each approved concept has a clear
web home. BI and UI review owns improved presentation without lost analytical
access. Architecture review owns safe boundaries and avoiding duplicate semantic
truth. Business-rules review owns the rule that reference evidence never
substitutes for confirmed calculation semantics. Change review owns detection of
silent parity regression.

Private reference reports may supply candidate familiar terminology for later
explicit alias configuration. This contract does not implement terminology
aliases.
