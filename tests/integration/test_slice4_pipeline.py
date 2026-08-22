from datetime import date

import polars as pl

from retail_analytics.core.comparisons.engine import ComparisonRequest, compare_periods
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.pipeline.slice4 import run_slice4_event_engine


def test_slice4_end_to_end_deterministic_events():
    context = AnalysisContext("run_a", "retailer_a", "source_a", "v1", "rules_v1")
    comparisons = compare_periods(
        _metrics(),
        (ComparisonRequest("YOY", date(2026, 2, 1)),),
        context,
    ).comparisons
    result = run_slice4_event_engine(
        comparisons=comparisons,
        abc=_abc(),
        benchmark_features=_benchmark(),
        event_rules="config/public/demo/event_rules.yaml",
        context=context,
    )

    assert not result.events.is_empty()
    assert "MATERIAL_REVENUE_DECLINE" in result.events["event_type"].to_list()
    assert "PRICE_PRESSURE_PATTERN" in result.events["event_type"].to_list()
    assert set(result.events["retailer_id"].unique().to_list()) == {"retailer_a"}
    assert result.quality_report.is_valid


def _metrics() -> pl.DataFrame:
    rows = []
    for period, revenue, units, price, velocity, distribution in (
        (date(2025, 2, 1), 100.0, 100.0, 10.0, 10.0, 0.80),
        (date(2026, 2, 1), 90.0, 120.0, 12.0, 8.0, 0.79),
    ):
        rows.extend(
            [
                _metric_row(period, "revenue", "revenue_net", revenue),
                _metric_row(period, "units", "units", units),
                _metric_row(period, "weighted_shelf_price_vat", "weighted_shelf_price_vat", price),
                _metric_row(period, "velocity", "units_per_selling_store", velocity),
                _metric_row(period, "distribution", "numeric_distribution", distribution),
            ]
        )
    return pl.DataFrame(rows)


def _metric_row(period: date, concept: str, metric_name: str, value: float) -> dict[str, object]:
    return {
        "analysis_run_id": "run_a",
        "retailer_id": "retailer_a",
        "source_id": "source_a",
        "rule_version": "rules_v1",
        "period": period,
        "category": "CATEGORY_A",
        "entity_type": "sku",
        "entity_id": "SKU_A_001",
        "concept": concept,
        "metric_name": metric_name,
        "metric_definition_id": f"retailer_a.{metric_name}.v1",
        "metric_definition_version": "v1",
        "metric_config_hash": "metric_hash",
        "metric_value": value,
    }


def _abc() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["run_a"],
            "retailer_id": ["retailer_a"],
            "source_id": ["source_a"],
            "rule_version": ["rules_v1"],
            "period": [date(2026, 2, 1)],
            "reference_period": [date(2025, 2, 1)],
            "category": ["CATEGORY_A"],
            "entity_type": ["sku"],
            "entity_id": ["SKU_A_001"],
            "abc_metric": ["abc_revenue"],
            "abc_class": ["B"],
            "reference_abc_class": ["A"],
        }
    )


def _benchmark() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["run_a"],
            "retailer_id": ["retailer_a"],
            "source_id": ["source_a"],
            "rule_version": ["rules_v1"],
            "reference_period": [date(2026, 2, 1)],
            "target_entity_id": ["SKU_A_001"],
            "entity_type": ["sku"],
            "category": ["CATEGORY_A"],
            "benchmark_scope": ["BROAD_CATEGORY"],
            "benchmark_scope_id": ["scope_a"],
            "pool_source": ["CATEGORY_POOL"],
            "metric_name": ["revenue_net"],
            "metric_definition_id": ["retailer_a.revenue_net.v1"],
            "metric_definition_version": ["v1"],
            "metric_value": [90.0],
            "rank": [1],
            "percentile": [0.90],
            "population_size": [5],
        }
    )
