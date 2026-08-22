from datetime import date

import polars as pl

from retail_analytics.economics.tax import (
    TaxRule,
    load_tax_rule_config,
    load_tax_rules,
    normalize_tax,
)
from retail_analytics.pipeline.context import AnalysisContext


def _context(retailer_id: str = "retailer_a") -> AnalysisContext:
    return AnalysisContext("run_a", retailer_id, "source_a", "v1", "rules_v1")


def _frame(period: date = date(2025, 6, 1), category_group: str = "CATEGORY_STANDARD") -> pl.DataFrame:
    return pl.DataFrame(
        {
            "period": [period],
            "category_group": [category_group],
            "units": [2.0],
            "revenue_vat": [120.0],
            "shelf_price_vat": [60.0],
            "input_price_vat": [30.0],
            "source_row_number": [7],
        }
    )


def _rules() -> tuple[TaxRule, ...]:
    return (
        TaxRule("reduced_rate_v1", date(2025, 1, 1), None, 0.10, {"category_group": "CATEGORY_REDUCED"}, "rules_v1", "retailer_a"),
        TaxRule("standard_rate_2025", date(2025, 1, 1), date(2025, 12, 31), 0.20, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_a"),
        TaxRule("standard_rate_2026", date(2026, 1, 1), None, 0.22, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_a"),
    )


def test_tax_rule_resolves_by_category_and_period():
    result = normalize_tax(_frame(category_group="CATEGORY_REDUCED"), _rules(), _context())

    assert result.quality_report.is_valid
    assert result.frame["tax_rule_id"].to_list() == ["reduced_rate_v1"]
    assert result.frame["tax_rate"].to_list() == [0.10]


def test_tax_rule_resolves_date_boundary():
    end_result = normalize_tax(_frame(date(2025, 12, 31)), _rules(), _context())
    start_result = normalize_tax(_frame(date(2026, 1, 1)), _rules(), _context())

    assert end_result.frame["tax_rule_id"].to_list() == ["standard_rate_2025"]
    assert start_result.frame["tax_rule_id"].to_list() == ["standard_rate_2026"]


def test_missing_tax_rule_fails():
    result = normalize_tax(_frame(category_group="CATEGORY_UNMAPPED"), _rules(), _context())

    assert not result.quality_report.is_valid
    assert result.quality_report.issues[0].issue_code == "no_matching_tax_rule"


def test_overlapping_tax_rules_fail():
    rules = _rules() + (
        TaxRule("overlap", date(2025, 6, 1), None, 0.19, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_a"),
    )

    result = normalize_tax(_frame(date(2025, 6, 1)), rules, _context())

    assert not result.quality_report.is_valid
    assert result.quality_report.issues[0].issue_code == "multiple_matching_tax_rules"


def test_tax_rate_metadata_is_preserved():
    result = normalize_tax(_frame(), _rules(), _context())

    assert result.frame["tax_rule_version"].to_list() == ["rules_v1"]
    assert result.tax_config_hash


def test_invalid_tax_rate_fails():
    rules = (
        TaxRule("invalid_rate", date(2025, 1, 1), None, 1.0, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_a"),
    )

    result = normalize_tax(_frame(), rules, _context())

    assert not result.quality_report.is_valid
    assert result.quality_report.issues[0].issue_code == "invalid_tax_rate"


def test_two_retailers_can_use_different_tax_rule_sets():
    rules = _rules() + (
        TaxRule("retailer_b_standard", date(2025, 1, 1), None, 0.05, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_b"),
    )

    result_a = normalize_tax(_frame(), rules, _context("retailer_a"))
    result_b = normalize_tax(_frame(), rules, _context("retailer_b"))

    assert result_a.frame["tax_rule_id"].to_list() == ["standard_rate_2025"]
    assert result_b.frame["tax_rule_id"].to_list() == ["retailer_b_standard"]


def test_demo_tax_rules_load_from_public_config():
    rules = load_tax_rules("config/public/demo/tax_rules.yaml")

    assert {rule.rule_id for rule in rules} == {"reduced_rate_v1", "standard_rate_2025", "standard_rate_2026"}


def test_malformed_tax_rate_loads_as_structured_quality_issue(tmp_path):
    config_path = tmp_path / "tax_rules.yaml"
    config_path.write_text(
        """
rule_version: rules_v1
rules:
  - rule_id: malformed_rate
    retailer_id: retailer_a
    valid_from: 2025-01-01
    rate: not-a-number
    match:
      category_group: CATEGORY_STANDARD
""",
        encoding="utf-8",
    )

    result = load_tax_rule_config(config_path)

    assert result.rules[0].rate is None
    assert not result.quality_report.is_valid
    assert result.quality_report.issues[0].issue_code == "invalid_tax_rule_config"
    assert result.quality_report.issues[0].field == "rate"


def test_malformed_tax_rate_becomes_tax_quality_issue(tmp_path):
    config_path = tmp_path / "tax_rules.yaml"
    config_path.write_text(
        """
rule_version: rules_v1
rules:
  - rule_id: malformed_rate
    retailer_id: retailer_a
    valid_from: 2025-01-01
    rate: not-a-number
    match:
      category_group: CATEGORY_STANDARD
""",
        encoding="utf-8",
    )

    rules = load_tax_rules(config_path)
    result = normalize_tax(_frame(), rules, _context())

    assert not result.quality_report.is_valid
    assert result.quality_report.issues[0].issue_code == "invalid_tax_rate"


def test_malformed_tax_config_top_level_returns_structured_issue(tmp_path):
    config_path = tmp_path / "tax_rules.yaml"
    config_path.write_text("- not-a-mapping\n", encoding="utf-8")

    result = load_tax_rule_config(config_path)

    assert result.rules == ()
    assert not result.quality_report.is_valid
    assert result.quality_report.issues[0].issue_code == "invalid_tax_rule_config"
