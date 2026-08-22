from datetime import date

import polars as pl

from retail_analytics.core.comparisons.engine import ComparisonRequest, compare_periods
from retail_analytics.core.comparisons.period_index import build_period_index
from retail_analytics.core.scoring.abc import calculate_abc
from retail_analytics.pipeline.context import AnalysisContext


def _context(retailer_id: str = "retailer_a") -> AnalysisContext:
    return AnalysisContext("run_a", retailer_id, "source_a", "v1", "rules_v1")


def _metric_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["run_a"] * 8,
            "retailer_id": ["retailer_a"] * 7 + ["retailer_b"],
            "source_id": ["source_a"] * 8,
            "period": [
                date(2025, 1, 1),
                date(2025, 12, 1),
                date(2026, 1, 1),
                date(2026, 3, 1),
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 1),
            ],
            "category": ["CATEGORY_STANDARD"] * 8,
            "entity_type": ["sku"] * 8,
            "entity_id": ["SKU_A_001", "SKU_A_001", "SKU_A_001", "SKU_A_001", "SKU_A_002", "SKU_A_003", "SKU_A_004", "SKU_A_001"],
            "concept": ["revenue"] * 8,
            "metric_name": ["revenue_net"] * 8,
            "metric_definition_id": ["retailer_a.revenue_net.v1"] * 7 + ["retailer_b.revenue_net.v1"],
            "metric_definition_version": ["v1"] * 8,
            "metric_config_hash": ["hash"] * 8,
            "metric_value": [100.0, 120.0, 150.0, 180.0, 30.0, 20.0, -5.0, 999.0],
        }
    )


def test_period_index_offsets():
    index = build_period_index([date(2026, 1, 1), date(2026, 3, 1)])

    assert index.previous_calendar_month(date(2026, 1, 1)) == date(2025, 12, 1)
    assert index.same_month_previous_year(date(2026, 1, 1)) == date(2025, 1, 1)
    assert index.previous_available_period(date(2026, 3, 1)) == date(2026, 1, 1)
    assert index.month_gap(date(2026, 3, 1), date(2026, 1, 1)) == 2


def test_yoy_uses_same_calendar_month():
    result = compare_periods(_metric_frame(), (ComparisonRequest("YOY", date(2026, 1, 1)),), _context())

    row = result.comparisons.filter(pl.col("entity_id") == "SKU_A_001")
    assert row["reference_period"].to_list() == [date(2025, 1, 1)]
    assert row["comparison_quality"].to_list() == ["HIGH"]


def test_mom_requires_contiguous_month():
    result = compare_periods(_metric_frame(), (ComparisonRequest("MOM", date(2026, 1, 1)),), _context())

    assert result.comparisons.filter(pl.col("entity_id") == "SKU_A_001")["reference_period"].to_list() == [date(2025, 12, 1)]


def test_gap_period_is_previous_available_not_mom():
    mom = compare_periods(_metric_frame(), (ComparisonRequest("MOM", date(2026, 3, 1)),), _context())
    previous = compare_periods(_metric_frame(), (ComparisonRequest("PREVIOUS_AVAILABLE", date(2026, 3, 1)),), _context())

    assert mom.comparisons.is_empty()
    assert previous.comparisons["month_gap"].to_list() == [2]
    assert previous.comparisons["comparison_quality"].to_list() == ["MEDIUM"]


def test_missing_yoy_base_is_structured():
    result = compare_periods(_metric_frame(), (ComparisonRequest("YOY", date(2026, 3, 1)),), _context())

    assert result.comparisons.is_empty()
    assert result.quality_report.issues[0].issue_code == "MISSING_COMPARISON_BASE"


def test_delta_abs_and_pct():
    result = compare_periods(_metric_frame(), (ComparisonRequest("YOY", date(2026, 1, 1)),), _context())
    row = result.comparisons.filter(pl.col("entity_id") == "SKU_A_001")

    assert row["delta_abs"].to_list() == [50.0]
    assert row["delta_pct"].to_list() == [0.5]


def test_percentage_metric_delta_pp():
    frame = _metric_frame().with_columns(
        pl.lit("distribution").alias("concept"),
        pl.lit("retailer_a.numeric_distribution.v1").alias("metric_definition_id"),
    )
    result = compare_periods(frame, (ComparisonRequest("YOY", date(2026, 1, 1)),), _context())
    row = result.comparisons.filter(pl.col("entity_id") == "SKU_A_001")

    assert row["delta_pp"].to_list() == [50.0]


def test_absolute_metric_delta_pp_is_null():
    result = compare_periods(_metric_frame(), (ComparisonRequest("YOY", date(2026, 1, 1)),), _context())
    row = result.comparisons.filter(pl.col("entity_id") == "SKU_A_001")

    assert row["delta_pp"].to_list() == [None]


def test_comparisons_do_not_cross_retailer_boundary():
    result = compare_periods(_metric_frame(), (ComparisonRequest("YOY", date(2026, 1, 1)),), _context("retailer_b"))

    assert result.comparisons.is_empty()


def test_abc_revenue_uses_80_15_5():
    result = calculate_abc(_metric_frame().filter(pl.col("period") == date(2026, 1, 1)))
    retailer_a = result.classifications.filter(pl.col("retailer_id") == "retailer_a")

    assert retailer_a.filter(pl.col("entity_id") == "SKU_A_001")["abc_class"].to_list() == ["A"]
    assert retailer_a.filter(pl.col("entity_id") == "SKU_A_002")["abc_class"].to_list() == ["B"]
    assert retailer_a.filter(pl.col("entity_id") == "SKU_A_003")["abc_class"].to_list() == ["C"]


def test_abc_negative_value_policy():
    result = calculate_abc(_metric_frame().filter(pl.col("period") == date(2026, 1, 1)))

    assert result.classifications.filter(pl.col("entity_id") == "SKU_A_004")["abc_class"].to_list() == ["NEGATIVE_OR_CORRECTION"]
    assert result.quality_report.issues[0].issue_code == "NEGATIVE_ABC_CONTRIBUTION"


def test_abc_exposes_cumulative_share():
    result = calculate_abc(_metric_frame().filter(pl.col("period") == date(2026, 1, 1)))

    assert "cumulative_share" in result.classifications.columns


def test_abc_does_not_cross_retailer_boundary():
    result = calculate_abc(_metric_frame())

    retailer_b = result.classifications.filter(pl.col("retailer_id") == "retailer_b")
    assert retailer_b["abc_class"].to_list() == ["A"]
