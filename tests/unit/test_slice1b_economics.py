from datetime import date

import polars as pl

from retail_analytics.economics.retailer_margin import (
    aggregate_margin_pct,
    calculate_retailer_economics,
)
from retail_analytics.economics.tax import TaxRule, normalize_tax
from retail_analytics.pipeline.context import AnalysisContext


def _context() -> AnalysisContext:
    return AnalysisContext("run_a", "retailer_a", "source_a", "v1", "rules_v1")


def _taxed_frame(**overrides) -> pl.DataFrame:
    values = {
        "period": [date(2025, 1, 1)],
        "category_group": ["CATEGORY_STANDARD"],
        "units": [2.0],
        "revenue_vat": [120.0],
        "shelf_price_vat": [72.0],
        "input_price_vat": [30.0],
        "source_row_number": [1],
    }
    values.update(overrides)
    rule = TaxRule("standard_rate_2025", date(2025, 1, 1), None, 0.20, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_a")
    return normalize_tax(pl.DataFrame(values), (rule,), _context()).frame


def test_revenue_net_is_calculated_from_tax_rate():
    frame = _taxed_frame()

    assert frame["revenue_net"].to_list() == [100.0]


def test_shelf_price_net_is_calculated():
    frame = _taxed_frame()

    assert frame["shelf_price_net"].to_list() == [60.0]


def test_input_price_net_is_calculated():
    frame = _taxed_frame()

    assert frame["input_price_net"].to_list() == [25.0]


def test_margin_abs_uses_net_values():
    result = calculate_retailer_economics(_taxed_frame(), _context())

    assert result.frame["input_cost_net"].to_list() == [50.0]
    assert result.frame["retailer_margin_abs"].to_list() == [50.0]


def test_margin_pct_uses_margin_over_revenue():
    result = calculate_retailer_economics(_taxed_frame(), _context())

    assert result.frame["retailer_margin_pct"].to_list() == [0.5]


def test_markup_uses_input_price_denominator():
    result = calculate_retailer_economics(_taxed_frame(), _context())

    assert result.frame["retailer_markup_pct"].to_list() == [1.4]


def test_zero_revenue_does_not_produce_infinity():
    result = calculate_retailer_economics(_taxed_frame(revenue_vat=[0.0]), _context())

    assert result.frame["retailer_margin_pct"].to_list() == [None]
    assert any(issue.issue_code == "zero_revenue_denominator" for issue in result.quality_report.issues)


def test_zero_input_price_does_not_produce_infinity():
    result = calculate_retailer_economics(_taxed_frame(input_price_vat=[0.0]), _context())

    assert result.frame["retailer_markup_pct"].to_list() == [None]
    assert any(issue.issue_code == "zero_input_price_denominator" for issue in result.quality_report.issues)


def test_aggregate_margin_is_ratio_of_sums_not_mean_of_percentages():
    frame = pl.DataFrame(
        {
            "revenue_net": [100.0, 900.0],
            "retailer_margin_abs": [50.0, 90.0],
            "retailer_margin_pct": [0.5, 0.1],
        }
    )

    assert aggregate_margin_pct(frame) == 0.14
    assert aggregate_margin_pct(frame) != sum(frame["retailer_margin_pct"].to_list()) / 2
