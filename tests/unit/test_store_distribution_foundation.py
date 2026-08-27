from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from retail_analytics.mart import (
    ComparisonMode,
    DashboardMartQueryService,
    DashboardMetricQueryRequest,
    MartBuildMetadata,
    MartBuildStatus,
    PeriodMode,
    PrivateLabelScope,
    build_monthly_store_universe,
    build_product_store_metric_facts,
    write_mart_metric_facts,
    write_monthly_store_universe,
    write_product_store_metric_facts,
)
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA, RangeAggregationStrategy
from retail_analytics.mart.query import STORE_FORMAT_DISTRIBUTION_CONCEPT


def test_monthly_store_universe_collapses_canonical_store_aliases() -> None:
    universe = build_monthly_store_universe(
        _source_rows_with_alias_duplicate(),
        build_metadata=_build(),
        source_revision_id="revision_a",
        store_alias_mapping_version="alias_hash_a",
        created_at=_created_at(),
    )

    assert universe.height == 3
    assert universe.filter(pl.col("store_format") == "format_a")["canonical_store_id"].sort().to_list() == [
        "STORE_1",
        "STORE_2",
    ]
    assert universe["store_alias_mapping_version"].unique().to_list() == ["alias_hash_a"]


def test_monthly_store_universe_rejects_mixed_source_revisions() -> None:
    frame = _source_rows_with_alias_duplicate().with_columns(
        pl.Series("source_revision_id", ["revision_a", "revision_b", "revision_a", "revision_a", "revision_a"])
    )

    with pytest.raises(ValueError, match="one active source_revision_id"):
        build_monthly_store_universe(frame, build_metadata=_build(source_revision_ids=("revision_a", "revision_b")))


def test_store_format_sku_distribution_uses_format_denominator_not_category_rows(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(_distribution_request("sku", ("SKU_A",), entity_filters={"store_format": ("format_a",)}))

    result = _single_result(response)
    assert result.metric_concept == STORE_FORMAT_DISTRIBUTION_CONCEPT
    assert result.numerator_value == 1.0
    assert result.denominator_value == 3.0
    assert result.value == pytest.approx(1.0 / 3.0)
    assert response.limitations == ()


def test_store_format_distribution_accepts_separate_store_universe_lineage(tmp_path) -> None:
    service = _service(tmp_path, separate_store_universe_lineage=True)

    response = service.query(_distribution_request("sku", ("SKU_A",), entity_filters={"store_format": ("format_a",)}))

    result = _single_result(response)
    assert result.numerator_value == 1.0
    assert result.denominator_value == 3.0
    assert result.value == pytest.approx(1.0 / 3.0)
    assert result.provenance is not None
    assert result.provenance.payload["source_evidence"]["denominator_universe_type"] == "monthly_store_format_universe"


def test_store_format_distribution_returns_zero_for_observed_no_sales_entity(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(_distribution_request("sku", ("SKU_ZERO",), entity_filters={"store_format": ("format_a",)}))

    result = _single_result(response)
    assert result.numerator_value == 0.0
    assert result.denominator_value == 3.0
    assert result.value == 0.0
    assert response.limitations == ()


def test_store_format_brand_manufacturer_and_category_use_distinct_store_union(tmp_path) -> None:
    service = _service(tmp_path)

    for grain, entity in (("brand", "BRAND_A"), ("manufacturer", "MANUFACTURER_A"), ("category", "CATEGORY_A")):
        response = service.query(_distribution_request(grain, (entity,), entity_filters={"store_format": ("format_a",)}))
        result = _single_result(response)
        assert result.numerator_value == 2.0
        assert result.denominator_value == 3.0
        assert result.value == pytest.approx(2.0 / 3.0)


def test_store_format_multi_sku_filter_counts_store_union_once(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(
        _distribution_request(
            "category",
            ("CATEGORY_A",),
            entity_filters={"store_format": ("format_a",), "sku": ("SKU_A", "SKU_B")},
        )
    )

    result = _single_result(response)
    assert result.numerator_value == 2.0
    assert result.denominator_value == 3.0
    assert result.value == pytest.approx(2.0 / 3.0)


def test_store_format_stm_scope_does_not_shrink_denominator(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(
        _distribution_request(
            "sku",
            ("SKU_PRIVATE",),
            entity_filters={"store_format": ("format_a",)},
            private_label_scope=PrivateLabelScope.ONLY,
        )
    )

    result = _single_result(response)
    assert result.numerator_value == 1.0
    assert result.denominator_value == 3.0
    assert result.value == pytest.approx(1.0 / 3.0)


def test_store_filter_distribution_fails_closed(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(
        _distribution_request(
            "sku",
            ("SKU_A",),
            entity_filters={"store_format": ("format_a",), "store": ("STORE_1",)},
        )
    )

    assert response.metric_results == ()
    assert "store_filter_distribution_unsupported" in {item.issue_code for item in response.limitations}


def test_store_format_distribution_range_is_period_only_not_averaged(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(
        _distribution_request(
            "sku",
            ("SKU_A",),
            entity_filters={"store_format": ("format_a",)},
            period_mode=PeriodMode.DATE_RANGE,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 2, 1),
        )
    )

    result = _single_result(response)
    assert result.value is None
    assert result.period_values[0].value == pytest.approx(1.0 / 3.0)
    assert result.period_values[1].value == pytest.approx(2.0 / 3.0)
    assert "range_aggregation_period_only" in {item.issue_code for item in response.limitations}


def test_store_format_distribution_provenance_identifies_components(tmp_path) -> None:
    service = _service(tmp_path)

    result = _single_result(
        service.query(_distribution_request("brand", ("BRAND_A",), entity_filters={"store_format": ("format_a",)}))
    )
    provenance = result.provenance

    assert provenance is not None
    assert provenance.payload["business_rule"]["business_rule_id"] == "BR-009B"
    assert provenance.payload["source_evidence"]["denominator_universe_type"] == "monthly_store_format_universe"
    assert provenance.payload["source_evidence"]["store_alias_mapping_versions"] == ("alias_hash_a",)
    assert provenance.payload["source_evidence"]["numerator_metric_names"] == ("selling_store_count",)
    assert provenance.payload["source_evidence"]["denominator_metric_names"] == ("monthly_store_format_universe_count",)


def test_global_distribution_store_format_filter_fails_closed(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="sku",
            entity_ids=("SKU_A",),
            metric_concepts=("distribution",),
            entity_filters={"store_format": ("format_a",)},
        )
    )

    assert response.metric_results == ()
    assert "global_distribution_store_format_filter_unsupported" in {item.issue_code for item in response.limitations}


def test_store_format_distribution_mixed_metric_request_fails_closed(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="sku",
            entity_ids=("SKU_A",),
            metric_concepts=(STORE_FORMAT_DISTRIBUTION_CONCEPT, "revenue"),
            entity_filters={"store_format": ("format_a",)},
        )
    )

    assert response.metric_results == ()
    assert "store_format_distribution_mixed_metric_request_unsupported" in {
        item.issue_code for item in response.limitations
    }


def test_store_format_distribution_metric_definition_ids_fail_closed(tmp_path) -> None:
    service = _service(tmp_path)

    response = service.query(
        DashboardMetricQueryRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="sku",
            entity_ids=("SKU_A",),
            metric_concepts=(STORE_FORMAT_DISTRIBUTION_CONCEPT,),
            metric_definition_ids=("retailer_a.sku.revenue.v1",),
            entity_filters={"store_format": ("format_a",)},
        )
    )

    assert response.metric_results == ()
    assert "store_format_distribution_metric_definition_ids_unsupported" in {
        item.issue_code for item in response.limitations
    }


def _service(tmp_path, *, separate_store_universe_lineage: bool = False) -> DashboardMartQueryService:
    metric_facts_path = tmp_path / "metric_facts.parquet"
    product_store_path = tmp_path / "product_store.parquet"
    store_universe_path = tmp_path / "store_universe.parquet"
    build = _build(period_end=date(2026, 2, 28))
    write_mart_metric_facts(_base_metric_facts(), metric_facts_path)
    source = _source_rows()
    write_product_store_metric_facts(
        pl.concat(
            [
                build_product_store_metric_facts(source, build_metadata=build, source_revision_id="revision_a", created_at=_created_at()),
                build_product_store_metric_facts(
                    source,
                    build_metadata=build,
                    source_revision_id="revision_a",
                    private_label_scope=PrivateLabelScope.ONLY,
                    created_at=_created_at(),
                ),
            ],
            how="diagonal",
        ),
        product_store_path,
    )
    store_universe = build_monthly_store_universe(
        source,
        build_metadata=build,
        source_revision_id="revision_a",
        store_alias_mapping_version="alias_hash_a",
        created_at=_created_at(),
    )
    if separate_store_universe_lineage:
        store_universe = store_universe.with_columns(
            pl.lit("store_universe_build_a").alias("mart_build_id"),
            pl.lit("store_universe_revision_a").alias("source_revision_id"),
            pl.col("period_start").dt.strftime("%Y-%m").alias("business_period_id"),
        )
    write_monthly_store_universe(store_universe, store_universe_path)
    return DashboardMartQueryService(
        metric_facts_path,
        mart_builds=(build,),
        product_store_facts_path=product_store_path,
        store_universe_path=store_universe_path,
    )


def _distribution_request(
    grain_id: str,
    entity_ids: tuple[str, ...],
    *,
    entity_filters: dict[str, tuple[str, ...]],
    period_mode: PeriodMode = PeriodMode.SINGLE_PERIOD,
    date_from: date = date(2026, 1, 1),
    date_to: date = date(2026, 1, 1),
    comparison_mode: ComparisonMode = ComparisonMode.NONE,
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
) -> DashboardMetricQueryRequest:
    return DashboardMetricQueryRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=date_from,
        date_to=date_to,
        period_mode=period_mode,
        period_grain="month",
        grain_id=grain_id,
        entity_ids=entity_ids,
        entity_filters=entity_filters,
        metric_concepts=(STORE_FORMAT_DISTRIBUTION_CONCEPT,),
        comparison_mode=comparison_mode,
        private_label_scope=private_label_scope,
    )


def _single_result(response):
    assert len(response.metric_results) == 1
    return response.metric_results[0]


def _source_rows_with_alias_duplicate() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "retailer_id": ["retailer_a"] * 5,
            "source_id": ["source_a"] * 5,
            "analysis_run_id": ["analysis_a"] * 5,
            "source_revision_id": ["revision_a"] * 5,
            "period": [date(2026, 1, 1)] * 5,
            "category": ["CATEGORY_A"] * 5,
            "manufacturer": ["MANUFACTURER_A"] * 5,
            "brand": ["BRAND_A"] * 5,
            "canonical_product_id": ["SKU_A", "SKU_A", "SKU_B", "SKU_C", "SKU_D"],
            "canonical_store_id": ["STORE_1", "STORE_1", "STORE_2", "STORE_3", "STORE_3"],
            "units": [1.0, 2.0, 3.0, 4.0, 5.0],
            "revenue_vat": [1.0] * 5,
            "revenue_net": [1.0] * 5,
            "retailer_margin_abs": [1.0] * 5,
            "shelf_price_vat": [1.0] * 5,
            "input_price_vat": [1.0] * 5,
            "store_format": ["format_a", "format_a", "format_a", "format_b", "format_b"],
            "region": ["region_a"] * 5,
            "private_label_flag": [False] * 5,
        }
    )


def _source_rows() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    specs = (
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_1", "format_a", 1.0, False),
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_ZERO", "SKU_ZERO", "STORE_2", "format_a", 0.0, False),
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_B", "STORE_1", "format_a", 2.0, False),
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_B", "STORE_2", "format_a", 3.0, False),
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_PRIVATE", "SKU_PRIVATE", "STORE_1", "format_a", 4.0, True),
        (date(2026, 1, 1), "CATEGORY_B", "MANUFACTURER_B", "BRAND_C", "SKU_C", "STORE_3", "format_a", 5.0, False),
        (date(2026, 1, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_4", "format_b", 6.0, False),
        (date(2026, 2, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_1", "format_a", 1.0, False),
        (date(2026, 2, 1), "CATEGORY_A", "MANUFACTURER_A", "BRAND_A", "SKU_A", "STORE_2", "format_a", 1.0, False),
        (date(2026, 2, 1), "CATEGORY_B", "MANUFACTURER_B", "BRAND_C", "SKU_C", "STORE_3", "format_a", 1.0, False),
    )
    for period, category, manufacturer, brand, sku, store, store_format, units, private_label in specs:
        rows.append(
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "analysis_run_id": "analysis_a",
                "source_revision_id": "revision_a",
                "period": period,
                "category": category,
                "manufacturer": manufacturer,
                "brand": brand,
                "canonical_product_id": sku,
                "canonical_store_id": store,
                "sku_name": f"{sku} name",
                "units": units,
                "revenue_vat": units * 12.0,
                "revenue_net": units * 10.0,
                "retailer_margin_abs": units * 2.0,
                "shelf_price_vat": 12.0,
                "input_price_vat": 8.0,
                "private_label_flag": private_label,
                "store_format": store_format,
                "region": "region_a",
            }
        )
    return pl.DataFrame(rows)


def _base_metric_facts() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "retailer_id": "retailer_a",
                "source_id": "source_a",
                "source_revision_id": "revision_a",
                "analysis_run_id": "analysis_a",
                "mart_build_id": "build_a",
                "private_label_scope": "INCLUDE",
                "period_grain": "month",
                "period_start": date(2026, 1, 1),
                "period_end": date(2026, 1, 31),
                "business_period_id": "2026-01",
                "grain_id": "network",
                "entity_id": "network",
                "parent_entity_ids": "{}",
                "metric_concept": "revenue",
                "metric_name": "revenue",
                "metric_definition_id": "retailer_a.network.revenue.v1",
                "metric_definition_version": "v1",
                "metric_config_hash": "hash_a",
                "semantic_family": "revenue",
                "semantic_compatibility_version": "v1",
                "cross_retailer_comparable": False,
                "value": 1.0,
                "numerator_value": None,
                "denominator_value": None,
                "business_rule_id": None,
                "denominator_universe_type": None,
                "store_alias_mapping_version": None,
                "numerator_metric_name": None,
                "denominator_metric_name": None,
                "aggregation": "sum",
                "range_aggregation_strategy": RangeAggregationStrategy.SUM_AVAILABLE_PERIODS.value,
                "share_scope": None,
                "rule_version": "rules_v1",
                "quality_status": "valid",
                "quality_flags": None,
                "created_at": _created_at(),
            }
        ],
        schema=MART_METRIC_FACT_SCHEMA,
    )


def _build(
    *,
    source_revision_ids: tuple[str, ...] = ("revision_a",),
    period_end: date = date(2026, 1, 31),
) -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id="build_a",
        built_at=_created_at(),
        build_version="mart_v1",
        code_version="test",
        retailer_id="retailer_a",
        source_ids=("source_a",),
        source_revision_ids=source_revision_ids,
        analysis_run_ids=("analysis_a",),
        metric_config_hashes=("hash_a",),
        rule_versions=("rules_v1",),
        status=MartBuildStatus.APPROVED,
        period_grain="month",
        period_start=date(2026, 1, 1),
        period_end=period_end,
    )


def _created_at() -> datetime:
    return datetime(2026, 1, 15, tzinfo=UTC)
