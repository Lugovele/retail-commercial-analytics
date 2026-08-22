from datetime import date

import polars as pl
import pytest

from retail_analytics.normalization.periods import normalize_period
from retail_analytics.normalization.values import normalize_types
from retail_analytics.schema.validation import ValidationError, raise_if_fatal
from retail_analytics.storage.profile import profile_canonical_source


def test_year_month_normalizes_to_month_start():
    normalized, report = normalize_period(pl.DataFrame({"year": [2026], "month": [6], "source_row_number": [1]}))
    assert report.is_valid
    assert normalized.get_column("period").to_list() == [date(2026, 6, 1)]


def test_invalid_month_fails():
    _, report = normalize_period(pl.DataFrame({"year": [2026], "month": [13], "source_row_number": [1]}))
    assert not report.is_valid
    assert report.issues[0].code == "invalid_month"


def test_numeric_fields_are_normalized():
    normalized, report = normalize_types(pl.DataFrame({"units": ["10"], "revenue_vat": ["25.5"], "source_row_number": [1]}))
    assert report.is_valid
    assert normalized.schema["units"] == pl.Float64
    assert normalized.get_column("revenue_vat").to_list() == [25.5]


def test_invalid_numeric_value_reports_validation_error():
    _, report = normalize_types(pl.DataFrame({"units": ["not_numeric"], "revenue_vat": ["25.5"], "source_row_number": [1]}))
    assert not report.is_valid
    assert any(issue.code == "invalid_numeric_value" for issue in report.issues)


def test_blank_required_string_reports_validation_error():
    _, report = normalize_types(pl.DataFrame({"source_sku_id": [""], "source_row_number": [1]}))
    with pytest.raises(ValidationError):
        raise_if_fatal(report)
    assert any(issue.code == "blank_required_string" for issue in report.issues)


def test_profile_reports_rows_periods_stores_and_skus():
    frame = pl.DataFrame({
        "period": [date(2026, 6, 1), date(2026, 7, 1)],
        "retailer_id": ["retailer_a", "retailer_a"],
        "source_store_id": ["STORE_A_001", "STORE_A_002"],
        "source_sku_id": ["SKU_A_001", "SKU_A_002"],
        "units": [1.0, None],
    })
    profile = profile_canonical_source(frame)
    assert profile.row_count == 2
    assert profile.periods == (date(2026, 6, 1), date(2026, 7, 1))
    assert profile.source_store_count == 2
    assert profile.source_sku_count == 2
    assert profile.null_counts["units"] == 1


def test_duplicate_candidate_grain_is_reported_not_silently_aggregated():
    frame = pl.DataFrame({
        "period": [date(2026, 6, 1), date(2026, 6, 1)],
        "retailer_id": ["retailer_a", "retailer_a"],
        "source_store_id": ["STORE_A_001", "STORE_A_001"],
        "source_sku_id": ["SKU_A_001", "SKU_A_001"],
        "units": [1.0, 2.0],
    })
    profile = profile_canonical_source(frame)
    assert profile.row_count == 2
    assert profile.duplicate_candidate_count == 2