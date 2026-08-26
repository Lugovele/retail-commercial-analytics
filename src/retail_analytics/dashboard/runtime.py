"""Dashboard runtime wiring over mart query services."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import yaml  # type: ignore[import-untyped]

from retail_analytics.history import (
    PeriodGrain,
    SourceLedgerEntry,
    read_source_ledger,
    source_artifact_id,
)
from retail_analytics.mart import (
    DashboardMartQueryService,
    EffectiveMetricCatalogEntry,
    MartBuildMetadata,
    MartBuildStatus,
    MetricAvailabilityStatus,
    PrivateLabelScope,
    PrivateMetricCatalogOverride,
    RangeAggregationStrategy,
    load_private_metric_catalog_overrides,
    load_public_metric_catalog,
    merge_metric_catalog,
    read_mart_build_metadata,
    write_mart_metric_facts,
)
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA

APP_TITLE = "Аналитика продаж"
SUPPORTED_GRAINS = ("network", "category", "manufacturer", "brand", "sku", "store")
SUPPORTED_PERIOD_MODES = ("SINGLE_PERIOD", "DATE_RANGE", "FULL_AVAILABLE_HISTORY")
SUPPORTED_COMPARISON_MODES = ("NONE", "YOY", "MOM", "PREVIOUS_AVAILABLE")
SUPPORTED_PRIVATE_LABEL_SCOPES = ("INCLUDE", "EXCLUDE", "ONLY")
DEFAULT_DASHBOARD_CONFIG_ENV = "RETAIL_ANALYTICS_DASHBOARD_CONFIG"
DEFAULT_DASHBOARD_MODE_ENV = "RETAIL_ANALYTICS_DASHBOARD_MODE"
SOURCE_LIKE_ENTITY_COLUMNS = {
    "category": "category",
    "manufacturer": "manufacturer",
    "brand": "brand",
    "sku": "canonical_product_id",
    "store": "canonical_store_id",
}
SOURCE_LIKE_LABEL_COLUMNS = {
    "store": ("store_display_label", "store_display_name", "store_name", "source_store_id", "canonical_store_id"),
}
ENTITY_PARENT_FILTERS = {
    "network": (),
    "category": (),
    "manufacturer": ("category",),
    "brand": ("category", "manufacturer"),
    "sku": ("category", "manufacturer", "brand"),
    "store": ("category", "manufacturer", "brand", "sku"),
}
PRODUCT_FILTERS = ("category", "manufacturer", "brand", "sku")
MART_PARENT_FILTER_SUPPORT = {
    "category": frozenset({"category"}),
    "manufacturer": frozenset({"category", "manufacturer"}),
    "brand": frozenset({"category", "brand"}),
    "sku": frozenset({"category", "sku"}),
}
NO_MATCHING_PRODUCT_FILTER = "__NO_MATCHING_PRODUCT_FILTER__"


class DashboardRuntimeMode(StrEnum):
    """Explicit dashboard runtime modes."""

    DEMO = "DEMO"
    PRIVATE = "PRIVATE"
    PRODUCTION = "PRODUCTION"


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
class DashboardRuntimeConfig:
    """Generic runtime config for a dashboard over persisted mart datasets."""

    mode: DashboardRuntimeMode
    metric_facts_path: Path | None = None
    mart_builds_path: Path | None = None
    source_ledger_path: Path | None = None
    events_path: Path | None = None
    event_rules_path: Path | None = None
    source_like_rows_path: Path | None = None
    product_store_facts_path: Path | None = None
    public_metric_catalog_path: Path = Path("config/public/dashboard_metric_catalog.yaml")
    private_metric_catalog_path: Path | None = None
    retailers: tuple[DashboardRuntimeRetailer, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", DashboardRuntimeMode(self.mode))
        for field_name in (
            "metric_facts_path",
            "mart_builds_path",
            "source_ledger_path",
            "events_path",
            "event_rules_path",
            "source_like_rows_path",
            "product_store_facts_path",
            "public_metric_catalog_path",
            "private_metric_catalog_path",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Path):
                object.__setattr__(self, field_name, Path(value))
        if self.mode in {DashboardRuntimeMode.PRIVATE, DashboardRuntimeMode.PRODUCTION}:
            missing = [
                name
                for name in (
                    "metric_facts_path",
                    "mart_builds_path",
                    "source_ledger_path",
                    "private_metric_catalog_path",
                )
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"Dashboard private runtime config is missing required paths: {', '.join(missing)}")
            if not self.retailers:
                raise ValueError("Dashboard private runtime config must declare at least one retailer/source scope")


@dataclass(frozen=True)
class DashboardRuntime:
    """Concrete dashboard runtime over a mart query service."""

    query_service: DashboardMartQueryService
    catalog: tuple[EffectiveMetricCatalogEntry, ...]
    retailers: tuple[DashboardRuntimeRetailer, ...]
    mode: DashboardRuntimeMode = DashboardRuntimeMode.DEMO
    events_path: Path | None = None
    event_rules_path: Path | None = None
    source_like_rows_path: Path | None = None
    product_store_facts_path: Path | None = None

    def runtime_metadata(self) -> dict[str, Any]:
        """Return dashboard shell metadata without private business semantics."""

        default = self.retailers[0]
        return {
            "app_title": APP_TITLE,
            "runtime_mode": self.mode.value,
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
            "signal_feed_configured": self.events_path is not None,
            "source_like_rows_configured": self.source_like_rows_path is not None,
            "product_store_facts_configured": self.product_store_facts_path is not None,
        }

    def effective_catalog(self, *, retailer_id: str, source_id: str) -> tuple[EffectiveMetricCatalogEntry, ...]:
        """Return effective catalog entries for one retailer/source scope."""

        return tuple(
            entry
            for entry in self.catalog
            if entry.retailer_id == retailer_id and entry.source_id in (None, source_id)
        )

    def options_metadata(
        self,
        *,
        retailer_id: str,
        source_id: str,
        private_label_scope: str | PrivateLabelScope = PrivateLabelScope.INCLUDE,
        date_from: date | None = None,
        date_to: date | None = None,
        parent_filters: dict[str, tuple[str, ...]] | None = None,
    ) -> dict[str, Any]:
        """Return period and entity filter options from persisted mart facts."""

        scope = PrivateLabelScope(private_label_scope)
        runtime_retailer = _runtime_retailer_for_scope(self.retailers, retailer_id, source_id)
        return {
            "periods": _period_options(self.query_service.metric_facts_path, retailer_id, source_id, scope),
            "entities": _entity_options(
                self.query_service.metric_facts_path,
                retailer_id,
                source_id,
                scope,
                date_from=date_from,
                date_to=date_to,
                parent_filters=parent_filters or {},
                source_like_rows_path=self.source_like_rows_path,
                source_revision_ids=_source_revision_ids_for_options(
                    self.query_service.mart_builds,
                    retailer_id,
                    source_id,
                    runtime_retailer.default_mart_build_id if runtime_retailer else None,
                ),
            ),
        }

    def query_entity_filters(
        self,
        *,
        retailer_id: str,
        source_id: str,
        private_label_scope: str | PrivateLabelScope,
        date_from: date | None,
        date_to: date | None,
        comparison_mode: str = "NONE",
        entity_filters: dict[str, tuple[str, ...]] | None,
    ) -> dict[str, tuple[str, ...]] | None:
        """Resolve UI entity filters to a mart-query-safe filter universe."""

        if not entity_filters:
            return entity_filters
        product_filters = {
            key: tuple(value for value in entity_filters.get(key, ()) if value)
            for key in PRODUCT_FILTERS
            if entity_filters.get(key)
        }
        if not product_filters or not _product_filters_need_sku_resolution(product_filters):
            return entity_filters
        resolved_skus = self._resolve_product_filter_skus(
            retailer_id=retailer_id,
            source_id=source_id,
            private_label_scope=private_label_scope,
            date_from=_source_like_resolution_start(
                self.query_service.metric_facts_path,
                retailer_id=retailer_id,
                source_id=source_id,
                private_label_scope=private_label_scope,
                date_from=date_from,
                comparison_mode=comparison_mode,
            ),
            date_to=date_to,
            product_filters=product_filters,
        )
        if resolved_skus is None:
            return entity_filters
        resolved = {
            key: values
            for key, values in entity_filters.items()
            if key not in PRODUCT_FILTERS and values
        }
        resolved["sku"] = resolved_skus or (NO_MATCHING_PRODUCT_FILTER,)
        return resolved

    def _resolve_product_filter_skus(
        self,
        *,
        retailer_id: str,
        source_id: str,
        private_label_scope: str | PrivateLabelScope,
        date_from: date | None,
        date_to: date | None,
        product_filters: dict[str, tuple[str, ...]],
    ) -> tuple[str, ...] | None:
        if self.source_like_rows_path is None or not self.source_like_rows_path.exists():
            return None
        available_columns = _source_columns(self.source_like_rows_path)
        if "canonical_product_id" not in available_columns:
            return None
        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "canonical_product_id IS NOT NULL",
            "canonical_product_id <> ''",
        ]
        params: list[Any] = [retailer_id, source_id]
        runtime_retailer = _runtime_retailer_for_scope(self.retailers, retailer_id, source_id)
        source_revision_ids = _source_revision_ids_for_options(
            self.query_service.mart_builds,
            retailer_id,
            source_id,
            runtime_retailer.default_mart_build_id if runtime_retailer else None,
        )
        if "source_revision_id" in available_columns and source_revision_ids:
            placeholders = ", ".join("?" for _ in source_revision_ids)
            clauses.append(f"source_revision_id IN ({placeholders})")
            params.extend(source_revision_ids)
        scope = PrivateLabelScope(private_label_scope)
        if "private_label_flag" in available_columns and scope != PrivateLabelScope.INCLUDE:
            clauses.append("private_label_flag = ?")
            params.append(scope == PrivateLabelScope.ONLY)
        if date_from is not None and "period" in available_columns:
            clauses.append("CAST(period AS DATE) >= CAST(? AS DATE)")
            params.append(date_from.isoformat())
        if date_to is not None and "period" in available_columns:
            clauses.append("CAST(period AS DATE) <= CAST(? AS DATE)")
            params.append(date_to.isoformat())
        for key, values in product_filters.items():
            column = SOURCE_LIKE_ENTITY_COLUMNS[key]
            if column not in available_columns:
                return None
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(values)
        rows = duckdb.sql(
            f"""
                SELECT DISTINCT canonical_product_id
                FROM read_parquet(?)
                WHERE {" AND ".join(clauses)}
                ORDER BY canonical_product_id
            """,
            params=[_duckdb_path(self.source_like_rows_path), *params],
        ).fetchall()
        return tuple(str(row[0]) for row in rows)


def build_dashboard_runtime(
    config: DashboardRuntimeConfig | None = None,
    *,
    mode: str | DashboardRuntimeMode | None = None,
    config_path: str | Path | None = None,
) -> DashboardRuntime:
    """Build an explicit demo or private dashboard runtime.

    Production/private modes require configuration and never fall back to the
    synthetic demo runtime.
    """

    env_mode = os.environ.get(DEFAULT_DASHBOARD_MODE_ENV)
    mode_was_explicit = mode is not None or env_mode is not None
    selected_mode = DashboardRuntimeMode(mode or env_mode or DashboardRuntimeMode.DEMO)
    if selected_mode == DashboardRuntimeMode.DEMO and config is None and config_path is None:
        return build_synthetic_dashboard_runtime()
    resolved_config = config or load_dashboard_runtime_config(config_path, mode=selected_mode)
    if (
        mode_was_explicit
        and selected_mode in {DashboardRuntimeMode.PRIVATE, DashboardRuntimeMode.PRODUCTION}
        and resolved_config.mode != selected_mode
    ):
        raise ValueError(
            f"Dashboard runtime mode mismatch: requested {selected_mode.value}, "
            f"config declares {resolved_config.mode.value}"
        )
    if resolved_config.mode == DashboardRuntimeMode.DEMO:
        return build_synthetic_dashboard_runtime()
    return build_private_dashboard_runtime(resolved_config)


def load_dashboard_runtime_config(
    path: str | Path | None = None,
    *,
    mode: str | DashboardRuntimeMode | None = None,
) -> DashboardRuntimeConfig:
    """Load generic private dashboard runtime configuration from YAML."""

    selected_mode = DashboardRuntimeMode(mode or os.environ.get(DEFAULT_DASHBOARD_MODE_ENV, DashboardRuntimeMode.DEMO))
    raw_path = path or os.environ.get(DEFAULT_DASHBOARD_CONFIG_ENV)
    if raw_path in (None, ""):
        if selected_mode == DashboardRuntimeMode.DEMO:
            return DashboardRuntimeConfig(mode=DashboardRuntimeMode.DEMO)
        raise ValueError(
            f"{selected_mode.value} dashboard runtime requires {DEFAULT_DASHBOARD_CONFIG_ENV} "
            "or an explicit config_path"
        )
    config_path = Path(raw_path)
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise TypeError(f"Dashboard runtime config must contain a mapping: {config_path}")
    base = config_path.parent
    config_mode = DashboardRuntimeMode(str(payload.get("mode") or selected_mode))
    retailers = tuple(_runtime_retailer(row) for row in payload.get("retailers") or ())
    public_catalog_path = Path("config/public/dashboard_metric_catalog.yaml")
    if payload.get("public_metric_catalog_path"):
        configured_public_catalog_path = _config_path(payload.get("public_metric_catalog_path"), base)
        if configured_public_catalog_path is None:
            raise ValueError("public_metric_catalog_path must resolve to a path")
        public_catalog_path = configured_public_catalog_path
    return DashboardRuntimeConfig(
        mode=config_mode,
        metric_facts_path=_config_path(payload.get("metric_facts_path"), base),
        mart_builds_path=_config_path(payload.get("mart_builds_path"), base),
        source_ledger_path=_config_path(payload.get("source_ledger_path"), base),
        events_path=_config_path(payload.get("events_path"), base),
        event_rules_path=_config_path(payload.get("event_rules_path"), base),
        source_like_rows_path=_config_path(payload.get("source_like_rows_path"), base),
        product_store_facts_path=_config_path(payload.get("product_store_facts_path"), base),
        public_metric_catalog_path=public_catalog_path,
        private_metric_catalog_path=_config_path(payload.get("private_metric_catalog_path"), base),
        retailers=retailers,
    )


def build_private_dashboard_runtime(config: DashboardRuntimeConfig) -> DashboardRuntime:
    """Build a dashboard runtime from private mart/config paths."""

    if config.mode not in {DashboardRuntimeMode.PRIVATE, DashboardRuntimeMode.PRODUCTION}:
        raise ValueError(f"Private runtime builder does not accept mode: {config.mode.value}")
    required_paths = (
        config.metric_facts_path,
        config.mart_builds_path,
        config.source_ledger_path,
        config.public_metric_catalog_path,
        config.private_metric_catalog_path,
    )
    missing_paths = [str(path) for path in required_paths if path is None or not path.exists()]
    missing_paths.extend(
        str(path)
        for path in (config.events_path, config.event_rules_path, config.source_like_rows_path, config.product_store_facts_path)
        if path is not None and not path.exists()
    )
    if missing_paths:
        raise FileNotFoundError(f"Dashboard private runtime paths do not exist: {missing_paths}")
    assert config.metric_facts_path is not None
    assert config.mart_builds_path is not None
    assert config.source_ledger_path is not None
    assert config.private_metric_catalog_path is not None
    public_catalog = load_public_metric_catalog(config.public_metric_catalog_path)
    private_overrides = load_private_metric_catalog_overrides(config.private_metric_catalog_path)
    catalog = tuple(
        entry
        for retailer in config.retailers
        for entry in merge_metric_catalog(
            public_catalog,
            private_overrides,
            retailer_id=retailer.retailer_id,
            source_id=retailer.source_id,
        )
    )
    if not catalog:
        raise ValueError("Dashboard private runtime resolved an empty effective metric catalog")
    service = DashboardMartQueryService(
        config.metric_facts_path,
        catalog=catalog,
        mart_builds=_read_mart_builds(config.mart_builds_path),
        source_ledger=_read_source_ledger_entries(config.source_ledger_path),
        product_store_facts_path=config.product_store_facts_path,
    )
    return DashboardRuntime(
        query_service=service,
        catalog=catalog,
        retailers=config.retailers,
        mode=config.mode,
        events_path=config.events_path,
        event_rules_path=config.event_rules_path,
        source_like_rows_path=config.source_like_rows_path,
        product_store_facts_path=config.product_store_facts_path,
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
                display_label="Сеть A",
                source_id="source_a",
                source_label="Источник A",
                default_mart_build_id=build.mart_build_id,
            ),
        ),
        mode=DashboardRuntimeMode.DEMO,
    )


def _runtime_retailer(row: dict[str, Any]) -> DashboardRuntimeRetailer:
    return DashboardRuntimeRetailer(
        retailer_id=str(row["retailer_id"]),
        display_label=str(row.get("display_label") or row["retailer_id"]),
        source_id=str(row["source_id"]),
        source_label=str(row.get("source_label") or row["source_id"]),
        private_label_display_name=str(row.get("private_label_display_name") or "выбранный ассортимент"),
        default_mart_build_id=_optional_str(row.get("default_mart_build_id")),
    )


def _config_path(value: object, base: Path) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value))
    return path if path.is_absolute() else (base / path)


def _read_mart_builds(path: Path) -> tuple[MartBuildMetadata, ...]:
    if path.is_file():
        return read_mart_build_metadata(path)
    return tuple(
        build
        for parquet_path in sorted(path.rglob("*.parquet"))
        for build in read_mart_build_metadata(parquet_path)
    )


def _read_source_ledger_entries(path: Path) -> tuple[SourceLedgerEntry, ...]:
    if path.is_file():
        return read_source_ledger(path)
    return tuple(
        entry
        for parquet_path in sorted(path.rglob("*.parquet"))
        for entry in read_source_ledger(parquet_path)
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _period_options(
    metric_facts_path: Path,
    retailer_id: str,
    source_id: str,
    scope: PrivateLabelScope,
) -> list[dict[str, str]]:
    clauses = ["retailer_id = ?", "source_id = ?"]
    params: list[Any] = [retailer_id, source_id]
    if _facts_have_column(metric_facts_path, "private_label_scope"):
        clauses.append("private_label_scope = ?")
        params.append(scope.value)
    rows = duckdb.sql(
        f"""
            SELECT DISTINCT period_start, business_period_id
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
            ORDER BY period_start
        """,
        params=[_duckdb_path(metric_facts_path), *params],
    ).fetchall()
    return [
        {
            "value": row[0].isoformat(),
            "label": str(row[1]),
        }
        for row in rows
    ]


def _entity_options(
    metric_facts_path: Path,
    retailer_id: str,
    source_id: str,
    scope: PrivateLabelScope,
    *,
    date_from: date | None,
    date_to: date | None,
    parent_filters: dict[str, tuple[str, ...]],
    source_like_rows_path: Path | None = None,
    source_revision_ids: tuple[str, ...] = (),
) -> dict[str, list[dict[str, Any]]]:
    if source_like_rows_path is not None and source_like_rows_path.exists():
        source_like_entities = _source_like_entity_options(
            source_like_rows_path,
            retailer_id,
            source_id,
            scope,
            date_from=date_from,
            date_to=date_to,
            parent_filters=parent_filters,
            source_revision_ids=source_revision_ids,
        )
        if any(source_like_entities.values()):
            source_like_entities["network"] = _metric_fact_entity_options_for_grain(
                metric_facts_path,
                retailer_id,
                source_id,
                scope,
                "network",
                date_from=date_from,
                date_to=date_to,
            )
            return source_like_entities
    entities: dict[str, list[dict[str, Any]]] = {grain: [] for grain in SUPPORTED_GRAINS}
    for grain in SUPPORTED_GRAINS:
        clauses = ["retailer_id = ?", "source_id = ?", "grain_id = ?"]
        params: list[Any] = [retailer_id, source_id, grain]
        if _facts_have_column(metric_facts_path, "private_label_scope"):
            clauses.append("private_label_scope = ?")
            params.append(scope.value)
        if date_from is not None:
            clauses.append("period_start >= CAST(? AS DATE)")
            params.append(date_from.isoformat())
        if date_to is not None:
            clauses.append("period_start <= CAST(? AS DATE)")
            params.append(date_to.isoformat())
        for parent_key in ENTITY_PARENT_FILTERS[grain]:
            parent_values = tuple(value for value in parent_filters.get(parent_key, ()) if value)
            if parent_values:
                placeholders = ", ".join("?" for _ in parent_values)
                clauses.append(f"json_extract_string(parent_entity_ids, '$.{parent_key}') IN ({placeholders})")
                params.extend(parent_values)
        rows = duckdb.sql(
            f"""
                SELECT entity_id, COUNT(DISTINCT business_period_id) AS period_count
                FROM read_parquet(?)
                WHERE {" AND ".join(clauses)}
                GROUP BY entity_id
                ORDER BY entity_id
            """,
            params=[_duckdb_path(metric_facts_path), *params],
        ).fetchall()
        entities[grain] = [
            {
                "value": str(entity_id),
                "label": str(entity_id),
                "period_count": int(period_count),
            }
            for entity_id, period_count in rows
        ]
    return entities


def _metric_fact_entity_options_for_grain(
    metric_facts_path: Path,
    retailer_id: str,
    source_id: str,
    scope: PrivateLabelScope,
    grain: str,
    *,
    date_from: date | None,
    date_to: date | None,
) -> list[dict[str, Any]]:
    clauses = ["retailer_id = ?", "source_id = ?", "grain_id = ?"]
    params: list[Any] = [retailer_id, source_id, grain]
    if _facts_have_column(metric_facts_path, "private_label_scope"):
        clauses.append("private_label_scope = ?")
        params.append(scope.value)
    if date_from is not None:
        clauses.append("period_start >= CAST(? AS DATE)")
        params.append(date_from.isoformat())
    if date_to is not None:
        clauses.append("period_start <= CAST(? AS DATE)")
        params.append(date_to.isoformat())
    rows = duckdb.sql(
        f"""
            SELECT entity_id, COUNT(DISTINCT business_period_id) AS period_count
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
            GROUP BY entity_id
            ORDER BY entity_id
        """,
        params=[_duckdb_path(metric_facts_path), *params],
    ).fetchall()
    return [
        {
            "value": str(entity_id),
            "label": str(entity_id),
            "period_count": int(period_count),
        }
        for entity_id, period_count in rows
    ]


def _source_like_entity_options(
    source_like_rows_path: Path,
    retailer_id: str,
    source_id: str,
    scope: PrivateLabelScope,
    *,
    date_from: date | None,
    date_to: date | None,
    parent_filters: dict[str, tuple[str, ...]],
    source_revision_ids: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    entities: dict[str, list[dict[str, Any]]] = {grain: [] for grain in SUPPORTED_GRAINS}
    available_columns = _source_columns(source_like_rows_path)
    for grain, entity_column in SOURCE_LIKE_ENTITY_COLUMNS.items():
        if entity_column not in available_columns:
            continue
        label_column = _source_like_label_column(grain, entity_column, available_columns)
        clauses = ["retailer_id = ?", "source_id = ?", f"{entity_column} IS NOT NULL", f"{entity_column} <> ''"]
        params: list[Any] = [retailer_id, source_id]
        if "source_revision_id" in available_columns and source_revision_ids:
            placeholders = ", ".join("?" for _ in source_revision_ids)
            clauses.append(f"source_revision_id IN ({placeholders})")
            params.extend(source_revision_ids)
        if "private_label_flag" in available_columns and scope != PrivateLabelScope.INCLUDE:
            clauses.append("private_label_flag = ?")
            params.append(scope == PrivateLabelScope.ONLY)
        if date_from is not None and "period" in available_columns:
            clauses.append("period >= CAST(? AS DATE)")
            params.append(date_from.isoformat())
        if date_to is not None and "period" in available_columns:
            clauses.append("period <= CAST(? AS DATE)")
            params.append(date_to.isoformat())
        for parent_key in ENTITY_PARENT_FILTERS[grain]:
            parent_column = SOURCE_LIKE_ENTITY_COLUMNS.get(parent_key)
            parent_values = tuple(value for value in parent_filters.get(parent_key, ()) if value)
            if parent_column and parent_column in available_columns and parent_values:
                placeholders = ", ".join("?" for _ in parent_values)
                clauses.append(f"{parent_column} IN ({placeholders})")
                params.extend(parent_values)
        rows = duckdb.sql(
            f"""
                SELECT {entity_column}, MIN({label_column}) AS display_label, COUNT(DISTINCT period) AS period_count
                FROM read_parquet(?)
                WHERE {" AND ".join(clauses)}
                GROUP BY {entity_column}
                ORDER BY display_label
            """,
            params=[_duckdb_path(source_like_rows_path), *params],
        ).fetchall()
        entities[grain] = [
            {
                "value": str(entity_id),
                "label": str(display_label or entity_id),
                "period_count": int(period_count),
            }
            for entity_id, display_label, period_count in rows
        ]
    return entities


def _source_like_label_column(grain: str, entity_column: str, available_columns: set[str]) -> str:
    for candidate in SOURCE_LIKE_LABEL_COLUMNS.get(grain, (entity_column,)):
        if candidate in available_columns:
            return candidate
    return entity_column


def _product_filters_need_sku_resolution(product_filters: dict[str, tuple[str, ...]]) -> bool:
    selected = set(product_filters)
    if not selected:
        return False
    effective = max(selected, key=PRODUCT_FILTERS.index)
    supported = MART_PARENT_FILTER_SUPPORT.get(effective, frozenset())
    return not selected.issubset(supported)


def _source_like_resolution_start(
    metric_facts_path: Path,
    *,
    retailer_id: str,
    source_id: str,
    private_label_scope: str | PrivateLabelScope,
    date_from: date | None,
    comparison_mode: str,
) -> date | None:
    if date_from is None or comparison_mode == "NONE":
        return date_from
    periods = [
        row[0]
        for row in duckdb.sql(
            """
                SELECT DISTINCT period_start
                FROM read_parquet(?)
                WHERE retailer_id = ?
                  AND source_id = ?
                  AND private_label_scope = ?
                  AND period_start <= CAST(? AS DATE)
                ORDER BY period_start
            """,
            params=[
                _duckdb_path(metric_facts_path),
                retailer_id,
                source_id,
                PrivateLabelScope(private_label_scope).value,
                date_from.isoformat(),
            ],
        ).fetchall()
    ]
    if comparison_mode == "YOY":
        candidate = date(date_from.year - 1, date_from.month, date_from.day)
        return candidate if candidate in periods else date_from
    if comparison_mode == "MOM":
        previous_month = date_from.replace(year=date_from.year - 1, month=12) if date_from.month == 1 else date(
            date_from.year,
            date_from.month - 1,
            date_from.day,
        )
        return previous_month if previous_month in periods else date_from
    earlier = [period for period in periods if period < date_from]
    return earlier[-1] if earlier else date_from


def _source_revision_ids_for_options(
    mart_builds: tuple[MartBuildMetadata, ...],
    retailer_id: str,
    source_id: str,
    default_mart_build_id: str | None,
) -> tuple[str, ...]:
    matching = tuple(
        build
        for build in mart_builds
        if build.retailer_id == retailer_id and source_id in build.source_ids and build.status == MartBuildStatus.APPROVED
    )
    if default_mart_build_id:
        for build in matching:
            if build.mart_build_id == default_mart_build_id:
                return tuple(sorted(build.source_revision_ids))
        raise ValueError(
            "Default mart build is not available for dashboard filter options: "
            f"{retailer_id}/{source_id}/{default_mart_build_id}"
        )
    if len(matching) > 1:
        raise ValueError(
            "Dashboard filter options require an explicit default mart build when multiple approved builds exist: "
            f"{retailer_id}/{source_id}"
        )
    if not matching:
        return ()
    return tuple(sorted(matching[0].source_revision_ids))


def _runtime_retailer_for_scope(
    retailers: tuple[DashboardRuntimeRetailer, ...],
    retailer_id: str,
    source_id: str,
) -> DashboardRuntimeRetailer | None:
    for item in retailers:
        if item.retailer_id == retailer_id and item.source_id == source_id:
            return item
    return None


def _source_columns(source_like_rows_path: Path) -> set[str]:
    return {
        str(row[0])
        for row in duckdb.sql(
            "DESCRIBE SELECT * FROM read_parquet(?) LIMIT 0",
            params=[_duckdb_path(source_like_rows_path)],
        ).fetchall()
    }


def _facts_have_column(metric_facts_path: Path, column: str) -> bool:
    return column in {
        str(row[0])
        for row in duckdb.sql(
            "DESCRIBE SELECT * FROM read_parquet(?) LIMIT 0",
            params=[_duckdb_path(metric_facts_path)],
        ).fetchall()
    }


def _duckdb_path(path: Path) -> str:
    raw = path.as_posix()
    if path.is_dir():
        raw = f"{raw}/**/*.parquet"
    return raw


def serialize_catalog(entries: tuple[EffectiveMetricCatalogEntry, ...]) -> list[dict[str, Any]]:
    """Serialize effective metric catalog entries for the browser."""

    return [
        {
            "metric_concept": entry.metric_concept,
            "display_label": entry.display_label,
            "display_alias": entry.display_alias,
            "description": entry.description,
            "business_meaning": entry.business_meaning,
            "formula_summary": entry.formula_summary,
            "unit_label": entry.unit_label,
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
            "business_question": entry.business_question,
            "decision_use": entry.decision_use,
            "delta_semantics": entry.delta_semantics,
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
        "parent_entity_ids": _parent_entity_ids(grain, entity_id),
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


def _parent_entity_ids(grain: str, entity_id: str) -> str:
    hierarchy = ("category", "manufacturer", "brand", "sku", "store")
    values = {
        "category": "CATEGORY_STANDARD",
        "manufacturer": "MANUFACTURER_A",
        "brand": "BRAND_A",
        "sku": "SKU_A_001",
        "store": "STORE_A_001",
    }
    if grain not in hierarchy:
        return "{}"
    values[grain] = entity_id
    parents = {key: values[key] for key in hierarchy[: hierarchy.index(grain) + 1]}
    return json.dumps(parents, sort_keys=True)


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
