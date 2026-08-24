# Additive Contribution / Impact Model

This document defines the publication-safe dashboard contract for additive
contribution to a selected comparison-period delta.

It does not define new commercial formulas. It derives a table-ready diagnostic
view from already approved additive mart facts.

## Purpose

The dashboard question is:

```text
Which child entities contributed most to the selected additive metric change?
```

User-facing wording:

```text
Вклад в изменение
```

The wording is intentionally neutral. It must not imply causality or commercial
good/bad judgment.

## Supported Metrics

Initial supported additive metrics:

- `revenue_vat`
- `revenue`
- `units`
- `retailer_margin_abs`

The model is not applicable to ratios, weighted metrics, period-only metrics,
shares, ranks, ABC, or signals.

## Supported Hierarchy Scopes

Contribution is calculated only where the existing mart facts carry a safe
parent/child relationship:

- `network -> category`
- `category -> manufacturer`
- `category -> brand`
- `category -> sku`

Other drill-down pairs require a future explicit hierarchy bridge or projection
contract. The dashboard must fall back to a neutral table and must not present
an impact ranking for unsupported pairs.

## Formula

For each child entity:

```text
child_delta = child_current_value - child_reference_value
absolute_delta = abs(child_delta)
```

For the parent scope:

```text
parent_delta = parent_current_value - parent_reference_value
```

If `parent_delta != 0`:

```text
contribution_share = child_delta / parent_delta
```

Default sorting:

```text
absolute_delta DESC
current_value DESC
child_entity_id ASC
```

## Mixed Signs

Contribution shares are signed and are not clamped to `0..100%`.

Example:

```text
parent_delta = -10
child A delta = -15 => contribution_share = 150%
child B delta = +5  => contribution_share = -50%
```

This is expected when some entities offset the total movement. The UI should
explain:

```text
Вклад может быть выше 100% или отрицательным, если объекты компенсируют изменение.
```

## Zero Parent Delta

If `parent_delta == 0`, contribution share is undefined.

The backend returns:

```text
contribution_share = null
status = TOTAL_DELTA_ZERO
```

The UI should say:

```text
Вклад в общее изменение не рассчитывается: итоговое изменение равно нулю.
```

It must not show `0%`.

## Missing Entities

For additive facts, a child present in one of the two comparison periods may be
treated as zero in the other period only when both parent periods are available
for the selected analytical universe.

If the parent current or reference period is missing, contribution is not
calculated and the response must expose an insufficient-comparison status.

## Provenance

Each contribution row should expose:

- selected analytical scope;
- parent grain/entity;
- child grain/entity;
- metric concept and metric definition lineage for parent and child facts;
- current value;
- reference value;
- child delta;
- parent delta;
- contribution formula;
- contribution share;
- comparison quality/status;
- analysis run;
- mart build;
- source revision.

Source-row IDs are not fabricated for aggregated facts.

## Future Decomposition

The following metric families require separate decomposition rules before they
can have a first-class contribution model:

- margin percentage;
- weighted shelf/input prices;
- shares;
- distribution;
- velocity;
- ranks;
- ABC;
- signals.
