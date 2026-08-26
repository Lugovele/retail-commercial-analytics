# Available-Month Comparison Contract

Status: approved backend contract with limitations.

This contract defines retailer-neutral semantics for comparing period sets that contain only months actually present in the source. It exists to support the business pattern commonly worded as "average over available months" without creating unsafe mean-of-ratios behavior.

## Period Scope

`AVAILABLE_MONTH_SET` is a non-contiguous monthly period scope. It carries:

- included business periods;
- included month numbers and labels;
- coverage count;
- comparison policy;
- source revision and mart lineage.

It must not be labelled as YTD, 6M, H1, rolling, or another continuous-period concept unless the underlying months are complete and contiguous under a separate rule.

## Comparison Policy

The default year-over-year comparison policy is `MATCHED_AVAILABLE_MONTHS`.

When the current side and reference side have different available month composition, the backend compares the intersection of month numbers. For example, if one side has March, April, June, September, and December, and the other side has March, April, and June, the comparable set is March, April, and June on both sides.

`ALL_AVAILABLE_MONTHS_PER_SIDE` remains a documented alternative only when a future business rule explicitly approves comparing structurally different seasonal sets. The backend must not silently use it.

## Metric Aggregation Matrix

| Metric family | Available-month semantics | Backend readiness | Delta semantics | Limitations |
| --- | --- | --- | --- | --- |
| Revenue | Arithmetic mean of monthly totals over included months. | Ready from existing additive facts. | Relative percent. | This answers "average available month", not total period result. |
| Revenue VAT | Arithmetic mean of monthly totals over included months. | Ready from existing additive facts. | Relative percent. | Same as revenue. |
| Units | Arithmetic mean of monthly totals over included months. | Ready from existing additive facts. | Relative percent. | Same as revenue. |
| Absolute margin | Arithmetic mean of monthly totals over included months. | Ready from existing additive facts. | Relative percent. | Same as revenue. |
| Margin % | Ratio of summed absolute margin to summed revenue over included months. | Ready from existing components. | Percentage points. | Monthly margin percentages are never averaged. |
| Weighted shelf price | Sum weighted-price numerator divided by sum weight over included months. | Ready from existing components. | Neutral absolute/percent context. | Monthly prices are not unweighted-averaged. |
| Weighted input price | Sum weighted-price numerator divided by sum weight over included months. | Ready from existing components. | Neutral absolute/percent context. | Monthly prices are not unweighted-averaged. |
| Share | Sum entity basis over included months divided by sum universe basis over included months. | Ready where declared share components and scope exist. | Percentage points. | Monthly shares are never averaged. |
| Cumulative share | Rank once from aggregated available-month additive values, then cumulative share once. | Ready in Portfolio projections for point set. | Point set only. | Cumulative-share movement across period sets needs a separate route. |
| Rank | Rank once from aggregated available-month additive values. | Ready in Portfolio projections for point set. | Positions only when a set movement route is approved. | Monthly ranks are never averaged. |
| ABC | For approved year scope, aggregate the basis over available months, then rank/share/cumulative/ABC once. | Ready for approved Portfolio ABC point set. | Classification, not averaged. | No custom arbitrary range ABC. |
| Velocity | Point-in-time only. | Unsupported for available-month set. | Neutral. | Do not average monthly velocity without a deterministic exposure rule. |
| Distribution | Point-in-time only. | Unsupported for available-month set. | Neutral percentage points in point comparisons only. | Do not average monthly distribution. |
| Store counts | Business rule required. | Unsupported for available-month set. | Neutral. | Average monthly count, distinct stores across set, and store-month exposure are separate metrics. |
| Assortment counts | Business rule required. | Unsupported for available-month set. | Neutral. | Average active assortment and distinct observed assortment are separate metrics. |

## Provenance

Every available-month value must expose:

- `scope_type = AVAILABLE_MONTH_SET`;
- included periods and month numbers;
- coverage count;
- aggregation method;
- comparison policy;
- matched or unmatched month treatment;
- metric definition and rule version;
- source revision and mart lineage;
- numerator and denominator components when used.

## Guardrails

The backend must not:

- arithmetic-average monthly margin %, shares, distribution, velocity, ranks, cumulative shares, or ABC classes;
- compare unmatched seasonal month sets without an explicit policy;
- present sparse period sets as continuous YTD or rolling periods;
- copy a reference report calculation pattern when it conflicts with deterministic business-rule authority.
