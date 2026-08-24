"""Dashboard runtime wiring over mart query services."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from retail_analytics.history import PeriodGrain, SourceLedgerEntry, source_artifact_id
from retail_analytics.mart import (
    DashboardMartQueryService,
    EffectiveMetricCatalogEntry,
    MartBuildMetadata,
    MartBuildStatus,
    MetricAvailabilityStatus,
    PrivateLabelScope,
    PrivateMetricCatalogOverride,
    RangeAggregationStrategy,
    load_public_metric_catalog,
    merge_metric_catalog,
    write_mart_metric_facts,
)
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA

APP_TITLE = "Аналитика продаж"
SUPPORTED_GRAINS = ("network", "category", "manufacturer", "brand", "sku", "store")
SUPPORTED_PERIOD_MODES = ("SINGLE_PERIOD", "DATE_RANGE", "FULL_AVAILABLE_HISTORY")
SUPPORTED_COMPARISON_MODES = ("NONE", "YOY", "MOM", "PREVIOUS_AVAILABLE")
SUPPORTED_PRIVATE_LABEL_SCOPES = ("INCLUDE", "EXCLUDE", "ONLY")


@dataclass(frozen=True)
class DashboardRuntimeRetailer:
    """Retailer/source labels and UI terminology loaded from runtime config."""

    retailer_id: str
    display_label: str
    source_id: str
    source_label: str
    private_label_display_name: str = "выбранный ассортимент"
    default_mart_build_id: str | None = None


@dataclass(frozen=True)
class DashboardRuntime:
    """Concrete dashboard runtime over a mart query service."""

    query_service: DashboardMartQueryService
    catalog: tuple[EffectiveMetricCatalogEntry, ...]
    retailers: tuple[DashboardRuntimeRetailer, ...]

    def runtime_metadata(self) -> dict[str, Any]:
        """Return dashboard shell metadata without private business semantics."""

        default = self.retailers[0]
        return {
            "app_title": APP_TITLE,
            "retailers": [
                {
                    "retailer_id": item.retailer_id,
                    "display_label": item.display_label,
                    "source_id": item.source_id,
                    "source_label": item.source_label,
                    "private_label_display_name": item.private_label_display_name,
                    "default_mart_build_id": item.default_mart_build_id,
                }
                for item in self.retailers
            ],
            "default_retailer_id": default.retailer_id,
            "default_source_id": default.source_id,
            "supported_grains": list(SUPPORTED_GRAINS),
            "supported_period_modes": list(SUPPORTED_PERIOD_MODES),
            "supported_comparison_modes": list(SUPPORTED_COMPARISON_MODES),
            "supported_private_label_scopes": list(SUPPORTED_PRIVATE_LABEL_SCOPES),
        }

    def effective_catalog(self, *, retailer_id: str, source_id: str) -> tuple[EffectiveMetricCatalogEntry, ...]:
        """Return effective catalog entries for one retailer/source scope."""

        return tuple(
            entry
            for entry in self.catalog
            if entry.retailer_id == retailer_id and entry.source_id in (None, source_id)
        )


def build_synthetic_dashboard_runtime(storage_root: str | Path | None = None) -> DashboardRuntime:
    """Build a publication-safe local runtime backed by synthetic mart facts."""

    root = Path(storage_root) if storage_root is not None else Path(tempfile.gettempdir()) / "retail_analytics_dashboard"
    root.mkdir(parents=True, exist_ok=True)
    public_catalog = load_public_metric_catalog("config/public/dashboard_metric_catalog.yaml")
    build = _synthetic_build()
    catalog = merge_metric_catalog(
        public_catalog,
        _synthetic_overrides(),
        retailer_id="retailer_a",
        source_id="source_a",
    )
    facts_path = root / "synthetic_metric_facts.parquet"
    write_mart_metric_facts(_synthetic_facts(), facts_path)
    service = DashboardMartQueryService(
        facts_path,
        catalog=catalog,
        mart_builds=(build,),
        source_ledger=(_synthetic_ledger(),),
    )
    return DashboardRuntime(
        query_service=service,
        catalog=catalog,
        retailers=(
            DashboardRuntimeRetailer(
                retailer_id="retailer_a",
                display_label="retailer_a",
                source_id="source_a",
                source_label="source_a",
                default_mart_build_id=build.mart_build_id,
            ),
        ),
    )


def serialize_catalog(entries: tuple[EffectiveMetricCatalogEntry, ...]) -> list[dict[str, Any]]:
    """Serialize effective metric catalog entries for the browser."""

    return [
        {
            "metric_concept": entry.metric_concept,
            "display_label": entry.display_label,
            "description": entry.description,
            "format": entry.format.value,
            "dashboard_group": entry.dashboard_group.value,
            "grain_support": list(entry.grain_support),
            "period_support": list(entry.period_support),
            "comparison_support": list(entry.comparison_support),
            "range_aggregation_strategy": entry.range_aggregation_strategy.value,
            "share_scope": entry.share_scope,
            "availability_status": entry.availability_status.value,
            "limitations": list(entry.limitations),
            "metric_definition_id": entry.metric_definition_id,
            "metric_definition_version": entry.metric_definition_version,
            "metric_config_hash": entry.metric_config_hash,
            "rule_version": entry.rule_version,
            "private_label_scope_support": [scope.value for scope in entry.private_label_scope_support],
        }
        for entry in entries
    ]


def _synthetic_build() -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id="build_dashboard_synthetic",
        built_at=datetime(2026, 1, 15, tzinfo=UTC),
        build_version="dashboard_ui.synthetic.v1",
        code_version="test",
        retailer_id="retailer_a",
        source_ids=("source_a",),
        source_revision_ids=("revision_dashboard_synthetic",),
        analysis_run_ids=("analysis_dashboard_synthetic",),
        metric_config_hashes=("metric_hash_dashboard_synthetic",),
        rule_versions=("rules_dashboard_synthetic_v1",),
        status=MartBuildStatus.APPROVED,
        period_grain="month",
        period_start=date(2025, 3, 1),
        period_end=date(2026, 6, 30),
        fact_row_count=432,
    )


def _synthetic_ledger() -> SourceLedgerEntry:
    periods = _synthetic_periods()
    business_periods = tuple(period.strftime("%Y-%m") for period in periods)
    return SourceLedgerEntry(
        source_revision_id="revision_dashboard_synthetic",
        source_artifact_id=source_artifact_id("retailer_a", "source_a", "hash_dashboard_synthetic"),
        retailer_id="retailer_a",
        source_id="source_a",
        source_type="monthly_workbook",
        source_version="v1",
        source_file_id="source_synthetic.xlsx",
        source_hash="hash_dashboard_synthetic",
        raw_object_key="synthetic/source/source_synthetic.xlsx",
        size_bytes=1000,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        registered_at=datetime(2026, 1, 2, tzinfo=UTC),
        period_grain=PeriodGrain.MONTH,
        period_start=periods[0],
        period_end=date(2026, 6, 30),
        observed_periods=periods,
        business_period_ids=business_periods,
        active_business_period_ids=business_periods,
        source_schema_version="schema_v1",
        mapping_config_hash="mapping_hash_synthetic",
        rule_package_hash="rule_hash_synthetic",
        revision_state="active",
        is_active_revision=True,
    )


def _synthetic_overrides() -> tuple[PrivateMetricCatalogOverride, ...]:
    overrides: list[PrivateMetricCatalogOverride] = []
    partial = {"distribution", "velocity", "selling_store_count", "active_store_count", "sku_count"}
    metric_specs = {
        "revenue_vat": "Оборот с НДС",
        "revenue": "Оборот без НДС",
        "units": "Продажи, шт.",
        "retailer_margin_abs": "Абсолютная маржа",
        "retailer_margin_pct": "Маржинальность",
        "weighted_shelf_price_vat": "Средняя полочная цена с НДС",
        "weighted_input_price_vat": "Средняя входная цена с НДС",
        "selling_store_count": "ТТ с продажами",
        "active_store_count": "Активные ТТ",
        "distribution": "Дистрибуция",
        "velocity": "Продажи на ТТ",
        "sku_count": "SKU в периоде",
        "category_revenue_share": "Доля в обороте категории",
    }
    for concept, label in metric_specs.items():
        overrides.append(
            PrivateMetricCatalogOverride(
                retailer_id="retailer_a",
                source_id="source_a",
                metric_definition_id=f"retailer_a.network.{concept}.v1",
                metric_definition_version="v1",
                metric_concept=concept,
                display_label=label,
                grain_support=SUPPORTED_GRAINS,
                period_support=("month",),
                comparison_support=SUPPORTED_COMPARISON_MODES,
                availability_status=MetricAvailabilityStatus.PARTIAL
                if concept in partial
                else MetricAvailabilityStatus.READY,
                limitations=("period_only",) if concept in partial else (),
                metric_config_hash="metric_hash_dashboard_synthetic",
                rule_version="rules_dashboard_synthetic_v1",
                private_label_scope_support=(
                    PrivateLabelScope.INCLUDE,
                    PrivateLabelScope.EXCLUDE,
                    PrivateLabelScope.ONLY,
                ),
            )
        )
    return tuple(overrides)


def _synthetic_facts() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for scope in PrivateLabelScope:
        scope_multiplier = {
            PrivateLabelScope.INCLUDE: 1.0,
            PrivateLabelScope.EXCLUDE: 0.72,
            PrivateLabelScope.ONLY: 0.28,
        }[scope]
        for entity_index, grain in enumerate(SUPPORTED_GRAINS):
            entity_id = _entity_id(grain)
            for period_index, period in enumerate(_synthetic_periods()):
                base = (period_index + 2) * 100.0 * (1 + entity_index * 0.08)
                revenue = base * scope_multiplier
                revenue_vat = revenue * 1.2
                units = (base / 10.0) * scope_multiplier
                margin = revenue * (0.18 + entity_index * 0.01)
                weighted_shelf_numerator = units * (11.0 + period_index * 0.4)
                weighted_input_numerator = units * (7.0 + period_index * 0.3)
                rows.extend(
                    [
                        _fact(period, grain, entity_id, "revenue_vat", revenue_vat, "sum", scope),
                        _fact(period, grain, entity_id, "revenue", revenue, "sum", scope),
                        _fact(period, grain, entity_id, "units", units, "sum", scope),
                        _fact(period, grain, entity_id, "retailer_margin_abs", margin, "sum", scope),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "retailer_margin_pct",
                            margin / revenue if revenue else None,
                            "ratio_of_sums",
                            scope,
                            numerator=margin,
                            denominator=revenue,
                        ),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "weighted_shelf_price_vat",
                            weighted_shelf_numerator / units if units else None,
                            "weighted_average",
                            scope,
                            numerator=weighted_shelf_numerator,
                            denominator=units,
                        ),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "weighted_input_price_vat",
                            weighted_input_numerator / units if units else None,
                            "weighted_average",
                            scope,
                            numerator=weighted_input_numerator,
                            denominator=units,
                        ),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "selling_store_count",
                            14 + entity_index,
                            "distinct_count",
                            scope,
                            strategy=RangeAggregationStrategy.PERIOD_ONLY,
                        ),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "active_store_count",
                            20,
                            "distinct_count",
                            scope,
                            strategy=RangeAggregationStrategy.PERIOD_ONLY,
                        ),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "distribution",
                            (14 + entity_index) / 20,
                            "ratio_of_sums",
                            scope,
                            numerator=14 + entity_index,
                            denominator=20,
                            strategy=RangeAggregationStrategy.PERIOD_ONLY,
                        ),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "velocity",
                            units / (14 + entity_index),
                            "ratio_of_sums",
                            scope,
                            numerator=units,
                            denominator=14 + entity_index,
                            strategy=RangeAggregationStrategy.PERIOD_ONLY,
                        ),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "sku_count",
                            24 - entity_index,
                            "distinct_count",
                            scope,
                            strategy=RangeAggregationStrategy.PERIOD_ONLY,
                        ),
                        _fact(
                            period,
                            grain,
                            entity_id,
                            "category_revenue_share",
                            min(0.95, 0.16 + entity_index * 0.06),
                            "share",
                            scope,
                            numerator=revenue,
                            denominator=revenue / min(0.95, 0.16 + entity_index * 0.06),
                            share_scope="network",
                            strategy=RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
                        ),
                    ]
                )
    return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA)


def _fact(
    period: date,
    grain: str,
    entity_id: str,
    concept: str,
    value: float | None,
    aggregation: str,
    scope: PrivateLabelScope,
    *,
    numerator: float | None = None,
    denominator: float | None = None,
    share_scope: str | None = None,
    strategy: RangeAggregationStrategy | None = None,
) -> dict[str, object]:
    return {
        "retailer_id": "retailer_a",
        "source_id": "source_a",
        "source_revision_id": "revision_dashboard_synthetic",
        "analysis_run_id": "analysis_dashboard_synthetic",
        "mart_build_id": "build_dashboard_synthetic",
        "private_label_scope": scope.value,
        "period_grain": "month",
        "period_start": period,
        "period_end": date(period.year, period.month, 28),
        "business_period_id": period.strftime("%Y-%m"),
        "grain_id": grain,
        "entity_id": entity_id,
        "parent_entity_ids": "{}",
        "metric_concept": concept,
        "metric_name": concept,
        "metric_definition_id": f"retailer_a.network.{concept}.v1",
        "metric_definition_version": "v1",
        "metric_config_hash": "metric_hash_dashboard_synthetic",
        "semantic_family": concept,
        "semantic_compatibility_version": "v1",
        "cross_retailer_comparable": False,
        "value": value,
        "numerator_value": numerator,
        "denominator_value": denominator,
        "aggregation": aggregation,
        "range_aggregation_strategy": strategy or _strategy_for(aggregation),
        "share_scope": share_scope,
        "rule_version": "rules_dashboard_synthetic_v1",
        "quality_status": "valid",
        "quality_flags": None,
        "created_at": datetime(2026, 1, 15, tzinfo=UTC),
    }


def _strategy_for(aggregation: str) -> RangeAggregationStrategy:
    return {
        "sum": RangeAggregationStrategy.SUM_AVAILABLE_PERIODS,
        "ratio_of_sums": RangeAggregationStrategy.RATIO_OF_SUMS,
        "weighted_average": RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
        "distinct_count": RangeAggregationStrategy.PERIOD_ONLY,
        "share": RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
    }[aggregation]


def _synthetic_periods() -> tuple[date, ...]:
    return (
        date(2025, 3, 1),
        date(2025, 4, 1),
        date(2025, 6, 1),
        date(2025, 9, 1),
        date(2025, 12, 1),
        date(2026, 3, 1),
        date(2026, 4, 1),
        date(2026, 6, 1),
    )


def _entity_id(grain: str) -> str:
    return {
        "network": "network",
        "category": "CATEGORY_STANDARD",
        "manufacturer": "MANUFACTURER_A",
        "brand": "BRAND_A",
        "sku": "SKU_A_001",
        "store": "STORE_A_001",
    }[grain]
