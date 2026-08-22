from datetime import date

import polars as pl

from retail_analytics.core.comparisons.engine import ComparisonRequest
from retail_analytics.economics.tax import TaxRule
from retail_analytics.metrics.registry import MetricDefinition, MetricRegistry
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.pipeline.slice1b import run_slice1b_normalization
from retail_analytics.pipeline.slice2 import run_slice2_metrics


def test_slice2_end_to_end_metrics_comparisons_and_abc():
    context = AnalysisContext("run_a", "retailer_a", "source_a", "v1", "rules_v1")
    canonical = _canonical_fixture()
    tax_rules = (
        TaxRule("standard_rate", date(2025, 1, 1), None, 0.20, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_a"),
    )
    enriched = run_slice1b_normalization(canonical_frame=canonical, tax_rules=tax_rules, context=context).enriched_frame

    result = run_slice2_metrics(
        enriched_frame=enriched,
        metric_definitions=_registry("retailer_a", "hash_a"),
        context=context,
        comparison_requests=(
            ComparisonRequest("YOY", date(2026, 1, 1)),
            ComparisonRequest("MOM", date(2026, 2, 1)),
            ComparisonRequest("PREVIOUS_AVAILABLE", date(2026, 4, 1)),
        ),
    )

    assert not result.aggregates.is_empty()
    assert not result.shares.is_empty()
    assert not result.comparisons.is_empty()
    assert not result.abc.is_empty()
    assert set(result.aggregates["retailer_id"].unique().to_list()) == {"retailer_a"}
    assert result.comparisons.filter(pl.col("comparison_type") == "YOY")["reference_period"].to_list()
    assert result.comparisons.filter(pl.col("comparison_type") == "MOM")["month_gap"].to_list()
    assert result.comparisons.filter(pl.col("comparison_type") == "PREVIOUS_AVAILABLE")["month_gap"].max() > 1


def test_same_sku_and_store_ids_across_retailers_are_not_shared():
    context_a = AnalysisContext("run_a", "retailer_a", "source_a", "v1", "rules_v1")
    context_b = AnalysisContext("run_b", "retailer_b", "source_a", "v1", "rules_v1")
    rules_a = (TaxRule("standard_a", date(2025, 1, 1), None, 0.20, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_a"),)
    rules_b = (TaxRule("standard_b", date(2025, 1, 1), None, 0.10, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_b"),)
    enriched_a = run_slice1b_normalization(canonical_frame=_canonical_fixture("retailer_a", "run_a"), tax_rules=rules_a, context=context_a).enriched_frame
    enriched_b = run_slice1b_normalization(canonical_frame=_canonical_fixture("retailer_b", "run_b"), tax_rules=rules_b, context=context_b).enriched_frame
    combined = pl.concat([enriched_a, enriched_b], how="diagonal")

    result_a = run_slice2_metrics(enriched_frame=combined, metric_definitions=_registry("retailer_a", "hash_a"), context=context_a)
    result_b = run_slice2_metrics(enriched_frame=combined, metric_definitions=_registry("retailer_b", "hash_b"), context=context_b)

    assert set(result_a.aggregates["retailer_id"].unique().to_list()) == {"retailer_a"}
    assert set(result_b.aggregates["retailer_id"].unique().to_list()) == {"retailer_b"}
    assert result_a.metric_config_hash != result_b.metric_config_hash


def _canonical_fixture(retailer_id: str = "retailer_a", analysis_run_id: str = "run_a") -> pl.DataFrame:
    periods = [
        date(2025, 1, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 4, 1),
    ]
    rows = []
    row_number = 1
    for period in periods:
        for sku, units, revenue in [
            ("SKU_A_001", 10.0, 120.0),
            ("SKU_A_002", 5.0, 72.0),
            ("SKU_A_003", -1.0, -12.0),
        ]:
            rows.append(
                {
                    "analysis_run_id": analysis_run_id,
                    "retailer_id": retailer_id,
                    "source_id": "source_a",
                    "period": period,
                    "category_group": "CATEGORY_STANDARD",
                    "category": "CATEGORY_STANDARD",
                    "brand": "BRAND_A",
                    "manufacturer": "MANUFACTURER_A",
                    "canonical_product_id": sku,
                    "canonical_store_id": "STORE_A_001",
                    "units": units,
                    "revenue_vat": revenue,
                    "shelf_price_vat": 12.0,
                    "input_price_vat": 6.0,
                    "source_row_number": row_number,
                }
            )
            row_number += 1
    return pl.DataFrame(rows)


def _registry(retailer_id: str, config_hash: str) -> MetricRegistry:
    grain = ("period", "category", "canonical_product_id")
    definitions = (
        MetricDefinition("revenue_net", "revenue", f"{retailer_id}.revenue_net.v1", "v1", "sum", source_column="revenue_net", grain=grain, retailer_id=retailer_id, rule_version="rules_v1"),
        MetricDefinition("units", "units", f"{retailer_id}.units.v1", "v1", "sum", source_column="units", grain=grain, retailer_id=retailer_id, rule_version="rules_v1"),
        MetricDefinition("retailer_margin_abs", "retailer_margin_abs", f"{retailer_id}.margin_abs.v1", "v1", "sum", source_column="retailer_margin_abs", grain=grain, retailer_id=retailer_id, rule_version="rules_v1"),
        MetricDefinition("selling_store_count", "selling_store_count", f"{retailer_id}.selling_store_count.v1", "v1", "distinct_count", distinct_column="canonical_store_id", condition={"units": {"gt": 0}}, grain=grain, retailer_id=retailer_id, rule_version="rules_v1"),
        MetricDefinition("active_store_count", "active_store_count", f"{retailer_id}.active_store_count.v1", "v1", "distinct_count", distinct_column="canonical_store_id", grain=grain, broadcast_grain=("period", "category"), retailer_id=retailer_id, rule_version="rules_v1"),
        MetricDefinition("numeric_distribution", "distribution", f"{retailer_id}.numeric_distribution.v1", "v1", "ratio_of_sums", numerator="selling_store_count", denominator="active_store_count", grain=grain, retailer_id=retailer_id, rule_version="rules_v1"),
        MetricDefinition("units_per_selling_store", "velocity", f"{retailer_id}.velocity.v1", "v1", "ratio_of_sums", numerator="units", denominator="selling_store_count", grain=grain, retailer_id=retailer_id, rule_version="rules_v1"),
    )
    return MetricRegistry(definitions, config_hash)
