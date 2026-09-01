from __future__ import annotations

import polars as pl
import pytest

from retail_analytics.volume_filter import (
    VOLUME_RANGES,
    volume_polars_filter,
    volume_range_for_value,
    volume_sql_predicate,
)


@pytest.mark.parametrize(
    ("value", "range_id"),
    [
        (0.0, None),
        (0.25, "le_0_25"),
        (0.250001, "gt_0_25_le_0_50"),
        (0.50, "gt_0_25_le_0_50"),
        (0.500001, "gt_0_50_le_0_75"),
        (0.75, "gt_0_50_le_0_75"),
        (1.00, "gt_0_75_le_1_00"),
        (1.50, "gt_1_00_le_1_50"),
        (2.00, "gt_1_50_le_2_00"),
        (5.00, "gt_2_00_le_5_00"),
        (5.01, "gt_5_00"),
    ],
)
def test_volume_range_boundaries_are_exact_without_zero(value: float, range_id: str | None) -> None:
    resolved = volume_range_for_value(value)
    assert (resolved.id if resolved else None) == range_id


def test_volume_ranges_do_not_overlap_for_positive_values() -> None:
    for value in (0.001, 0.25, 0.250001, 0.5, 0.500001, 0.75, 1.0, 1.5, 2.0, 5.0, 5.001):
        matching = [
            item.id
            for item in VOLUME_RANGES
            if value > (item.min_exclusive if item.min_exclusive is not None else 0.0)
            and (item.max_inclusive is None or value <= item.max_inclusive)
        ]
        assert matching == [volume_range_for_value(value).id]


def test_volume_polars_filter_accepts_range_and_exact_tokens() -> None:
    frame = pl.DataFrame({"volume_l": [0.0, 0.25, 0.33, 0.5, 1.0, 5.5]})
    predicate = volume_polars_filter("volume_l", ("volume_range:gt_0_25_le_0_50", "5.5"))
    assert predicate is not None

    assert frame.filter(predicate)["volume_l"].to_list() == [0.33, 0.5, 5.5]


def test_volume_sql_predicate_uses_numeric_range_not_display_labels() -> None:
    predicate, params = volume_sql_predicate("volume_l", ("volume_range:gt_1_00_le_1_50", "0.33"))

    assert predicate is not None
    assert "CAST(volume_l AS DOUBLE) > ?" in predicate
    assert "CAST(volume_l AS DOUBLE) <= ?" in predicate
    assert "ROUND(CAST(volume_l AS DOUBLE), 6) IN (?)" in predicate
    assert params == [0.33, 1.0, 1.5]
