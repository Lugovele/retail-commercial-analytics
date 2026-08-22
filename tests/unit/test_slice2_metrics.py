from datetime import date

import polars as pl

from retail_analytics.core.calculation.aggregations import calculate_metric_share, calculate_metrics
from retail_analytics.metrics.registry import MetricDefinition, load_metric_definition_config
from retail_analytics.pipeline.context import AnalysisContext


def _context(retailer_id: str = "retailer_a", source_id: str = "source_a") -> AnalysisContext:
    return AnalysisContext("run_a", retailer_id, source_id, "v1", "rules_v1")


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "analysis_run_id": ["run_a"] * 5,
            "retailer_id": ["retailer_a"] * 4 + ["retailer_b"],
            "source_id": ["source_a"] * 5,
            "period": [date(2026, 1, 1)] * 5,
            "category": ["CATEGORY_STANDARD"] * 5,
            "brand": ["BRAND_A", "BRAND_A", "BRAND_A", "BRAND_B", "BRAND_A"],
            "manufacturer": ["MANUFACTURER_A"] * 5,
            "canonical_product_id": ["SKU_A_001", "SKU_A_001", "SKU_A_002", "SKU_A_003", "SKU_A_001"],
            "canonical_store_id": ["STORE_A_001", "STORE_A_002", "STORE_A_001", "STORE_A_003", "STORE_A_001"],
            "units": [10.0, -2.0, 5.0, 0.0, 99.0],
            "revenue_net": [100.0, -20.0, 50.0, 0.0, 990.0],
            "revenue_vat": [120.0, -24.0, 60.0, 0.0, 1188.0],
            "retailer_margin_abs": [30.0, -6.0, 10.0, 0.0, 300.0],
            "shelf_price_vat": [12.0, 12.0, 18.0, 20.0, 12.0],
            "input_price_vat": [7.0, 7.0, 10.0, 11.0, 7.0],
        }
    )


def test_metric_registry_filters_by_context_and_version():
    registry = load_metric_definition_config("config/public/demo/metric_definitions.yaml")
    scoped = registry.for_context(_context())

    assert scoped.get("revenue_net").definition_id == "retailer_a.revenue_net.v1"
    assert all(definition.retailer_id == "retailer_a" for definition in scoped.definitions)


def test_revenue_aggregates_by_period_and_sku():
    result = calculate_metrics(_frame(), (_sum_definition("revenue_net", "revenue"),), _context())

    sku = _metric(result.metrics, "SKU_A_001", "revenue")
    assert sku["metric_value"][0] == 80.0


def test_units_aggregate_by_period_and_brand():
    definition = _sum_definition("units", "units", grain=("period", "category", "brand"), entity_type="brand")
    result = calculate_metrics(_frame(), (definition,), _context())

    brand = _metric(result.metrics, "BRAND_A", "units")
    assert brand["metric_value"][0] == 13.0


def test_margin_pct_uses_ratio_of_sums():
    result = calculate_metrics(
        _frame(),
        (
            _sum_definition("revenue_net", "revenue"),
            _sum_definition("retailer_margin_abs", "retailer_margin_abs"),
            MetricDefinition(
                "retailer_margin_pct",
                "retailer_margin_pct",
                "retailer_a.margin_pct.v1",
                "v1",
                "ratio_of_sums",
                numerator="retailer_margin_abs",
                denominator="revenue_net",
                retailer_id="retailer_a",
                rule_version="rules_v1",
            ),
        ),
        _context(),
    )

    sku = _metric(result.metrics, "SKU_A_001", "retailer_margin_pct")
    assert sku["metric_value"][0] == 0.3


def test_aggregate_prices_are_weighted():
    definition = MetricDefinition(
        "weighted_shelf_price_vat",
        "weighted_shelf_price_vat",
        "retailer_a.weighted_shelf_price_vat.v1",
        "v1",
        "weighted_average",
        value_column="shelf_price_vat",
        weight_column="units",
        grain=("period", "category", "brand"),
        entity_type="brand",
        retailer_id="retailer_a",
        rule_version="rules_v1",
    )
    result = calculate_metrics(_frame(), (definition,), _context())

    brand = _metric(result.metrics, "BRAND_A", "weighted_shelf_price_vat")
    assert brand["metric_value"][0] == 14.0


def test_negative_corrections_preserve_financial_totals():
    result = calculate_metrics(_frame(), (_sum_definition("revenue_net", "revenue"),), _context())

    assert _metric(result.metrics, "SKU_A_001", "revenue")["metric_value"][0] == 80.0


def test_selling_store_count_uses_positive_units():
    result = calculate_metrics(_frame(), (_selling_store_definition(),), _context())

    assert _metric(result.metrics, "SKU_A_001", "selling_store_count")["metric_value"][0] == 1.0


def test_active_store_count_uses_period_store_universe():
    result = calculate_metrics(_frame(), (_active_store_definition(broadcast=True),), _context())

    assert _metric(result.metrics, "SKU_A_001", "active_store_count")["metric_value"][0] == 3.0


def test_distribution_uses_configured_definition():
    result = calculate_metrics(
        _frame(),
        (_selling_store_definition(), _active_store_definition(broadcast=True), _distribution_definition()),
        _context(),
    )

    assert _metric(result.metrics, "SKU_A_001", "distribution")["metric_value"][0] == 1.0 / 3.0


def test_distribution_zero_denominator_returns_null_issue():
    frame = _frame().with_columns(
        pl.lit(0.0).alias("active_store_count"),
        pl.lit(0.0).alias("selling_store_count"),
    )
    result = calculate_metrics(
        frame,
        (_distribution_definition(),),
        _context(),
    )

    assert _metric(result.metrics, "SKU_A_001", "distribution")["metric_value"][0] is None
    assert any(issue.issue_code == "ZERO_DISTRIBUTION_DENOMINATOR" for issue in result.quality_report.issues)


def test_distribution_is_retailer_isolated():
    result = calculate_metrics(_frame(), (_sum_definition("units", "units"),), _context("retailer_b"))

    assert result.metrics["metric_value"].to_list() == [99.0]


def test_units_per_selling_store():
    result = calculate_metrics(
        _frame(),
        (_sum_definition("units", "units"), _selling_store_definition(), _velocity_definition("units", "units_per_selling_store")),
        _context(),
    )

    assert _metric(result.metrics, "SKU_A_001", "velocity")["metric_value"][0] == 8.0


def test_velocity_zero_selling_stores_returns_null_issue():
    result = calculate_metrics(
        _frame(),
        (_sum_definition("units", "units"), _selling_store_definition(), _velocity_definition("units", "units_per_selling_store")),
        _context(),
    )

    assert _metric(result.metrics, "SKU_A_003", "velocity")["metric_value"][0] is None
    assert any(issue.issue_code == "ZERO_VELOCITY_DENOMINATOR" for issue in result.quality_report.issues)


def test_negative_correction_does_not_create_selling_store():
    result = calculate_metrics(_frame(), (_selling_store_definition(),), _context())

    assert _metric(result.metrics, "SKU_A_001", "selling_store_count")["metric_value"][0] == 1.0


def test_category_revenue_share():
    result = calculate_metrics(_frame(), (_sum_definition("revenue_net", "revenue"),), _context())
    share = calculate_metric_share(result.metrics)

    assert _metric(share.metrics, "SKU_A_001", "category_revenue_share")["metric_value"][0] == 80.0 / 130.0


def test_category_units_share():
    result = calculate_metrics(_frame(), (_sum_definition("units", "units"),), _context())
    share = calculate_metric_share(result.metrics)

    assert _metric(share.metrics, "SKU_A_001", "category_units_share")["metric_value"][0] == 8.0 / 13.0


def test_category_margin_share():
    result = calculate_metrics(_frame(), (_sum_definition("retailer_margin_abs", "retailer_margin_abs"),), _context())
    share = calculate_metric_share(result.metrics)

    assert round(_metric(share.metrics, "SKU_A_001", "category_margin_share")["metric_value"][0], 10) == round(24.0 / 34.0, 10)


def test_share_zero_denominator_returns_null_issue():
    frame = _frame().with_columns(pl.lit(0.0).alias("revenue_net"))
    result = calculate_metrics(frame, (_sum_definition("revenue_net", "revenue"),), _context())
    share = calculate_metric_share(result.metrics)

    assert all(value is None for value in share.metrics["metric_value"].to_list())
    assert share.quality_report.issues[0].issue_code == "ZERO_SHARE_DENOMINATOR"


def test_category_shares_sum_to_one_when_valid():
    result = calculate_metrics(_frame(), (_sum_definition("revenue_net", "revenue"),), _context())
    share = calculate_metric_share(result.metrics)

    assert round(share.metrics["metric_value"].sum(), 10) == 1.0


def test_metrics_do_not_mutate_enriched_input():
    frame = _frame()
    before = frame.clone()

    calculate_metrics(frame, (_sum_definition("revenue_net", "revenue"),), _context())

    assert frame.equals(before)


def test_share_denominator_does_not_mix_entity_grains():
    sku_result = calculate_metrics(_frame(), (_sum_definition("revenue_net", "revenue"),), _context())
    brand_definition = _sum_definition("revenue_net", "revenue", grain=("period", "category", "brand"), entity_type="brand")
    brand_result = calculate_metrics(_frame(), (brand_definition,), _context())
    combined = pl.concat([sku_result.metrics, brand_result.metrics], how="diagonal")

    share = calculate_metric_share(combined)

    sku_share_sum = share.metrics.filter(pl.col("entity_type") == "sku")["metric_value"].sum()
    brand_share_sum = share.metrics.filter(pl.col("entity_type") == "brand")["metric_value"].sum()
    assert round(sku_share_sum, 10) == 1.0
    assert round(brand_share_sum, 10) == 1.0


def test_ratio_metric_order_is_independent():
    result = calculate_metrics(
        _frame(),
        (_distribution_definition(), _selling_store_definition(), _active_store_definition(broadcast=True)),
        _context(),
    )

    assert _metric(result.metrics, "SKU_A_001", "distribution")["metric_value"][0] == 1.0 / 3.0


def test_same_source_id_is_required_for_metrics_scope():
    frame = pl.concat(
        [
            _frame(),
            _frame().with_columns(pl.lit("source_b").alias("source_id"), pl.lit(1000.0).alias("revenue_net")),
        ],
        how="diagonal",
    )

    result = calculate_metrics(frame, (_sum_definition("revenue_net", "revenue"),), _context(source_id="source_b"))

    assert result.metrics["metric_value"].sum() == 4000.0


def test_public_metric_config_includes_distribution_and_velocity_for_required_grains():
    registry = load_metric_definition_config("config/public/demo/metric_definitions.yaml")
    scoped = registry.for_context(_context())
    distribution_grains = {definition.entity_type for definition in scoped.definitions if definition.concept == "distribution"}
    velocity_grains = {definition.entity_type for definition in scoped.definitions if definition.concept == "velocity"}

    assert {"sku", "brand", "manufacturer", "category"}.issubset(distribution_grains)
    assert {"sku", "brand", "manufacturer", "category"}.issubset(velocity_grains)


def test_public_sku_distribution_uses_monthly_store_universe_not_category_local():
    frame = pl.concat(
        [
            _frame(),
            pl.DataFrame(
                {
                    "analysis_run_id": ["run_a"],
                    "retailer_id": ["retailer_a"],
                    "source_id": ["source_a"],
                    "period": [date(2026, 1, 1)],
                    "category": ["CATEGORY_REDUCED"],
                    "brand": ["BRAND_C"],
                    "manufacturer": ["MANUFACTURER_C"],
                    "canonical_product_id": ["SKU_A_004"],
                    "canonical_store_id": ["STORE_A_004"],
                    "units": [1.0],
                    "revenue_net": [10.0],
                    "revenue_vat": [12.0],
                    "retailer_margin_abs": [2.0],
                    "shelf_price_vat": [12.0],
                    "input_price_vat": [10.0],
                }
            ),
        ],
        how="diagonal",
    )
    registry = load_metric_definition_config("config/public/demo/metric_definitions.yaml").for_context(_context())
    definitions = tuple(registry.get(name) for name in ("selling_store_count", "active_store_count", "numeric_distribution"))

    result = calculate_metrics(frame, definitions, _context(), metric_config_hash=registry.config_hash)

    assert _metric_by_name(result.metrics, "SKU_A_001", "active_store_count")["metric_value"][0] == 4.0
    assert _metric_by_name(result.metrics, "SKU_A_001", "numeric_distribution")["metric_value"][0] == 1.0 / 4.0


def test_brand_distribution_uses_monthly_store_universe_and_distinct_selling_stores():
    result = calculate_metrics(_frame(), _grain_metric_definitions("brand", ("period", "category", "brand")), _context())

    assert _metric_by_name(result.metrics, "BRAND_A", "brand_selling_store_count")["metric_value"][0] == 1.0
    assert _metric_by_name(result.metrics, "BRAND_A", "brand_active_store_count")["metric_value"][0] == 3.0
    assert _metric_by_name(result.metrics, "BRAND_A", "brand_numeric_distribution")["metric_value"][0] == 1.0 / 3.0


def test_manufacturer_distribution_counts_duplicate_store_once():
    result = calculate_metrics(_frame(), _grain_metric_definitions("manufacturer", ("period", "category", "manufacturer")), _context())

    assert _metric_by_name(result.metrics, "MANUFACTURER_A", "manufacturer_selling_store_count")["metric_value"][0] == 1.0
    assert _metric_by_name(result.metrics, "MANUFACTURER_A", "manufacturer_numeric_distribution")["metric_value"][0] == 1.0 / 3.0


def test_category_distribution_uses_target_grain_distinct_store_count():
    result = calculate_metrics(_frame(), _grain_metric_definitions("category", ("period", "category")), _context())

    assert _metric_by_name(result.metrics, "CATEGORY_STANDARD", "category_selling_store_count")["metric_value"][0] == 1.0
    assert _metric_by_name(result.metrics, "CATEGORY_STANDARD", "category_numeric_distribution")["metric_value"][0] == 1.0 / 3.0


def test_brand_velocity_is_ratio_of_sums_not_mean_of_sku_velocities():
    result = calculate_metrics(
        _frame(),
        (
            *_grain_metric_definitions("sku", ("period", "category", "canonical_product_id"), prefix="sku"),
            *_grain_metric_definitions("brand", ("period", "category", "brand")),
        ),
        _context(),
    )

    brand_velocity = _metric_by_name(result.metrics, "BRAND_A", "brand_units_per_selling_store")["metric_value"][0]
    sku_velocities = result.metrics.filter(
        (pl.col("entity_type") == "sku")
        & (pl.col("metric_name") == "sku_units_per_selling_store")
        & (pl.col("entity_id").is_in(["SKU_A_001", "SKU_A_002"]))
    )["metric_value"].to_list()
    assert brand_velocity == 13.0
    assert brand_velocity != sum(sku_velocities) / len(sku_velocities)


def test_manufacturer_and_category_revenue_velocity_use_selling_store_denominator():
    definitions = (
        *_grain_metric_definitions("manufacturer", ("period", "category", "manufacturer")),
        *_grain_metric_definitions("category", ("period", "category")),
    )
    result = calculate_metrics(_frame(), definitions, _context())

    assert _metric_by_name(result.metrics, "MANUFACTURER_A", "manufacturer_revenue_net_per_selling_store")["metric_value"][0] == 130.0
    assert _metric_by_name(result.metrics, "CATEGORY_STANDARD", "category_revenue_net_per_selling_store")["metric_value"][0] == 130.0


def test_multi_grain_distribution_is_retailer_and_source_isolated():
    frame = pl.concat(
        [
            _frame(),
            _frame().with_columns(pl.lit("source_b").alias("source_id"), pl.lit("STORE_B_001").alias("canonical_store_id")),
            _frame().with_columns(pl.lit("retailer_b").alias("retailer_id"), pl.lit("STORE_C_001").alias("canonical_store_id")),
        ],
        how="diagonal",
    )

    result = calculate_metrics(frame, _grain_metric_definitions("brand", ("period", "category", "brand")), _context("retailer_a", "source_a"))

    assert _metric_by_name(result.metrics, "BRAND_A", "brand_active_store_count")["metric_value"][0] == 3.0
    assert set(result.metrics["retailer_id"].unique().to_list()) == {"retailer_a"}
    assert set(result.metrics["source_id"].unique().to_list()) == {"source_a"}


def _sum_definition(column: str, concept: str, *, grain=("period", "category", "canonical_product_id"), entity_type="sku") -> MetricDefinition:
    return MetricDefinition(
        column,
        concept,
        f"retailer_a.{column}.v1",
        "v1",
        "sum",
        source_column=column,
        grain=grain,
        entity_type=entity_type,
        retailer_id="retailer_a",
        rule_version="rules_v1",
    )


def _selling_store_definition() -> MetricDefinition:
    return MetricDefinition(
        "selling_store_count",
        "selling_store_count",
        "retailer_a.selling_store_count.v1",
        "v1",
        "distinct_count",
        distinct_column="canonical_store_id",
        condition={"units": {"gt": 0}},
        retailer_id="retailer_a",
        rule_version="rules_v1",
    )


def _active_store_definition(*, broadcast: bool = False) -> MetricDefinition:
    return MetricDefinition(
        "active_store_count",
        "active_store_count",
        "retailer_a.active_store_count.v1",
        "v1",
        "distinct_count",
        distinct_column="canonical_store_id",
        grain=("period", "category", "canonical_product_id"),
        broadcast_grain=("period", "category") if broadcast else None,
        retailer_id="retailer_a",
        rule_version="rules_v1",
    )


def _distribution_definition() -> MetricDefinition:
    return MetricDefinition(
        "numeric_distribution",
        "distribution",
        "retailer_a.numeric_distribution.v1",
        "v1",
        "ratio_of_sums",
        numerator="selling_store_count",
        denominator="active_store_count",
        retailer_id="retailer_a",
        rule_version="rules_v1",
    )


def _velocity_definition(numerator: str, name: str) -> MetricDefinition:
    return MetricDefinition(
        name,
        "velocity",
        f"retailer_a.{name}.v1",
        "v1",
        "ratio_of_sums",
        numerator=numerator,
        denominator="selling_store_count",
        retailer_id="retailer_a",
        rule_version="rules_v1",
    )


def _metric(frame: pl.DataFrame, entity_id: str, concept: str) -> pl.DataFrame:
    return frame.filter((pl.col("entity_id") == entity_id) & (pl.col("concept") == concept))


def _metric_by_name(frame: pl.DataFrame, entity_id: str, metric_name: str) -> pl.DataFrame:
    return frame.filter((pl.col("entity_id") == entity_id) & (pl.col("metric_name") == metric_name))


def _grain_metric_definitions(entity_type: str, grain: tuple[str, ...], *, prefix: str | None = None) -> tuple[MetricDefinition, ...]:
    name_prefix = prefix or entity_type
    return (
        MetricDefinition(
            f"{name_prefix}_revenue_net",
            "revenue",
            f"retailer_a.{name_prefix}_revenue_net.v1",
            "v1",
            "sum",
            source_column="revenue_net",
            grain=grain,
            entity_type=entity_type,
            retailer_id="retailer_a",
            rule_version="rules_v1",
        ),
        MetricDefinition(
            f"{name_prefix}_units",
            "units",
            f"retailer_a.{name_prefix}_units.v1",
            "v1",
            "sum",
            source_column="units",
            grain=grain,
            entity_type=entity_type,
            retailer_id="retailer_a",
            rule_version="rules_v1",
        ),
        MetricDefinition(
            f"{name_prefix}_selling_store_count",
            "selling_store_count",
            f"retailer_a.{name_prefix}_selling_store_count.v1",
            "v1",
            "distinct_count",
            distinct_column="canonical_store_id",
            condition={"units": {"gt": 0}},
            grain=grain,
            entity_type=entity_type,
            retailer_id="retailer_a",
            rule_version="rules_v1",
        ),
        MetricDefinition(
            f"{name_prefix}_active_store_count",
            "active_store_count",
            f"retailer_a.{name_prefix}_active_store_count.v1",
            "v1",
            "distinct_count",
            distinct_column="canonical_store_id",
            grain=grain,
            broadcast_grain=("period",),
            entity_type=entity_type,
            retailer_id="retailer_a",
            rule_version="rules_v1",
        ),
        MetricDefinition(
            f"{name_prefix}_numeric_distribution",
            "distribution",
            f"retailer_a.{name_prefix}_numeric_distribution.v1",
            "v1",
            "ratio_of_sums",
            numerator=f"{name_prefix}_selling_store_count",
            denominator=f"{name_prefix}_active_store_count",
            grain=grain,
            entity_type=entity_type,
            retailer_id="retailer_a",
            rule_version="rules_v1",
        ),
        MetricDefinition(
            f"{name_prefix}_units_per_selling_store",
            "velocity",
            f"retailer_a.{name_prefix}_units_per_selling_store.v1",
            "v1",
            "ratio_of_sums",
            numerator=f"{name_prefix}_units",
            denominator=f"{name_prefix}_selling_store_count",
            grain=grain,
            entity_type=entity_type,
            retailer_id="retailer_a",
            rule_version="rules_v1",
        ),
        MetricDefinition(
            f"{name_prefix}_revenue_net_per_selling_store",
            "velocity",
            f"retailer_a.{name_prefix}_revenue_net_per_selling_store.v1",
            "v1",
            "ratio_of_sums",
            numerator=f"{name_prefix}_revenue_net",
            denominator=f"{name_prefix}_selling_store_count",
            grain=grain,
            entity_type=entity_type,
            retailer_id="retailer_a",
            rule_version="rules_v1",
        ),
    )
