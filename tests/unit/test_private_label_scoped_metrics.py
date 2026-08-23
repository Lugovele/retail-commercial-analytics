from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from retail_analytics.mart import (
    PrivateLabelScope,
    calculate_private_label_scoped_metrics,
)
from retail_analytics.metrics.registry import MetricDefinition
from retail_analytics.pipeline.context import AnalysisContext


def test_scoped_additive_margin_weighted_and_shares_recompute_universe() -> None:
    definitions = _definitions()
    include = calculate_private_label_scoped_metrics(
        _frame(),
        definitions,
        _context(),
        metric_config_hash="hash_a",
        private_label_scope=PrivateLabelScope.INCLUDE,
    )
    exclude = calculate_private_label_scoped_metrics(
        _frame(),
        definitions,
        _context(),
        metric_config_hash="hash_a",
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )
    only = calculate_private_label_scoped_metrics(
        _frame(),
        definitions,
        _context(),
        metric_config_hash="hash_a",
        private_label_scope=PrivateLabelScope.ONLY,
    )

    assert _value(include.metrics, "revenue", "ALL") == 100.0
    assert _value(exclude.metrics, "revenue", "ALL") == 60.0
    assert _value(only.metrics, "revenue", "ALL") == 40.0
    assert _value(exclude.metrics, "retailer_margin_pct", "ALL") == pytest.approx(12.0 / 60.0)
    assert _value(only.metrics, "weighted_shelf_price_vat", "ALL") == pytest.approx(12.0)
    assert _value(include.metrics, "category_revenue_share", "BRAND_NATIONAL") == pytest.approx(0.6)
    assert _value(exclude.metrics, "category_revenue_share", "BRAND_NATIONAL") == pytest.approx(1.0)


def test_store_grain_excludes_private_label_contribution_but_keeps_store_identity() -> None:
    result = calculate_private_label_scoped_metrics(
        _frame(),
        (
            MetricDefinition(
                name="store_revenue",
                concept="revenue",
                definition_id="retailer_a.store.revenue.v1",
                definition_version="v1",
                aggregation="sum",
                source_column="revenue",
                grain=("period", "canonical_store_id"),
                entity_type="store",
                grain_id="store",
            ),
        ),
        _context(),
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    assert set(result.metrics["entity_id"].to_list()) == {"STORE_A_001", "STORE_A_002"}
    assert _value(result.metrics, "revenue", "STORE_A_001") == 60.0
    assert _value(result.metrics, "revenue", "STORE_A_002") == 0.0


def test_distribution_scope_preserves_active_store_universe() -> None:
    result = calculate_private_label_scoped_metrics(
        _frame(),
        (
            MetricDefinition(
                name="brand_selling_store_count",
                concept="selling_store_count",
                definition_id="retailer_a.brand.selling_store_count.v1",
                definition_version="v1",
                aggregation="distinct_count",
                distinct_column="canonical_store_id",
                condition={"units": {"gt": 0}},
                grain=("period", "category", "brand"),
                entity_type="brand",
                grain_id="brand",
            ),
            MetricDefinition(
                name="brand_active_store_count",
                concept="active_store_count",
                definition_id="retailer_a.brand.active_store_count.v1",
                definition_version="v1",
                aggregation="distinct_count",
                distinct_column="canonical_store_id",
                grain=("period", "category", "brand"),
                broadcast_grain=("period", "category"),
                entity_type="brand",
                grain_id="brand",
            ),
            MetricDefinition(
                name="brand_numeric_distribution",
                concept="distribution",
                definition_id="retailer_a.brand.numeric_distribution.v1",
                definition_version="v1",
                aggregation="ratio_of_sums",
                numerator="brand_selling_store_count",
                denominator="brand_active_store_count",
                grain=("period", "category", "brand"),
                entity_type="brand",
                grain_id="brand",
            ),
        ),
        _context(),
        private_label_scope=PrivateLabelScope.EXCLUDE,
    )

    assert _value(result.metrics, "active_store_count", "BRAND_NATIONAL") == 2.0
    assert _value(result.metrics, "selling_store_count", "BRAND_NATIONAL") == 1.0
    assert _value(result.metrics, "distribution", "BRAND_NATIONAL") == pytest.approx(0.5)


def _value(frame: pl.DataFrame, concept: str, entity_id: str) -> float:
    return frame.filter((pl.col("concept") == concept) & (pl.col("entity_id") == entity_id))[
        "metric_value"
    ][0]


def _context() -> AnalysisContext:
    return AnalysisContext(
        analysis_run_id="analysis_a",
        retailer_id="retailer_a",
        source_id="source_a",
        source_version="v1",
        rule_version="rules_v1",
    )


def _definitions() -> tuple[MetricDefinition, ...]:
    return (
        MetricDefinition(
            name="network_revenue",
            concept="revenue",
            definition_id="retailer_a.network.revenue.v1",
            definition_version="v1",
            aggregation="sum",
            source_column="revenue",
            grain=("period",),
            entity_type="network",
            grain_id="network",
        ),
        MetricDefinition(
            name="network_margin_abs",
            concept="retailer_margin_abs",
            definition_id="retailer_a.network.margin_abs.v1",
            definition_version="v1",
            aggregation="sum",
            source_column="retailer_margin_abs",
            grain=("period",),
            entity_type="network",
            grain_id="network",
        ),
        MetricDefinition(
            name="network_margin_pct",
            concept="retailer_margin_pct",
            definition_id="retailer_a.network.margin_pct.v1",
            definition_version="v1",
            aggregation="ratio_of_sums",
            numerator="network_margin_abs",
            denominator="network_revenue",
            grain=("period",),
            entity_type="network",
            grain_id="network",
        ),
        MetricDefinition(
            name="weighted_shelf_price_vat",
            concept="weighted_shelf_price_vat",
            definition_id="retailer_a.network.shelf_price.v1",
            definition_version="v1",
            aggregation="weighted_average",
            value_column="shelf_price_vat",
            weight_column="units",
            grain=("period",),
            entity_type="network",
            grain_id="network",
        ),
        MetricDefinition(
            name="category_revenue",
            concept="revenue",
            definition_id="retailer_a.category.revenue.v1",
            definition_version="v1",
            aggregation="sum",
            source_column="revenue",
            grain=("period", "category"),
            entity_type="category",
            grain_id="category",
            share_denominator_scope="network",
        ),
        MetricDefinition(
            name="brand_revenue",
            concept="revenue",
            definition_id="retailer_a.brand.revenue.v1",
            definition_version="v1",
            aggregation="sum",
            source_column="revenue",
            grain=("period", "category", "brand"),
            entity_type="brand",
            grain_id="brand",
            share_denominator_scope="category",
        ),
    )


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["analysis_a", "analysis_a", "analysis_a"],
            "retailer_id": ["retailer_a", "retailer_a", "retailer_a"],
            "source_id": ["source_a", "source_a", "source_a"],
            "period": [date(2025, 1, 1), date(2025, 1, 1), date(2025, 1, 1)],
            "category": ["CATEGORY_STANDARD", "CATEGORY_STANDARD", "CATEGORY_STANDARD"],
            "brand": ["BRAND_NATIONAL", "BRAND_PRIVATE", "BRAND_NATIONAL"],
            "canonical_store_id": ["STORE_A_001", "STORE_A_001", "STORE_A_002"],
            "canonical_product_id": ["SKU_A_001", "SKU_A_002", "SKU_A_003"],
            "private_label_flag": [False, True, False],
            "revenue": [60.0, 40.0, 0.0],
            "retailer_margin_abs": [12.0, 8.0, 0.0],
            "shelf_price_vat": [10.0, 12.0, 9.0],
            "units": [6.0, 4.0, 0.0],
        }
    )
