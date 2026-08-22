from datetime import date

import polars as pl

from retail_analytics.core.benchmarking.contracts import (
    BenchmarkRequest,
    PeerRule,
    PriceSegmentRule,
)
from retail_analytics.core.benchmarking.features import calculate_benchmark_features
from retail_analytics.core.benchmarking.peer_groups import build_peer_groups
from retail_analytics.core.benchmarking.price_segments import build_price_segments
from retail_analytics.core.benchmarking.registry import (
    load_peer_rule_config,
    load_price_segment_rule_config,
    peer_rules_for_context,
    price_segment_rules_for_context,
)
from retail_analytics.pipeline.context import AnalysisContext


def _context(retailer_id: str = "retailer_a", source_id: str = "source_a") -> AnalysisContext:
    return AnalysisContext("run_a", retailer_id, source_id, "v1", "rules_v1")


def _segment_rule(retailer_id: str = "retailer_a", min_population: int = 3) -> PriceSegmentRule:
    return PriceSegmentRule(
        "retailer_a.price_segments.v1",
        "rules_v1",
        retailer_id,
        ("ECONOMY", "MID", "PREMIUM"),
        min_segment_population=min_population,
    )


def _broad_rule() -> PeerRule:
    return PeerRule(
        "retailer_a.category_pool.v1",
        "rules_v1",
        "retailer_a",
        "BROAD_CATEGORY",
        ("category",),
        top_n=2,
    )


def _direct_rule() -> PeerRule:
    return PeerRule(
        "retailer_a.direct_peer.v1",
        "rules_v1",
        "retailer_a",
        "DIRECT_COMPARABLE",
        ("category", "carbonation", "volume_band", "price_segment", "package"),
    )


def _products(retailer_id: str = "retailer_a", source_id: str = "source_a") -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["run_a"] * 8,
            "retailer_id": [retailer_id] * 8,
            "source_id": [source_id] * 8,
            "entity_id": [f"SKU_A_{index:03d}" for index in range(1, 9)],
            "category": ["CATEGORY_A"] * 7 + ["CATEGORY_B"],
            "brand": ["BRAND_A", "BRAND_B", "BRAND_C", "BRAND_D", "BRAND_E", "BRAND_F", "BRAND_G", "BRAND_H"],
            "manufacturer": ["MANUFACTURER_A", "MANUFACTURER_B", "MANUFACTURER_B", "MANUFACTURER_C", "MANUFACTURER_D", "MANUFACTURER_E", "MANUFACTURER_F", "MANUFACTURER_G"],
            "carbonation": ["CARBONATED", "CARBONATED", "CARBONATED", "STILL", "CARBONATED", "CARBONATED", "CARBONATED", "CARBONATED"],
            "volume_band": ["VOLUME_A", "VOLUME_A", "VOLUME_A", "VOLUME_A", "VOLUME_B", "VOLUME_A", "VOLUME_A", "VOLUME_A"],
            "package": ["PACKAGE_PET", "PACKAGE_PET", "PACKAGE_PET", "PACKAGE_PET", "PACKAGE_CAN", "PACKAGE_PET", "PACKAGE_PET", "PACKAGE_PET"],
            "is_own_product": [True, False, False, False, False, False, False, False],
        }
    )


def _metrics(retailer_id: str = "retailer_a", source_id: str = "source_a") -> pl.DataFrame:
    prices = [10.0, 20.0, 20.0, 40.0, 50.0, None, 0.0, 30.0]
    rows = []
    for idx, price in enumerate(prices, start=1):
        entity = f"SKU_A_{idx:03d}"
        period = date(2026, 2, 1)
        for metric_name, value in {
            "weighted_shelf_price_vat": price,
            "revenue_net": float(100 - idx),
            "units": float(20 - idx),
            "units_per_selling_store": float(10 + idx),
            "retailer_margin_abs": float(40 - idx),
            "numeric_distribution": 0.5,
        }.items():
            rows.append(_metric_row(retailer_id, source_id, period, entity, metric_name, value))
        rows.append(_metric_row(retailer_id, source_id, date(2026, 1, 1), entity, "weighted_shelf_price_vat", 99.0))
    return pl.DataFrame(rows)


def test_peer_rule_registry_filters_by_context():
    rules, _ = load_peer_rule_config("config/public/demo/peer_rules.yaml")

    assert len(peer_rules_for_context(rules, _context())) == 2
    assert peer_rules_for_context(rules, _context("retailer_b")) == ()


def test_price_segment_rule_registry_filters_by_context():
    rules, _ = load_price_segment_rule_config("config/public/demo/peer_rules.yaml")

    assert len(price_segment_rules_for_context(rules, _context())) == 1


def test_price_segments_use_latest_available_period():
    result = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest())

    assert set(result.price_segments["reference_period"].unique().to_list()) == {date(2026, 2, 1)}


def test_price_segments_create_three_demo_groups():
    result = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest())
    valid = result.price_segments.filter(pl.col("price_segment").is_in(["ECONOMY", "MID", "PREMIUM"]))

    assert set(valid["price_segment"].to_list()) == {"ECONOMY", "MID", "PREMIUM"}


def test_price_segment_boundaries_are_reproducible():
    result_a = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest())
    result_b = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest())

    assert result_a.price_segments.equals(result_b.price_segments)


def test_price_segment_ties_are_deterministic():
    result = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest())
    tied = result.price_segments.filter(pl.col("representative_price") == 20.0)

    assert len(set(tied["price_segment"].to_list())) == 1


def test_missing_price_is_reported():
    result = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest())

    assert result.price_segments.filter(pl.col("entity_id") == "SKU_A_006")["price_segment"].to_list() == ["UNCLASSIFIED_PRICE_NULL"]


def test_small_population_behavior():
    products = _products().filter(pl.col("entity_id").is_in(["SKU_A_001", "SKU_A_002"]))
    metrics = _metrics().filter(pl.col("entity_id").is_in(["SKU_A_001", "SKU_A_002"]))
    result = build_price_segments(metrics, products, (_segment_rule(min_population=3),), _context(), BenchmarkRequest())

    assert set(result.price_segments["price_segment"].to_list()) == {"INSUFFICIENT_POPULATION"}


def test_segment_assignment_is_retailer_isolated():
    result = build_price_segments(_metrics("retailer_b"), _products("retailer_b"), (_segment_rule("retailer_a"),), _context("retailer_b"), BenchmarkRequest())

    assert result.price_segments.is_empty()


def test_segment_assignment_is_rule_version_isolated():
    stale_rule = PriceSegmentRule(
        "retailer_a.price_segments.old",
        "old_rules",
        "retailer_a",
        ("ECONOMY", "MID", "PREMIUM"),
    )
    result = build_price_segments(_metrics(), _products(), (stale_rule,), _context(), BenchmarkRequest())

    assert result.price_segments.is_empty()


def test_broad_pool_contains_category_skus():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    result = build_peer_groups(_metrics(), _products(), (_broad_rule(),), segments, _context(), BenchmarkRequest())

    assert "SKU_A_002" in result.peer_groups.filter(pl.col("target_entity_id") == "SKU_A_001")["peer_entity_id"].to_list()


def test_top_n_pools_deduplicate_entities():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    result = build_peer_groups(_metrics(), _products(), (_broad_rule(),), segments, _context(), BenchmarkRequest())

    top = result.peer_groups.filter(pl.col("benchmark_scope") == "TOP_N")
    assert top.unique(["target_entity_id", "peer_entity_id", "benchmark_scope", "pool_source"]).height == top.height


def test_pool_uses_all_entities_when_population_below_n():
    rule = PeerRule("retailer_a.category_pool.v1", "rules_v1", "retailer_a", "BROAD_CATEGORY", ("category",), top_n=10)
    result = build_peer_groups(_metrics(), _products().filter(pl.col("category") == "CATEGORY_B"), (rule,), pl.DataFrame(), _context(), BenchmarkRequest())

    top = result.peer_groups.filter(pl.col("benchmark_scope") == "TOP_N")
    assert set(top["peer_entity_id"].to_list()) == {"SKU_A_008"}


def test_top_n_uses_selected_benchmark_period():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    historical = _metric_row("retailer_a", "source_a", date(2026, 1, 1), "SKU_A_005", "revenue_net", 999.0)
    metrics = pl.concat([_metrics(), pl.DataFrame([historical])], how="diagonal")
    result = build_peer_groups(metrics, _products(), (_broad_rule(),), segments, _context(), BenchmarkRequest())
    top_revenue = result.peer_groups.filter((pl.col("benchmark_scope") == "TOP_N") & (pl.col("pool_source") == "revenue_net"))

    assert "SKU_A_005" not in top_revenue["peer_entity_id"].to_list()


def test_top_n_scope_identity_includes_ranking_metric():
    rule = PeerRule(
        "retailer_a.category_pool.v1",
        "rules_v1",
        "retailer_a",
        "BROAD_CATEGORY",
        ("category",),
        top_n=1,
        ranking_metrics=("revenue_net", "units_per_selling_store"),
    )
    result = build_peer_groups(_metrics(), _products(), (rule,), pl.DataFrame(), _context(), BenchmarkRequest())
    top = result.peer_groups.filter((pl.col("benchmark_scope") == "TOP_N") & (pl.col("target_entity_id") == "SKU_A_001"))

    assert set(top["pool_source"].to_list()) == {"revenue_net", "units_per_selling_store"}
    assert len(set(top["benchmark_scope_id"].to_list())) == 2


def test_direct_peer_group_applies_configured_dimensions_and_excludes_self():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    result = build_peer_groups(_metrics(), _products(), (_direct_rule(),), segments, _context(), BenchmarkRequest())
    peers = result.peer_groups.filter(pl.col("target_entity_id") == "SKU_A_002")["peer_entity_id"].to_list()

    assert "SKU_A_003" in peers
    assert "SKU_A_002" not in peers


def test_direct_peer_group_does_not_cross_category_or_retailer():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    result = build_peer_groups(_metrics(), _products(), (_direct_rule(),), segments, _context(), BenchmarkRequest())

    assert "SKU_A_008" not in result.peer_groups["peer_entity_id"].to_list()


def test_empty_peer_group_reports_quality_issue():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    result = build_peer_groups(_metrics(), _products(), (_direct_rule(),), segments, _context(), BenchmarkRequest())

    assert any(issue.issue_code == "EMPTY_DIRECT_PEER_GROUP" for issue in result.quality_report.issues)


def test_unsupported_direct_peer_mode_reports_quality_issue():
    rule = PeerRule(
        "retailer_a.direct_peer.v1",
        "rules_v1",
        "retailer_a",
        "DIRECT_COMPARABLE",
        ("category",),
        direct_peer_mode="DIRECT_PLUS_RULE_POOL",
    )
    result = build_peer_groups(_metrics(), _products(), (rule,), pl.DataFrame(), _context(), BenchmarkRequest())

    assert result.peer_groups.is_empty()
    assert any(issue.issue_code == "UNSUPPORTED_DIRECT_PEER_MODE" for issue in result.quality_report.issues)


def test_rank_percentile_and_relative_price_features():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    peers = build_peer_groups(_metrics(), _products(), (_direct_rule(),), segments, _context(), BenchmarkRequest()).peer_groups
    result = calculate_benchmark_features(_metrics(), peers, segments, _context(), BenchmarkRequest())

    rows = result.benchmark_features.filter(pl.col("target_entity_id") == "SKU_A_002")
    assert rows.filter(pl.col("metric_name") == "revenue_net")["population_size"].to_list()
    assert rows.filter(pl.col("metric_name") == "relative_price_position")["price_delta_pct_to_peer_median"].to_list()


def test_benchmark_features_are_period_scoped():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    peers = build_peer_groups(_metrics(), _products(), (_broad_rule(),), segments, _context(), BenchmarkRequest()).peer_groups
    historical = _metric_row("retailer_a", "source_a", date(2026, 1, 1), "SKU_A_001", "revenue_net", 999.0)
    metrics = pl.concat([_metrics(), pl.DataFrame([historical])], how="diagonal")
    result = calculate_benchmark_features(metrics, peers, segments, _context(), BenchmarkRequest())
    row = result.benchmark_features.filter(
        (pl.col("target_entity_id") == "SKU_A_001")
        & (pl.col("benchmark_scope") == "BROAD_CATEGORY")
        & (pl.col("metric_name") == "revenue_net")
    )

    assert row["metric_value"].to_list() == [99.0]


def test_price_gap_empty_peer_is_null():
    segments = build_price_segments(_metrics(), _products(), (_segment_rule(),), _context(), BenchmarkRequest()).price_segments
    peers = build_peer_groups(_metrics(), _products().filter(pl.col("entity_id") == "SKU_A_001"), (_direct_rule(),), segments, _context(), BenchmarkRequest()).peer_groups
    result = calculate_benchmark_features(_metrics(), peers, segments, _context(), BenchmarkRequest())

    assert result.benchmark_features.is_empty()


def test_rankings_do_not_cross_source_boundary():
    result = build_price_segments(_metrics(source_id="source_b"), _products(source_id="source_b"), (_segment_rule(),), _context(source_id="source_a"), BenchmarkRequest())

    assert result.price_segments.is_empty()


def _metric_row(retailer_id: str, source_id: str, period: date, entity_id: str, metric_name: str, value: float | None) -> dict:
    return {
        "analysis_run_id": "run_a",
        "retailer_id": retailer_id,
        "source_id": source_id,
        "period": period,
        "category": "CATEGORY_A" if entity_id != "SKU_A_008" else "CATEGORY_B",
        "entity_type": "sku",
        "entity_id": entity_id,
        "metric_name": metric_name,
        "metric_definition_id": f"{retailer_id}.{metric_name}.v1",
        "metric_definition_version": "v1",
        "metric_config_hash": "metric_hash",
        "concept": metric_name,
        "metric_value": value,
    }
