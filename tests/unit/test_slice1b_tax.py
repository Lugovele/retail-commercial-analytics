from datetime import date

import polars as pl

from retail_analytics.economics.tax import (
    TaxRule,
    load_tax_rule_config,
    load_tax_rules,
    normalize_tax,
)
from retail_analytics.economics.tax_semantics import classify_tax_semantics
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.pipeline.slice1b import run_slice1b_normalization


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


def test_tax_semantic_exact_single_key_mapping(tmp_path):
    result = load_tax_rule_config(_single_key_semantic_config(tmp_path))
    frame = pl.DataFrame({"category": ["CATEGORY_A"], "period": [date(2025, 1, 1)], "source_row_number": [1]})

    classified = classify_tax_semantics(frame, result.tax_semantic_mapping)

    assert classified.quality_report.is_valid
    assert classified.frame["tax_category"].to_list() == ["REDUCED_GROUP"]
    assert classified.frame["tax_semantic_match_type"].to_list() == ["exact"]


def test_tax_semantic_exact_composite_key_mapping(tmp_path):
    result = load_tax_rule_config(_semantic_config(tmp_path))
    frame = _semantic_frame("CATEGORY_B", "SUBCATEGORY_B", "TYPE_B")

    classified = classify_tax_semantics(frame, result.tax_semantic_mapping)

    assert classified.frame["tax_category"].to_list() == ["STANDARD_GROUP"]
    assert classified.frame["tax_semantic_match_type"].to_list() == ["reviewed_standard"]


def test_tax_semantic_reduced_group_reaches_tax_resolver(tmp_path):
    result = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_A", "SUBCATEGORY_A", "TYPE_A"),
        tax_rules=_semantic_config(tmp_path),
        context=_context(),
    )

    assert result.quality_report.is_valid
    assert result.enriched_frame["tax_category"].to_list() == ["REDUCED_GROUP"]
    assert result.enriched_frame["tax_rule_id"].to_list() == ["reduced_rate_v1"]
    assert result.enriched_frame["tax_rate"].to_list() == [0.10]


def test_tax_semantic_slice1b_end_to_end_economics(tmp_path):
    result = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_B", "SUBCATEGORY_B", "TYPE_B"),
        tax_rules=_semantic_config(tmp_path),
        context=_context(),
    )
    row = result.enriched_frame.row(0, named=True)

    assert row["tax_category"] == "STANDARD_GROUP"
    assert row["tax_rate"] == 0.20
    assert row["revenue_net"] == 100.0
    assert row["shelf_price_net"] == 50.0
    assert row["input_price_net"] == 25.0
    assert row["retailer_margin_abs"] == 50.0
    assert row["retailer_margin_pct"] == 0.5


def test_tax_semantic_standard_group_uses_time_versioned_rule(tmp_path):
    result_2025 = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_B", "SUBCATEGORY_B", "TYPE_B", period=date(2025, 12, 31)),
        tax_rules=_semantic_config(tmp_path),
        context=_context(),
    )
    result_2026 = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_B", "SUBCATEGORY_B", "TYPE_B", period=date(2026, 1, 1)),
        tax_rules=_semantic_config(tmp_path),
        context=_context(),
    )

    assert result_2025.enriched_frame["tax_rule_id"].to_list() == ["standard_rate_2025"]
    assert result_2026.enriched_frame["tax_rule_id"].to_list() == ["standard_rate_2026"]


def test_tax_semantic_unknown_key_is_structured_issue(tmp_path):
    result = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_UNKNOWN", "SUBCATEGORY_B", "TYPE_B"),
        tax_rules=_semantic_config(tmp_path),
        context=_context(),
    )

    assert any(issue.issue_code == "unknown_tax_semantic_key" for issue in result.quality_report.issues)
    assert result.enriched_frame["tax_rate"].to_list() == [None]


def test_tax_semantic_missing_key_field_is_structured_issue(tmp_path):
    frame = _semantic_frame("CATEGORY_B", "SUBCATEGORY_B", "TYPE_B").drop("subcategory_2")
    result = run_slice1b_normalization(canonical_frame=frame, tax_rules=_semantic_config(tmp_path), context=_context())

    assert any(issue.issue_code == "missing_tax_semantic_input" for issue in result.quality_report.issues)
    assert result.enriched_frame["tax_rate"].to_list() == [None]


def test_tax_semantic_does_not_fuzzy_match(tmp_path):
    result = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_A_EXTRA", "SUBCATEGORY_A", "TYPE_A"),
        tax_rules=_semantic_config(tmp_path),
        context=_context(),
    )

    assert any(issue.issue_code == "unknown_tax_semantic_key" for issue in result.quality_report.issues)


def test_tax_semantic_ambiguous_duplicate_match_fails(tmp_path):
    config_path = _semantic_config(tmp_path)
    text = config_path.read_text(encoding="utf-8")
    text = text.replace(
        "reviewed_mappings:",
        """
  confirmed_mappings:
    - tax_category: ALSO_REDUCED
      match:
        category: CATEGORY_A
        subcategory: SUBCATEGORY_A
        subcategory_2: TYPE_A
  reviewed_mappings:""",
    )
    config_path.write_text(text, encoding="utf-8")

    result = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_A", "SUBCATEGORY_A", "TYPE_A"),
        tax_rules=config_path,
        context=_context(),
    )

    assert any(issue.issue_code == "ambiguous_tax_semantic_match" for issue in result.quality_report.issues)


def test_tax_semantic_partial_composite_match_config_fails(tmp_path):
    config_path = _semantic_config(tmp_path)
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("        subcategory_2: TYPE_A\n", "", 1)
    config_path.write_text(text, encoding="utf-8")

    result = load_tax_rule_config(config_path)

    assert result.tax_semantic_mapping is None
    assert any(issue.issue_code == "invalid_tax_semantic_mapping_config" for issue in result.quality_report.issues)


def test_tax_semantic_extra_composite_match_config_fails(tmp_path):
    config_path = _semantic_config(tmp_path)
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("        subcategory_2: TYPE_A\n", "        subcategory_2: TYPE_A\n        extra_field: EXTRA\n", 1)
    config_path.write_text(text, encoding="utf-8")

    result = load_tax_rule_config(config_path)

    assert result.tax_semantic_mapping is None
    assert any(issue.issue_code == "invalid_tax_semantic_mapping_config" for issue in result.quality_report.issues)


def test_tax_semantic_duplicate_source_fields_config_fails(tmp_path):
    config_path = _semantic_config(tmp_path)
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("    - subcategory\n", "    - subcategory\n    - subcategory\n", 1)
    config_path.write_text(text, encoding="utf-8")

    result = load_tax_rule_config(config_path)

    assert result.tax_semantic_mapping is None
    assert any(issue.field == "source_fields" for issue in result.quality_report.issues)


def test_tax_semantic_invalid_unknown_policy_config_fails(tmp_path):
    config_path = _semantic_config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace("unknown_future_value_policy: REVIEW_REQUIRED", "unknown_future_value_policy: SILENT_DEFAULT")
    config_path.write_text(text, encoding="utf-8")

    result = load_tax_rule_config(config_path)

    assert result.tax_semantic_mapping is None
    assert any(issue.field == "unknown_future_value_policy" for issue in result.quality_report.issues)


def test_tax_semantic_scoped_standard_fallback_is_explicit(tmp_path):
    result = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_UNLISTED", "SUBCATEGORY_UNLISTED", "TYPE_UNLISTED"),
        tax_rules=_scoped_standard_semantic_config(tmp_path),
        context=_context(),
    )

    assert result.quality_report.is_valid
    assert result.enriched_frame["tax_category"].to_list() == ["STANDARD_GROUP"]
    assert result.enriched_frame["tax_semantic_match_type"].to_list() == ["scoped_standard"]


def test_tax_semantic_lineage_and_hash_are_preserved(tmp_path):
    result = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_B", "SUBCATEGORY_B", "TYPE_B"),
        tax_rules=_semantic_config(tmp_path),
        context=_context(),
    )

    row = result.enriched_frame.row(0, named=True)
    assert row["tax_semantic_mapping_id"] == "synthetic_tax_semantics_v1"
    assert row["tax_semantic_mapping_version"] == "rules_v1"
    assert row["tax_semantic_mapping_hash"]


def test_direct_tax_rule_sequence_remains_backward_compatible():
    result = run_slice1b_normalization(canonical_frame=_frame(), tax_rules=_rules(), context=_context())

    assert result.quality_report.is_valid
    assert "tax_semantic_mapping_id" not in result.enriched_frame.columns


def test_tax_semantic_no_applicable_date_rule_is_reported(tmp_path):
    result = run_slice1b_normalization(
        canonical_frame=_semantic_frame("CATEGORY_B", "SUBCATEGORY_B", "TYPE_B", period=date(2024, 12, 31)),
        tax_rules=_semantic_config(tmp_path),
        context=_context(),
    )

    assert any(issue.issue_code == "no_matching_tax_rule" for issue in result.quality_report.issues)


def _semantic_frame(
    category: str,
    subcategory: str,
    subcategory_2: str,
    *,
    period: date = date(2025, 6, 1),
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "period": [period],
            "category": [category],
            "subcategory": [subcategory],
            "subcategory_2": [subcategory_2],
            "units": [2.0],
            "revenue_vat": [120.0],
            "shelf_price_vat": [60.0],
            "input_price_vat": [30.0],
            "source_row_number": [7],
        }
    )


def _semantic_config(tmp_path):
    config_path = tmp_path / "tax_rules.yaml"
    config_path.write_text(
        """
rule_version: rules_v1
rules:
  - rule_id: reduced_rate_v1
    retailer_id: retailer_a
    rule_version: rules_v1
    valid_from: 2025-01-01
    valid_to: null
    rate: 0.10
    match:
      tax_category: REDUCED_GROUP
  - rule_id: standard_rate_2025
    retailer_id: retailer_a
    rule_version: rules_v1
    valid_from: 2025-01-01
    valid_to: 2025-12-31
    rate: 0.20
    match:
      tax_category: STANDARD_GROUP
  - rule_id: standard_rate_2026
    retailer_id: retailer_a
    rule_version: rules_v1
    valid_from: 2026-01-01
    valid_to: null
    rate: 0.22
    match:
      tax_category: STANDARD_GROUP
tax_semantic_mapping:
  mapping_id: synthetic_tax_semantics_v1
  mapping_version: rules_v1
  source_fields:
    - category
    - subcategory
    - subcategory_2
  output_field: tax_category
  confirmed_reduced_mappings:
    - tax_category: REDUCED_GROUP
      match:
        category: CATEGORY_A
        subcategory: SUBCATEGORY_A
        subcategory_2: TYPE_A
  standard_mapping:
    tax_category: STANDARD_GROUP
    scope_assertion: synthetic reviewed beverage taxonomy
    reviewed_mappings:
      - category: CATEGORY_B
        subcategory: SUBCATEGORY_B
        subcategory_2: TYPE_B
  unknown_future_value_policy: REVIEW_REQUIRED
""",
        encoding="utf-8",
    )
    return config_path


def _single_key_semantic_config(tmp_path):
    config_path = tmp_path / "tax_rules.yaml"
    config_path.write_text(
        """
rule_version: rules_v1
rules:
  - rule_id: reduced_rate_v1
    retailer_id: retailer_a
    rule_version: rules_v1
    valid_from: 2025-01-01
    valid_to: null
    rate: 0.10
    match:
      tax_category: REDUCED_GROUP
tax_semantic_mapping:
  mapping_id: synthetic_single_key_tax_semantics_v1
  mapping_version: rules_v1
  source_fields:
    - category
  output_field: tax_category
  confirmed_reduced_mappings:
    - tax_category: REDUCED_GROUP
      match:
        category: CATEGORY_A
  unknown_future_value_policy: REVIEW_REQUIRED
""",
        encoding="utf-8",
    )
    return config_path


def _scoped_standard_semantic_config(tmp_path):
    config_path = tmp_path / "tax_rules.yaml"
    config_path.write_text(
        """
rule_version: rules_v1
rules:
  - rule_id: standard_rate_2025
    retailer_id: retailer_a
    rule_version: rules_v1
    valid_from: 2025-01-01
    valid_to: null
    rate: 0.20
    match:
      tax_category: STANDARD_GROUP
tax_semantic_mapping:
  mapping_id: synthetic_scoped_standard_tax_semantics_v1
  mapping_version: rules_v1
  source_fields:
    - category
    - subcategory
    - subcategory_2
  output_field: tax_category
  standard_mapping:
    tax_category: STANDARD_GROUP
    scope_assertion: synthetic source file contains only reviewed standard rows
  unknown_future_value_policy: REVIEW_REQUIRED
""",
        encoding="utf-8",
    )
    return config_path
