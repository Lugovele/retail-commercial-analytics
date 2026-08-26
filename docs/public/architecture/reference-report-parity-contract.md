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

- private alias semantics;
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

## Dashboard Placement And Visual Contracts

When the private registry declares a metric placement contract and a visual
semantics contract, meaningful dashboard UI or parity work must consult both
contracts before implementation.

The durable source-of-truth hierarchy is:

1. deterministic business rules and metric definitions: calculation truth;
2. private metric placement contract: analytical origin, primary home,
   representation and coverage truth;
3. private visual semantics contract: presentation priority and reading
   semantics;
4. public visualization, screen and presentation policy: retailer-neutral
   implementation constraints;
5. current UI implementation: implementation evidence, not authority.

The placement contract and visual semantics contract have distinct roles. The
placement contract answers what must exist, where it belongs, how it is
represented, and whether coverage is visible, backend-only, partial, a gap, or
unresolved. The visual semantics contract answers how the selected
representation should communicate current/reference hierarchy, deltas, rank,
share, classification, ownership, attention, data quality and limitations.

The standard placement origin vocabulary is:

- `XLSX`
- `XLSX→WEB`
- `WEB-DERIVED`
- `WEB-AUDIT`
- `XLSX-UNRESOLVED`

Web-derived and web-audit concepts must not be described as legacy spreadsheet
KPIs. Spreadsheet-unresolved concepts fail closed: they may be shown as a calm
limitation or future placeholder, but must not render approximate calculations,
guessed denominators, legacy labels over different metrics, or silent
substitutions.

The standard placement implementation status vocabulary is:

- `VISIBLE`
- `BACKEND_READY`
- `BACKEND_ONLY`
- `PARTIAL`
- `GAP`
- `UNRESOLVED`
- `NOT_APPLICABLE`

Backend readiness is not visible parity. A concept is web-present only when
semantics are approved, backend or query support exists where needed, the
concept is reachable in its primary home, the representation communicates the
business question, relevant filters and scopes work, unsupported combinations
surface explicit limitations, and Inspector/provenance exists where complexity
requires it.

Repeating a label, adding a heading, duplicating an already visible value,
adding a tiny badge, or adding explanatory text without the underlying analytics
does not count as parity implementation.

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

For meaningful dashboard UI/parity work, the lifecycle also requires a pre-code
design table:

```text
Concept | Origin | Primary Home | Current Status | Target Representation | Backend Ready? | Change Needed
```

After implementation it requires a rendered acceptance table:

```text
Concept | Before | After | Browser Visible? | Correct Scope? | Representation | Remaining Limitation
```

The post-code table must be based on rendered private acceptance when UI parity
is claimed, not source inspection alone.

Trivial CSS or purely cosmetic work does not require a full workbook re-audit.

## Reviewer Responsibilities

Senior FMCG and business review owns commercial analytical content parity.
Product information architecture owns whether each approved concept has a clear
web home. BI and UI review owns improved presentation without lost analytical
access. Architecture review owns safe boundaries and avoiding duplicate semantic
truth. Business-rules review owns the rule that reference evidence never
substitutes for confirmed calculation semantics. Change review owns detection of
silent parity regression.

Product information architecture also owns the one-primary-home rule,
representation type and avoidance of redundant cross-screen duplication. BI/UI
review verifies that the visual semantics contract is preserved without
spreadsheet replication. Change review rejects superficial implementation
status changes where analytical access is not actually visible.

Private reference reports may supply candidate familiar terminology for later
explicit alias configuration. This contract does not implement terminology
aliases.
