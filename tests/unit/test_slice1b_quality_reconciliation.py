from datetime import date

import polars as pl

from retail_analytics.economics.tax import TaxRule
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.pipeline.slice1b import run_slice1b_normalization
from retail_analytics.quality.checks import reconcile_economics, run_quality_checks


def _context() -> AnalysisContext:
    return AnalysisContext("run_a", "retailer_a", "source_a", "v1", "rules_v1")


def _rules() -> tuple[TaxRule, ...]:
    return (
        TaxRule("standard_rate_2025", date(2025, 1, 1), None, 0.20, {"category_group": "CATEGORY_STANDARD"}, "rules_v1", "retailer_a"),
    )


def _frame(units=(2.0,), revenue_vat=(120.0,)) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "period": [date(2025, 1, 1) for _ in units],
            "category_group": ["CATEGORY_STANDARD" for _ in units],
            "units": list(units),
            "revenue_vat": list(revenue_vat),
            "shelf_price_vat": [60.0 for _ in units],
            "input_price_vat": [30.0 for _ in units],
            "source_row_number": list(range(1, len(units) + 1)),
        }
    )


def test_negative_units_negative_revenue_is_preserved():
    source = _frame(units=(-1.0,), revenue_vat=(-60.0,))
    result = run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    assert result.enriched_frame["units"].to_list() == [-1.0]
    assert result.enriched_frame["revenue_vat"].to_list() == [-60.0]


def test_negative_correction_is_classified():
    result = run_slice1b_normalization(
        canonical_frame=_frame(units=(-1.0,), revenue_vat=(-60.0,)),
        tax_rules=_rules(),
        context=_context(),
    )

    assert result.enriched_frame["business_quality_class"].to_list() == ["RETURN_OR_CORRECTION"]
    assert any(issue.issue_code == "negative_units_negative_revenue" for issue in result.quality_report.issues)


def test_positive_units_negative_revenue_is_suspicious():
    report = run_quality_checks(_frame(units=(1.0,), revenue_vat=(-60.0,)), _context())

    assert any(issue.issue_code == "positive_units_negative_revenue" for issue in report.issues)


def test_negative_units_positive_revenue_is_suspicious():
    report = run_quality_checks(_frame(units=(-1.0,), revenue_vat=(60.0,)), _context())

    assert any(issue.issue_code == "negative_units_positive_revenue" for issue in report.issues)


def test_missing_shelf_price_is_warning():
    source = _frame().drop("shelf_price_vat")
    result = run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    assert any(issue.issue_code == "missing_shelf_price" for issue in result.quality_report.issues)


def test_missing_optional_price_warnings_are_not_duplicated():
    source = _frame().drop("shelf_price_vat")
    result = run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    matching_issues = [
        issue for issue in result.quality_report.issues if issue.issue_code == "missing_shelf_price"
    ]
    assert len(matching_issues) == 1


def test_malformed_tax_config_is_reported_by_slice1b(tmp_path):
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

    result = run_slice1b_normalization(
        canonical_frame=_frame(),
        tax_rules=config_path,
        context=_context(),
    )

    assert any(issue.issue_code == "invalid_tax_rule_config" for issue in result.quality_report.issues)
    assert any(issue.issue_code == "invalid_tax_rate" for issue in result.quality_report.issues)


def test_enrichment_does_not_drop_correction_rows():
    source = _frame(units=(2.0, -1.0), revenue_vat=(120.0, -60.0))
    result = run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    assert result.enriched_frame.height == 2


def test_reconciliation_preserves_revenue_vat_total():
    source = _frame(units=(2.0, -1.0), revenue_vat=(120.0, -60.0))
    result = run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    check = _check(result.reconciliation_result.checks, "preserve_revenue_vat_total")
    assert check.status == "PASS"
    assert check.actual == check.expected


def test_reconciliation_preserves_units_total():
    source = _frame(units=(2.0, -1.0), revenue_vat=(120.0, -60.0))
    result = run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    assert _check(result.reconciliation_result.checks, "preserve_units_total").status == "PASS"


def test_reconciliation_preserves_row_count():
    source = _frame(units=(2.0, -1.0), revenue_vat=(120.0, -60.0))
    result = run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    assert _check(result.reconciliation_result.checks, "preserve_row_count").status == "PASS"


def test_reconciliation_preserves_source_row_traceability():
    source = _frame(units=(2.0, -1.0), revenue_vat=(120.0, -60.0))
    result = run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    assert _check(result.reconciliation_result.checks, "preserve_source_row_traceability").status == "PASS"


def test_reconciliation_reports_mismatch_as_structured_result():
    source = _frame(units=(2.0,), revenue_vat=(120.0,))
    changed = source.with_columns(pl.lit(121.0).alias("revenue_vat"))
    result = reconcile_economics(source, changed, _context())

    assert not result.is_valid
    assert _check(result.checks, "preserve_revenue_vat_total").status == "FAIL"
    assert result.quality_report.issues[0].issue_code == "preserve_revenue_vat_total"


def test_economics_enrichment_does_not_mutate_input_frame():
    source = _frame()
    before = source.clone()

    run_slice1b_normalization(canonical_frame=source, tax_rules=_rules(), context=_context())

    assert source.equals(before)
    assert "revenue_net" not in source.columns


def _check(checks, check_id):
    return next(check for check in checks if check.check_id == check_id)
