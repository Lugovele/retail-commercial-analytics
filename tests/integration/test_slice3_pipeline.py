from datetime import date

import polars as pl

from retail_analytics.core.benchmarking.contracts import PeerRule, PriceSegmentRule
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.pipeline.slice3 import run_slice3_benchmarking


def test_slice3_end_to_end_benchmarking_foundation():
    context = AnalysisContext("run_a", "retailer_a", "source_a", "v1", "rules_v1")
    result = run_slice3_benchmarking(
        metric_frame=_metrics(),
        product_frame=_products(),
        peer_rules=(
            PeerRule("retailer_a.category_pool.v1", "rules_v1", "retailer_a", "BROAD_CATEGORY", ("category",)),
            PeerRule(
                "retailer_a.direct_peer.v1",
                "rules_v1",
                "retailer_a",
                "DIRECT_COMPARABLE",
                ("category", "carbonation", "volume_band", "price_segment", "package"),
            ),
        ),
        price_segment_rules=(
            PriceSegmentRule(
                "retailer_a.price_segments.v1",
                "rules_v1",
                "retailer_a",
                ("ECONOMY", "MID", "PREMIUM"),
            ),
        ),
        context=context,
    )

    assert not result.price_segments.is_empty()
    assert not result.peer_groups.is_empty()
    assert not result.benchmark_features.is_empty()
    assert set(result.price_segments["retailer_id"].unique().to_list()) == {"retailer_a"}


def _products() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["run_a"] * 4,
            "retailer_id": ["retailer_a"] * 4,
            "source_id": ["source_a"] * 4,
            "entity_id": ["SKU_A_001", "SKU_A_002", "SKU_A_003", "SKU_A_004"],
            "category": ["CATEGORY_A"] * 4,
            "carbonation": ["CARBONATED"] * 4,
            "volume_band": ["VOLUME_A"] * 4,
            "package": ["PACKAGE_A"] * 4,
            "is_own_product": [True, False, False, False],
        }
    )


def _metrics() -> pl.DataFrame:
    rows = []
    for index, price in enumerate((10.0, 20.0, 30.0, 40.0), start=1):
        entity_id = f"SKU_A_{index:03d}"
        for metric_name, value in {
            "weighted_shelf_price_vat": price,
            "revenue_net": 100.0 - index,
            "units": 20.0 - index,
            "units_per_selling_store": 10.0 + index,
            "retailer_margin_abs": 40.0 - index,
            "numeric_distribution": 0.5,
        }.items():
            rows.append(_metric_row(entity_id, metric_name, value))
    return pl.DataFrame(rows)


def _metric_row(entity_id: str, metric_name: str, value: float) -> dict[str, object]:
    return {
        "analysis_run_id": "run_a",
        "retailer_id": "retailer_a",
        "source_id": "source_a",
        "period": date(2026, 2, 1),
        "category": "CATEGORY_A",
        "entity_type": "sku",
        "entity_id": entity_id,
        "metric_name": metric_name,
        "metric_definition_id": f"retailer_a.{metric_name}.v1",
        "metric_definition_version": "v1",
        "metric_config_hash": "metric_hash",
        "concept": metric_name,
        "metric_value": value,
    }
