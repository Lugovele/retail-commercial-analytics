# Deterministic Signal Feed

This contract defines how dashboard signal data is exposed to product screens.
It is intentionally narrower than the raw event-fact taxonomy.

## Product Buckets

The dashboard signal route separates four concepts:

| Bucket | Meaning | User-facing role |
|---|---|---|
| `COMMERCIAL_SIGNAL` | Confirmed event produced by an enabled deterministic business rule and approved for commercial attention. | "Что требует внимания?" |
| `DETERMINISTIC_PATTERN` | Deterministic pattern candidate that is observable but not causal. | Analyst review / evidence. |
| `DATA_QUALITY_ALERT` | Data quality issue that affects trust or coverage. | Data-quality section, not commercial signal. |
| `CAPABILITY_LIMITATION` | Supported boundary or missing capability. | Limitation notice, never an alert about business performance. |

Capability limitations must not be mixed into commercial signals.

## Route

Product screens use:

```text
POST /api/dashboard/signals
```

The route reads persisted confirmed event outputs. It does not create new events
from ordinary metric deltas and does not run frontend formulas. Commercial
signals, deterministic patterns, data-quality alerts, and capability limitations
are returned in separate arrays.

## Signal Row Contract

Each surfaced signal or pattern row carries:

- signal identity;
- signal bucket;
- event type and family;
- object grain and identifier;
- period and reference period where applicable;
- current value, reference value, and delta fields produced by the event engine;
- deterministic rule identity and config hash;
- severity, priority, confidence, and comparison quality;
- requested private-label scope;
- structured provenance.

The route returns empty signal lists when no confirmed events exist. Empty is a
valid product state.

If confirmed event rows exist but are excluded by product surfacing rules, the
route returns `NO_SURFACED_SIGNALS` rather than claiming there were no confirmed
events.

## Provenance

Signal provenance includes:

- selected analytical scope;
- affected object;
- period and comparison;
- rule identity;
- thresholds and trigger values;
- metric or benchmark lineage when present;
- analysis run and mart build;
- source evidence status;
- quality and missing fields.

Source-row identifiers are not promised by this route. When only aggregated
facts are available, the source evidence status remains partial.

## Surfacing Rules

Commercial signal rows may be surfaced only from enabled deterministic rules
whose event family is product-approved for commercial attention.

The initial commercial families are:

- `GROWTH_DECLINE`;
- `DISTRIBUTION`;
- `VELOCITY`;
- `SHARE`;
- `PRICE`;
- `MARGIN_PCT`.

`PATTERN_CANDIDATE` is surfaced as `DETERMINISTIC_PATTERN`, not as a commercial
signal.

The following are not surfaced as ready commercial signals in this contract:

- ordinary metric deltas without an event rule;
- recommendations;
- causal explanations;
- brand Growth/Decline/Critical composite statuses;
- delisting;
- direct peers that require unresolved flavor semantics;
- promo effectiveness;
- `PROMO_LIKE_PATTERN`;
- `ABC_CLASS_CHANGE`;
- `PERSISTENT_C_CLASS`;
- `BENCHMARK` family events without separate benchmark-scope approval.

## Private-Label Scope

Requests and responses carry the requested private-label scope. If persisted
event outputs do not contain a materialized private-label scope column, the
route returns an explicit limitation instead of pretending that the signal is
scope-specific.

## Empty Feed

An empty confirmed event output is not a failure. Product UI should show a calm
empty state such as:

```text
Для выбранного среза нет подтверждённых сигналов.
```

It must not fabricate examples or recommendations.
