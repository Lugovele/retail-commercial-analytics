from __future__ import annotations

from datetime import date

import pytest

from retail_analytics.mart import PrivateLabelScope, RankingScope, rank_manufacturers


def test_manufacturer_rank_by_revenue_uses_competition_rank_ties() -> None:
    rows = rank_manufacturers(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        metric="revenue_net",
        period_start=date(2025, 1, 1),
        category="CATEGORY_STANDARD",
    )

    ranks = {(row.manufacturer, row.rank, row.tie_count) for row in rows}
    assert ranks == {
        ("MANUFACTURER_A", 1, 2),
        ("MANUFACTURER_B", 1, 2),
        ("MANUFACTURER_C", 3, 1),
        ("MANUFACTURER_PL", 4, 1),
    }
    assert rows[0].ranking_scope == RankingScope.CATEGORY
    assert all(row.population_count == 4 for row in rows)


def test_manufacturer_rank_by_units_is_category_scoped() -> None:
    rows = rank_manufacturers(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        metric="units",
        period_start=date(2025, 1, 1),
    )

    standard = [row for row in rows if row.category == "CATEGORY_STANDARD"]
    other = [row for row in rows if row.category == "CATEGORY_OTHER"]
    assert {row.manufacturer for row in standard} == {
        "MANUFACTURER_A",
        "MANUFACTURER_B",
        "MANUFACTURER_C",
        "MANUFACTURER_PL",
    }
    assert {row.manufacturer for row in other} == {"MANUFACTURER_Z"}
    assert other[0].rank == 1


def test_manufacturer_rank_respects_retailer_source_and_private_label_scope() -> None:
    rows = rank_manufacturers(
        _frame(),
        retailer_id="retailer_a",
        source_id="source_a",
        metric="revenue_net",
        period_start=date(2025, 1, 1),
        category="CATEGORY_STANDARD",
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    assert {row.manufacturer for row in rows} == {"MANUFACTURER_A", "MANUFACTURER_B", "MANUFACTURER_C"}
    assert all(row.private_label_scope == PrivateLabelScope.EXCLUDE for row in rows)


def test_manufacturer_rank_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError, match="Unsupported ranking_scope"):
        rank_manufacturers(
            _frame(),
            retailer_id="retailer_a",
            source_id="source_a",
            metric="revenue_net",
            period_start=date(2025, 1, 1),
            ranking_scope="NETWORK",
        )


def test_manufacturer_rank_rejects_non_additive_metric() -> None:
    with pytest.raises(ValueError, match="Unsupported manufacturer ranking metric"):
        rank_manufacturers(
            _frame(),
            retailer_id="retailer_a",
            source_id="source_a",
            metric="retailer_margin_pct",
            period_start=date(2025, 1, 1),
        )


def _frame():
    import polars as pl

    return pl.DataFrame(
        {
            "retailer_id": ["retailer_a"] * 7 + ["retailer_b"],
            "source_id": ["source_a"] * 7 + ["source_a"],
            "period": [date(2025, 1, 1)] * 8,
            "category": [
                "CATEGORY_STANDARD",
                "CATEGORY_STANDARD",
                "CATEGORY_STANDARD",
                "CATEGORY_STANDARD",
                "CATEGORY_STANDARD",
                "CATEGORY_OTHER",
                "CATEGORY_STANDARD",
                "CATEGORY_STANDARD",
            ],
            "manufacturer": [
                "MANUFACTURER_A",
                "MANUFACTURER_B",
                "MANUFACTURER_C",
                "MANUFACTURER_PL",
                "MANUFACTURER_A",
                "MANUFACTURER_Z",
                "MANUFACTURER_C",
                "MANUFACTURER_R",
            ],
            "private_label_flag": [False, False, False, True, False, False, False, False],
            "revenue_net": [100.0, 100.0, 50.0, 25.0, 0.0, 999.0, 0.0, 500.0],
            "units": [5.0, 1.0, 3.0, 8.0, 0.0, 2.0, 0.0, 10.0],
        }
    )
