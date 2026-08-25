# Filterable Product x Store Serving Layer

Status: READY for approved dashboard query intersections.

## Purpose

The dashboard can combine product filters and store filters in one analytical scope. Store is an orthogonal filter axis: OR within a filter, AND across filters. The ordinary `mart_metric_facts` surface remains the canonical fast path for standard dashboard grains. Product x store intersections use a separate backend serving fact at internal grain `sku_store`.

## Supported Semantics

The serving layer supports metrics that can be safely recomputed from SKU x store period facts:

- `revenue_vat`: sum
- `revenue`: sum
- `units`: sum
- `retailer_margin_abs`: sum
- `retailer_margin_pct`: ratio of summed margin to summed revenue
- `weighted_shelf_price_vat`: weighted ratio of summed price numerator to summed units
- `weighted_input_price_vat`: weighted ratio of summed price numerator to summed units

The frontend must not calculate these values. It sends the selected analytical scope to the dashboard query route and renders backend results.

## Unsupported In This Layer

The serving layer must not roll up distinct-count, presence, velocity, share, rank, contribution, ABC, portfolio, or signal concepts unless a metric-specific recomputation contract is added later. Unsupported concepts return explicit query limitations instead of synthetic values.

## Period And Sparse Data

Only available persisted periods are represented. Missing months are not zero-filled. Single-period, comparison, and selected-range behavior follows each metric's declared range aggregation strategy.

## Provenance

Rows returned through this path include provenance with:

- `scoped_rollup.status = DERIVED_FROM_PRODUCT_STORE_FACTS`
- `source_fact_grain = sku_store`
- requested grain
- execution entity filters
- private label scope
- mart build id
- analysis run ids
- source revision ids
- metric definition identity

Source row identifiers remain unavailable in normal dashboard provenance; the evidence status is partial aggregated fact evidence.
