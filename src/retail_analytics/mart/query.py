"""Dashboard mart query contracts over Parquet metric facts."""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from retail_analytics.history import SourceLedgerEntry, active_revisions
from retail_analytics.mart.builds import MartBuildMetadata, MartBuildStatus
from retail_analytics.mart.metric_catalog import (
    EffectiveMetricCatalogEntry,
    MetricAvailabilityStatus,
    catalog_entry_for_fact,
)
from retail_analytics.mart.metric_facts import MART_METRIC_FACT_SCHEMA, RangeAggregationStrategy
from retail_analytics.mart.product_store_facts import PRODUCT_STORE_SUPPORTED_CONCEPTS
from retail_analytics.mart.scopes import PrivateLabelScope, scope_identity_hash
from retail_analytics.mart.store_universe import MONTHLY_STORE_FORMAT_UNIVERSE

FILTER_GRAIN_ORDER = ("category", "manufacturer", "brand", "sku", "store")
SOURCE_LIKE_APPROVED_KPI_FILTER_PRECEDENCE = ("sku", "brand", "category")
STORE_FORMAT_DISTRIBUTION_CONCEPT = "numeric_distribution_store_format"
STORE_FORMAT_DISTRIBUTION_RULE_ID = "BR-009B"
STORE_FORMAT_DISTRIBUTION_SUPPORTED_GRAINS = frozenset({"category", "manufacturer", "brand", "sku"})
SOURCE_LIKE_APPROVED_KPI_CONCEPTS = frozenset(
    {"velocity", "distribution", "weighted_distribution", "average_price_per_liter"}
)
SOURCE_LIKE_APPROVED_KPI_SUPPORT = {
    "velocity": frozenset({"category", "brand", "sku"}),
    "distribution": frozenset({"category", "brand", "sku"}),
    "weighted_distribution": frozenset({"brand", "sku"}),
    "average_price_per_liter": frozenset({"network", "category", "brand", "sku"}),
}
SOURCE_LIKE_ENTITY_COLUMNS = {
    "network": None,
    "category": "category",
    "manufacturer": "manufacturer",
    "brand": "brand",
    "sku": "canonical_product_id",
    "store": "canonical_store_id",
}
SOURCE_LIKE_REQUIRED_COLUMNS = frozenset(
    {
        "retailer_id",
        "source_id",
        "analysis_run_id",
        "period",
        "canonical_store_id",
        "canonical_product_id",
        "category",
        "manufacturer",
        "brand",
        "units",
        "revenue_vat",
        "volume_l",
    }
)
SCOPED_ROLLUP_SAFE_CONCEPTS = {
    "revenue_vat",
    "revenue",
    "units",
    "retailer_margin_abs",
    "retailer_margin_pct",
    "weighted_shelf_price_vat",
    "weighted_input_price_vat",
}
PARENT_ENTITY_JSON_KEYS = {
    "category": "category",
    "manufacturer": "manufacturer",
    "brand": "brand",
    "sku": "canonical_product_id",
    "store": "canonical_store_id",
}


class PeriodMode(StrEnum):
    """Logical period request modes."""

    SINGLE_PERIOD = "SINGLE_PERIOD"
    DATE_RANGE = "DATE_RANGE"
    AVAILABLE_MONTH_SET = "AVAILABLE_MONTH_SET"
    FULL_AVAILABLE_HISTORY = "FULL_AVAILABLE_HISTORY"


class ComparisonMode(StrEnum):
    """Supported period comparison modes."""

    NONE = "NONE"
    YOY = "YOY"
    MOM = "MOM"
    PREVIOUS_AVAILABLE = "PREVIOUS_AVAILABLE"


class CoverageStatus(StrEnum):
    """Coverage of requested expected periods by available mart facts."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    UNSUPPORTED = "UNSUPPORTED"


class QualityPolicy(StrEnum):
    """Minimal query-time quality policy."""

    INCLUDE_ALL = "INCLUDE_ALL"
    VALID_ONLY = "VALID_ONLY"


@dataclass(frozen=True)
class DashboardMetricQueryRequest:
    """Dashboard-ready query request over metric facts."""

    retailer_id: str
    source_id: str
    date_from: date | None
    date_to: date | None
    period_mode: PeriodMode
    period_grain: str
    grain_id: str
    entity_ids: tuple[str, ...] = ()
    entity_filters: dict[str, tuple[str, ...]] | None = None
    user_entity_filters: dict[str, tuple[str, ...]] | None = None
    metric_concepts: tuple[str, ...] = ()
    metric_definition_ids: tuple[str, ...] = ()
    comparison_mode: ComparisonMode = ComparisonMode.NONE
    ownership_scope: str | None = None
    quality_policy: QualityPolicy = QualityPolicy.INCLUDE_ALL
    include_lineage: bool = True
    mart_build_id: str | None = None
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE

    def __post_init__(self) -> None:
        object.__setattr__(self, "period_mode", PeriodMode(self.period_mode))
        object.__setattr__(self, "comparison_mode", ComparisonMode(self.comparison_mode))
        object.__setattr__(self, "quality_policy", QualityPolicy(self.quality_policy))
        object.__setattr__(self, "private_label_scope", PrivateLabelScope(self.private_label_scope))


@dataclass(frozen=True)
class PeriodValue:
    """One period-level fact value included in a query result."""

    period_start: date
    period_end: date
    business_period_id: str
    value: float | None
    numerator_value: float | None
    denominator_value: float | None
    business_rule_id: str | None
    denominator_universe_type: str | None
    store_alias_mapping_version: str | None
    numerator_metric_name: str | None
    denominator_metric_name: str | None
    source_revision_id: str
    analysis_run_id: str
    quality_status: str
    quality_flags: str | None


@dataclass(frozen=True)
class MetricDefinitionLineage:
    """Metric definition identity behind a returned value."""

    metric_definition_id: str
    metric_definition_version: str
    metric_config_hash: str
    rule_version: str
    semantic_family: str | None
    semantic_compatibility_version: str | None
    cross_retailer_comparable: bool


@dataclass(frozen=True)
class MetricProvenanceTrace:
    """Structured backend provenance for a dashboard-visible value."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class MetricQueryResult:
    """Aggregated or period-only metric result."""

    metric_concept: str
    metric_name: str
    grain_id: str
    entity_id: str
    value: float | None
    numerator_value: float | None
    denominator_value: float | None
    range_aggregation_strategy: RangeAggregationStrategy
    share_scope: str | None
    period_values: tuple[PeriodValue, ...]
    lineage: MetricDefinitionLineage | None
    limitations: tuple[str, ...] = ()
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE
    provenance: MetricProvenanceTrace | None = None


@dataclass(frozen=True)
class ComparisonResult:
    """Period comparison result with explicit period and quality metadata."""

    comparison_mode: ComparisonMode
    metric_definition_id: str
    entity_id: str
    current_period_start: date
    comparison_period_start: date
    current_value: float | None
    comparison_value: float | None
    delta: float | None
    pct_delta: float | None
    quality_status: str
    gap_periods: int
    private_label_scope: PrivateLabelScope
    current_included_periods: tuple[date, ...] = ()
    comparison_included_periods: tuple[date, ...] = ()
    aggregation_method: str | None = None
    comparison_policy: str | None = None


@dataclass(frozen=True)
class QueryLimitation:
    """Structured query limitation or rejection reason."""

    issue_code: str
    message: str
    metric_definition_id: str | None = None
    metric_concept: str | None = None


@dataclass(frozen=True)
class DashboardMetricQueryResponse:
    """Structured dashboard mart query response."""

    request_scope: dict[str, Any]
    requested_period_start: date | None
    requested_period_end: date | None
    available_periods: tuple[date, ...]
    missing_periods: tuple[date, ...]
    coverage_ratio: float | None
    coverage_status: CoverageStatus
    metric_results: tuple[MetricQueryResult, ...]
    comparisons: tuple[ComparisonResult, ...]
    quality_flags: tuple[str, ...]
    limitations: tuple[QueryLimitation, ...]
    mart_build_id: str
    analysis_run_ids: tuple[str, ...]
    metric_definition_lineage: tuple[MetricDefinitionLineage, ...]
    private_label_scope: PrivateLabelScope
    scope_identity_hash: str


class DashboardMartQueryService:
    """Query mart metric facts through DuckDB and apply catalog-safe semantics."""

    def __init__(
        self,
        metric_facts_path: str | Path,
        *,
        catalog: tuple[EffectiveMetricCatalogEntry, ...] = (),
        mart_builds: tuple[MartBuildMetadata, ...] = (),
        source_ledger: tuple[SourceLedgerEntry, ...] = (),
        product_store_facts_path: str | Path | None = None,
        store_universe_path: str | Path | None = None,
        source_like_rows_path: str | Path | None = None,
    ) -> None:
        self.metric_facts_path = Path(metric_facts_path)
        self.product_store_facts_path = Path(product_store_facts_path) if product_store_facts_path is not None else None
        self.store_universe_path = Path(store_universe_path) if store_universe_path is not None else None
        self.source_like_rows_path = Path(source_like_rows_path) if source_like_rows_path is not None else None
        self.catalog = catalog
        self.mart_builds = mart_builds
        self.source_ledger = source_ledger
        self._fact_columns: set[str] | None = None

    def query(self, request: DashboardMetricQueryRequest) -> DashboardMetricQueryResponse:
        """Return dashboard-ready metric results without redefining metric formulas."""

        mart_build_id = self._resolve_build_id(request)
        self._validate_active_revision_scope(request, mart_build_id)
        fetch_start = _comparison_fetch_start(request)
        limitations = list(self._private_label_scope_materialization_limitations(request))
        scoped_rollup_grain: str | None = None
        serving_fact_grain: str | None = None
        unsupported_distribution_scope = _unsupported_distribution_scope_limitations(request)
        source_like_concepts = (
            _source_like_approved_kpi_concepts(request)
            if self.source_like_rows_path is not None and self.source_like_rows_path.exists()
            else ()
        )
        fact_request = _request_without_source_like_approved_kpis(request) if source_like_concepts else request
        if unsupported_distribution_scope:
            raw = pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA)
            limitations.extend(unsupported_distribution_scope)
        elif _requests_store_format_distribution(request):
            raw, serving_fact_grain, product_store_limitations = self._read_store_format_distribution_facts(
                request,
                mart_build_id=mart_build_id,
                period_start=fetch_start,
            )
            limitations.extend(product_store_limitations)
        elif _has_product_store_intersection(request):
            raw, serving_fact_grain, product_store_limitations = self._read_product_store_rollup_facts(
                fact_request,
                mart_build_id=mart_build_id,
                period_start=fetch_start,
            )
            limitations.extend(product_store_limitations)
        elif _source_like_only_request(request, fact_request):
            raw = pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA)
        else:
            raw = self._read_facts(fact_request, mart_build_id=mart_build_id, period_start=fetch_start)
        if (
            raw.is_empty()
            and fact_request.entity_filters
            and not _has_product_store_intersection(fact_request)
            and not _source_like_only_request(request, fact_request)
        ):
            raw, scoped_rollup_grain, rollup_limitations = self._read_scoped_rollup_facts(
                fact_request,
                mart_build_id=mart_build_id,
                period_start=fetch_start,
            )
            limitations.extend(rollup_limitations)
        if source_like_concepts and not unsupported_distribution_scope:
            source_like_request = _source_like_effective_scope_request(request)
            source_like_raw, source_like_limitations = self._read_source_like_approved_kpi_facts(
                source_like_request,
                mart_build_id=mart_build_id,
                period_start=fetch_start,
                metric_concepts=source_like_concepts,
            )
            limitations.extend(source_like_limitations)
            raw = _concat_fact_frames(raw, source_like_raw)
        requested = _filter_requested_periods(raw, request)
        self._validate_fact_active_revisions(requested, request)
        _reject_source_revision_ambiguity(requested)
        _reject_duplicate_fact_contributors(requested)
        limitations.extend(self._period_grain_limitations(request))
        limitations.extend(self._catalog_limitations(requested, request, scoped_rollup_grain=scoped_rollup_grain))
        requested_periods = _expected_periods(request, requested)
        available_periods = tuple(
            sorted(set(requested.get_column("period_start").to_list())) if not requested.is_empty() else ()
        )
        missing_periods = tuple(period for period in requested_periods if period not in available_periods)
        coverage_ratio, coverage_status = _coverage(requested_periods, available_periods)

        metric_results, result_limitations = _metric_results(
            requested,
            request,
            self.catalog,
            requested_periods,
        )
        limitations.extend(result_limitations)
        if source_like_concepts and request.period_mode != PeriodMode.SINGLE_PERIOD:
            metric_results = self._apply_source_like_approved_kpi_range_values(
                metric_results,
                request,
                metric_concepts=source_like_concepts,
            )
        self._validate_comparison_fact_scope(raw, request)
        comparisons, comparison_limitations = _comparisons(raw, metric_results, request)
        limitations.extend(comparison_limitations)
        analysis_run_ids = tuple(sorted(set(requested.get_column("analysis_run_id").to_list()))) if not requested.is_empty() else ()
        quality_flags = _quality_flags(requested)
        metric_results = _attach_provenance(
            metric_results,
            request=request,
            mart_build_id=mart_build_id,
            analysis_run_ids=analysis_run_ids,
            requested_periods=requested_periods,
            available_periods=available_periods,
            missing_periods=missing_periods,
            comparisons=comparisons,
            response_quality_flags=quality_flags,
            scoped_rollup_grain=scoped_rollup_grain,
            serving_fact_grain=serving_fact_grain,
        )
        lineage = tuple(result.lineage for result in metric_results if request.include_lineage and result.lineage is not None)

        return DashboardMetricQueryResponse(
            request_scope={
                "retailer_id": request.retailer_id,
                "source_id": request.source_id,
                "period_grain": request.period_grain,
                "grain_id": request.grain_id,
                "entity_ids": request.entity_ids,
                "metric_concepts": request.metric_concepts,
                "metric_definition_ids": request.metric_definition_ids,
                "period_mode": request.period_mode.value,
                "comparison_mode": request.comparison_mode.value,
                "entity_filters": request.entity_filters or {},
                "private_label_scope": request.private_label_scope.value,
            },
            requested_period_start=min(requested_periods) if requested_periods else request.date_from,
            requested_period_end=max(requested_periods) if requested_periods else request.date_to,
            available_periods=available_periods,
            missing_periods=missing_periods,
            coverage_ratio=coverage_ratio,
            coverage_status=coverage_status,
            metric_results=metric_results,
            comparisons=comparisons,
            quality_flags=quality_flags,
            limitations=tuple(limitations),
            mart_build_id=mart_build_id,
            analysis_run_ids=analysis_run_ids,
            metric_definition_lineage=lineage,
            private_label_scope=request.private_label_scope,
            scope_identity_hash=scope_identity_hash(
                private_label_scope=request.private_label_scope,
                entity_filters=request.entity_filters,
            ),
        )

    def _resolve_build_id(self, request: DashboardMetricQueryRequest) -> str:
        if request.mart_build_id:
            if self.mart_builds:
                matches = [build for build in self.mart_builds if build.mart_build_id == request.mart_build_id]
                if not matches:
                    raise ValueError(f"Unknown mart_build_id: {request.mart_build_id}")
            return request.mart_build_id

        approved = [
            build
            for build in self.mart_builds
            if build.retailer_id == request.retailer_id
            and request.source_id in build.source_ids
            and build.period_grain == request.period_grain
            and build.status == MartBuildStatus.APPROVED
        ]
        if len(approved) == 1:
            return approved[0].mart_build_id
        if len(approved) > 1:
            raise ValueError("Multiple approved mart builds match request; mart_build_id is required")
        distinct = self._distinct_builds(request)
        if len(distinct) == 1:
            return distinct[0]
        if not distinct:
            raise ValueError("No mart build matches request")
        raise ValueError("Multiple mart builds match request; mart_build_id is required")

    def _validate_active_revision_scope(self, request: DashboardMetricQueryRequest, mart_build_id: str) -> None:
        if not self.source_ledger:
            return
        build = next((item for item in self.mart_builds if item.mart_build_id == mart_build_id), None)
        if build is None:
            return
        active_ids = {entry.source_revision_id for entry in active_revisions(self.source_ledger)}
        unexpected = sorted(set(build.source_revision_ids) - active_ids)
        if unexpected:
            raise ValueError(f"Mart build references inactive source revisions: {unexpected}")
        active_periods: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for entry in active_revisions(self.source_ledger):
            if entry.retailer_id != request.retailer_id or entry.source_id != request.source_id:
                continue
            for period in entry.active_business_period_ids or entry.business_period_ids:
                active_periods[(entry.retailer_id, entry.source_id, period)].add(entry.source_revision_id)
        ambiguous = {key: values for key, values in active_periods.items() if len(values) > 1}
        if ambiguous:
            raise ValueError(f"Ambiguous active source revisions for periods: {sorted(ambiguous)}")

    def _validate_fact_active_revisions(self, frame: pl.DataFrame, request: DashboardMetricQueryRequest) -> None:
        if not self.source_ledger or frame.is_empty():
            return
        active_period_map: dict[tuple[str, str, str], str] = {}
        for entry in active_revisions(self.source_ledger):
            if entry.retailer_id != request.retailer_id or entry.source_id != request.source_id:
                continue
            for period in entry.active_business_period_ids or entry.business_period_ids:
                active_period_map[(entry.retailer_id, entry.source_id, period)] = entry.source_revision_id
        mismatches: list[tuple[str, str, str, str, str | None]] = []
        for row in frame.select(
            ["retailer_id", "source_id", "business_period_id", "source_revision_id"]
        ).unique().to_dicts():
            key = (str(row["retailer_id"]), str(row["source_id"]), str(row["business_period_id"]))
            expected_revision = active_period_map.get(key)
            actual_revision = str(row["source_revision_id"])
            if expected_revision != actual_revision:
                mismatches.append((*key, actual_revision, expected_revision))
        if mismatches:
            raise ValueError(f"Facts contain inactive source revisions for active periods: {mismatches}")

    def _validate_comparison_fact_scope(self, frame: pl.DataFrame, request: DashboardMetricQueryRequest) -> None:
        if request.comparison_mode == ComparisonMode.NONE or request.period_mode != PeriodMode.SINGLE_PERIOD:
            return
        target = _comparison_target(frame, request)
        if target is None or request.date_from is None:
            return
        scoped = frame.filter(pl.col("period_start").is_in([request.date_from, target]))
        self._validate_fact_active_revisions(scoped, request)
        _reject_source_revision_ambiguity(scoped)
        _reject_duplicate_fact_contributors(scoped)

    def _distinct_builds(self, request: DashboardMetricQueryRequest) -> tuple[str, ...]:
        sql = """
            SELECT DISTINCT mart_build_id
            FROM read_parquet(?)
            WHERE retailer_id = ?
              AND source_id = ?
              AND period_grain = ?
        """
        rows = duckdb.sql(
            sql,
            params=[_duckdb_path(self.metric_facts_path), request.retailer_id, request.source_id, request.period_grain],
        ).fetchall()
        return tuple(sorted(str(row[0]) for row in rows))

    def _read_facts(
        self,
        request: DashboardMetricQueryRequest,
        *,
        mart_build_id: str,
        period_start: date | None,
    ) -> pl.DataFrame:
        if (
            request.private_label_scope != PrivateLabelScope.INCLUDE
            and not self._facts_have_private_label_scope()
        ):
            return pl.DataFrame()
        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "period_grain = ?",
            "grain_id = ?",
            "mart_build_id = ?",
        ]
        params: list[Any] = [
            request.retailer_id,
            request.source_id,
            request.period_grain,
            request.grain_id,
            mart_build_id,
        ]
        if period_start is not None:
            clauses.append("period_start >= CAST(? AS DATE)")
            params.append(period_start.isoformat())
        if request.date_to is not None:
            clauses.append("period_start <= CAST(? AS DATE)")
            params.append(request.date_to.isoformat())
        if self._facts_have_private_label_scope():
            clauses.append("private_label_scope = ?")
            params.append(request.private_label_scope.value)
        _add_in_filter(clauses, params, "entity_id", request.entity_ids)
        _add_in_filter(clauses, params, "metric_concept", request.metric_concepts)
        _add_in_filter(clauses, params, "metric_definition_id", request.metric_definition_ids)
        for column, values in (request.entity_filters or {}).items():
            if column in {"category", "manufacturer", "brand", "sku", "store"}:
                _add_json_parent_filter(clauses, params, column, values)
                continue
            if column not in {"entity_id", "metric_concept", "metric_definition_id", "quality_status"}:
                raise ValueError(f"Unsupported query filter column: {column}")
            _add_in_filter(clauses, params, column, values)
        if request.quality_policy == QualityPolicy.VALID_ONLY:
            clauses.append("quality_status = ?")
            params.append("valid")
        sql = f"""
            SELECT *
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
            ORDER BY period_start, grain_id, entity_id, metric_definition_id
        """
        return duckdb.sql(sql, params=[_duckdb_path(self.metric_facts_path), *params]).pl()

    def _read_source_like_approved_kpi_facts(
        self,
        request: DashboardMetricQueryRequest,
        *,
        mart_build_id: str,
        period_start: date | None,
        metric_concepts: tuple[str, ...],
    ) -> tuple[pl.DataFrame, tuple[QueryLimitation, ...]]:
        if not metric_concepts:
            return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA), ()
        limitations = list(_source_like_approved_kpi_limitations(request, metric_concepts))
        supported = tuple(
            concept
            for concept in metric_concepts
            if request.grain_id in SOURCE_LIKE_APPROVED_KPI_SUPPORT.get(concept, frozenset())
        )
        if not supported:
            return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA), tuple(limitations)
        if self.source_like_rows_path is None or not self.source_like_rows_path.exists():
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                (
                    *limitations,
                    QueryLimitation(
                        "source_like_rows_missing",
                        "Approved KPI recomposition requires configured canonical source-like rows.",
                    ),
                ),
            )
        columns = _duckdb_columns(self.source_like_rows_path)
        missing = sorted(SOURCE_LIKE_REQUIRED_COLUMNS - columns)
        if missing:
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                (
                    *limitations,
                    QueryLimitation(
                        "source_like_rows_missing_required_columns",
                        f"Approved KPI recomposition requires source columns: {', '.join(missing)}.",
                    ),
                ),
            )
        source = self._source_like_approved_kpi_source_rows(request, period_start=period_start)
        if source.is_empty():
            return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA), tuple(limitations)
        build = next((item for item in self.mart_builds if item.mart_build_id == mart_build_id), None)
        if build is None:
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                (
                    *limitations,
                    QueryLimitation(
                        "source_like_kpi_build_metadata_missing",
                        "Approved KPI recomposition requires mart build metadata for lineage.",
                    ),
                ),
            )
        rows: list[dict[str, Any]] = []
        for concept in supported:
            rows.extend(_source_like_approved_kpi_rows(source, request, build, concept))
        if not rows:
            return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA), tuple(limitations)
        return pl.DataFrame(rows, schema=MART_METRIC_FACT_SCHEMA), tuple(limitations)

    def _source_like_approved_kpi_source_rows(
        self,
        request: DashboardMetricQueryRequest,
        *,
        period_start: date | None,
    ) -> pl.DataFrame:
        if self.source_like_rows_path is None:
            raise ValueError("source-like rows path is not configured")
        clauses = ["retailer_id = ?", "source_id = ?"]
        params: list[Any] = [request.retailer_id, request.source_id]
        if period_start is not None:
            clauses.append("CAST(period AS DATE) >= CAST(? AS DATE)")
            params.append(period_start.isoformat())
        if request.date_to is not None:
            clauses.append("CAST(period AS DATE) <= CAST(? AS DATE)")
            params.append(request.date_to.isoformat())
        if request.private_label_scope == PrivateLabelScope.ONLY:
            clauses.append("private_label_flag = true")
        elif request.private_label_scope == PrivateLabelScope.EXCLUDE:
            clauses.append("(private_label_flag = false OR private_label_flag IS NULL)")
        for key, values in (request.entity_filters or {}).items():
            column = SOURCE_LIKE_ENTITY_COLUMNS.get(key)
            if column is not None:
                continue
            if key in {"store_format", "territory", "fo", "fo2", "region"}:
                _add_source_like_filter(clauses, params, key, values)
                continue
            raise ValueError(f"Unsupported query filter column for approved KPI recomposition: {key}")
        sql = f"""
            SELECT
                retailer_id,
                source_id,
                analysis_run_id,
                CAST(period AS DATE) AS period,
                canonical_store_id,
                canonical_product_id,
                category,
                manufacturer,
                brand,
                CAST(units AS DOUBLE) AS units,
                CAST(revenue_vat AS DOUBLE) AS revenue_vat,
                CAST(volume_l AS DOUBLE) AS volume_l
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
        """
        return duckdb.sql(sql, params=[_duckdb_path(self.source_like_rows_path), *params]).pl()

    def _apply_source_like_approved_kpi_range_values(
        self,
        metric_results: tuple[MetricQueryResult, ...],
        request: DashboardMetricQueryRequest,
        *,
        metric_concepts: tuple[str, ...],
    ) -> tuple[MetricQueryResult, ...]:
        if self.source_like_rows_path is None or not self.source_like_rows_path.exists():
            return metric_results
        source = self._source_like_approved_kpi_source_rows(request, period_start=request.date_from)
        if source.is_empty():
            return metric_results
        overrides = _source_like_range_components(source, request, metric_concepts)
        adjusted: list[MetricQueryResult] = []
        for result in metric_results:
            key = (result.metric_concept, result.entity_id)
            if key not in overrides:
                adjusted.append(result)
                continue
            numerator, denominator = overrides[key]
            value = None if numerator is None or denominator in (None, 0) else numerator / denominator
            adjusted.append(replace(result, value=value, numerator_value=numerator, denominator_value=denominator))
        return tuple(adjusted)

    def _read_product_store_rollup_facts(
        self,
        request: DashboardMetricQueryRequest,
        *,
        mart_build_id: str,
        period_start: date | None,
    ) -> tuple[pl.DataFrame, str | None, tuple[QueryLimitation, ...]]:
        if self.product_store_facts_path is None or not self.product_store_facts_path.exists():
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                None,
                (
                    QueryLimitation(
                        "product_store_filter_intersection_not_materialized",
                        "Product and store filters require a materialized product-store analytical scope.",
                    ),
                ),
            )
        if request.metric_definition_ids:
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                "sku_store",
                (
                    QueryLimitation(
                        "product_store_intersection_not_supported_for_metric_definition_id",
                        "Product-store rollup does not reinterpret explicit metric definition ids.",
                    ),
                ),
            )
        requested_concepts = request.metric_concepts or tuple(PRODUCT_STORE_SUPPORTED_CONCEPTS)
        supported = tuple(concept for concept in requested_concepts if concept in PRODUCT_STORE_SUPPORTED_CONCEPTS)
        limitations = [
            QueryLimitation(
                "product_store_intersection_not_supported_for_metric",
                "Metric is not safely recomputable from product-store serving facts.",
                metric_concept=concept,
            )
            for concept in requested_concepts
            if concept not in PRODUCT_STORE_SUPPORTED_CONCEPTS
        ]
        if not supported:
            return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA), "sku_store", tuple(limitations)

        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "period_grain = ?",
            "mart_build_id = ?",
            "private_label_scope = ?",
        ]
        params: list[Any] = [
            request.retailer_id,
            request.source_id,
            request.period_grain,
            mart_build_id,
            request.private_label_scope.value,
        ]
        if period_start is not None:
            clauses.append("period_start >= CAST(? AS DATE)")
            params.append(period_start.isoformat())
        if request.date_to is not None:
            clauses.append("period_start <= CAST(? AS DATE)")
            params.append(request.date_to.isoformat())
        _add_in_filter(clauses, params, "metric_concept", supported)
        for column, values in (request.entity_filters or {}).items():
            if column not in PARENT_ENTITY_JSON_KEYS:
                raise ValueError(f"Unsupported query filter column: {column}")
            _add_in_filter(clauses, params, _product_store_filter_column(column), values)
        _add_product_store_entity_id_filter(clauses, params, request.grain_id, request.entity_ids)
        if request.quality_policy == QualityPolicy.VALID_ONLY:
            clauses.append("quality_status = ?")
            params.append("valid")
        sql = f"""
            SELECT *
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
            ORDER BY period_start, canonical_store_id, canonical_product_id, metric_concept
        """
        source = duckdb.sql(sql, params=[_duckdb_path(self.product_store_facts_path), *params]).pl()
        if source.is_empty():
            limitations.append(
                QueryLimitation(
                    "product_store_intersection_no_data",
                    "No product-store facts match the selected analytical scope.",
                )
            )
        return _roll_up_product_store_facts(source, request, self._metric_templates(request, mart_build_id)), "sku_store", tuple(limitations)

    def _read_store_format_distribution_facts(
        self,
        request: DashboardMetricQueryRequest,
        *,
        mart_build_id: str,
        period_start: date | None,
    ) -> tuple[pl.DataFrame, str | None, tuple[QueryLimitation, ...]]:
        limitations = list(_store_format_distribution_request_limitations(request))
        if limitations:
            return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA), None, tuple(limitations)
        if self.product_store_facts_path is None or not self.product_store_facts_path.exists():
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                None,
                (
                    QueryLimitation(
                        "store_format_distribution_product_store_facts_missing",
                        "Store-format distribution requires materialized SKU x store facts for numerator recomposition.",
                        metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
                    ),
                ),
            )
        if self.store_universe_path is None or not self.store_universe_path.exists():
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                None,
                (
                    QueryLimitation(
                        "store_format_distribution_universe_missing",
                        "Store-format distribution requires a materialized monthly store-universe artifact.",
                        metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
                    ),
                ),
            )

        store_format = (request.entity_filters or {})["store_format"][0]
        product_store = self._store_format_distribution_source_rows(
            request,
            mart_build_id=mart_build_id,
            period_start=period_start,
            store_format=store_format,
        )
        universe = self._store_format_universe_rows(
            request,
            mart_build_id=mart_build_id,
            period_start=period_start,
            store_format=store_format,
        )
        if product_store.is_empty():
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                "store_universe",
                (
                    QueryLimitation(
                        "store_format_distribution_entity_scope_not_observed",
                        "Selected entity scope is not present in the store-format source rows, so a zero-selling numerator cannot be proven.",
                        metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
                    ),
                ),
            )
        if universe.is_empty():
            return (
                pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA),
                "store_universe",
                (
                    QueryLimitation(
                        "store_format_distribution_universe_empty",
                        "No monthly store-format universe membership matches the selected scope.",
                        metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
                    ),
                ),
            )
        return (
            _store_format_distribution_metric_rows(product_store, universe, request, mart_build_id, store_format),
            "store_universe",
            (),
        )

    def _store_format_distribution_source_rows(
        self,
        request: DashboardMetricQueryRequest,
        *,
        mart_build_id: str,
        period_start: date | None,
        store_format: str,
    ) -> pl.DataFrame:
        product_store_facts_path = self.product_store_facts_path
        if product_store_facts_path is None:
            raise ValueError("store-format distribution product-store facts path is not configured")
        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "period_grain = ?",
            "mart_build_id = ?",
            "private_label_scope = ?",
            "metric_concept = ?",
            "store_format = ?",
        ]
        params: list[Any] = [
            request.retailer_id,
            request.source_id,
            request.period_grain,
            mart_build_id,
            request.private_label_scope.value,
            "units",
            store_format,
        ]
        if period_start is not None:
            clauses.append("period_start >= CAST(? AS DATE)")
            params.append(period_start.isoformat())
        if request.date_to is not None:
            clauses.append("period_start <= CAST(? AS DATE)")
            params.append(request.date_to.isoformat())
        for column, values in (request.entity_filters or {}).items():
            if column == "store_format":
                continue
            _add_in_filter(clauses, params, _product_store_filter_column(column), values)
        _add_product_store_entity_id_filter(clauses, params, request.grain_id, request.entity_ids)
        if request.quality_policy == QualityPolicy.VALID_ONLY:
            clauses.append("quality_status = ?")
            params.append("valid")
        sql = f"""
            SELECT *
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
            ORDER BY period_start, canonical_store_id, canonical_product_id
        """
        return duckdb.sql(sql, params=[_duckdb_path(product_store_facts_path), *params]).pl()

    def _store_format_universe_rows(
        self,
        request: DashboardMetricQueryRequest,
        *,
        mart_build_id: str,
        period_start: date | None,
        store_format: str,
    ) -> pl.DataFrame:
        store_universe_path = self.store_universe_path
        if store_universe_path is None:
            raise ValueError("store-format distribution store-universe path is not configured")
        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "period_grain = ?",
            "store_format = ?",
        ]
        del mart_build_id
        params: list[Any] = [request.retailer_id, request.source_id, request.period_grain, store_format]
        if period_start is not None:
            clauses.append("period_start >= CAST(? AS DATE)")
            params.append(period_start.isoformat())
        if request.date_to is not None:
            clauses.append("period_start <= CAST(? AS DATE)")
            params.append(request.date_to.isoformat())
        sql = f"""
            SELECT *
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
            ORDER BY period_start, canonical_store_id
        """
        return duckdb.sql(sql, params=[_duckdb_path(store_universe_path), *params]).pl()

    def _metric_templates(
        self,
        request: DashboardMetricQueryRequest,
        mart_build_id: str,
    ) -> dict[str, dict[str, Any]]:
        concepts = tuple(concept for concept in (request.metric_concepts or ()) if concept in PRODUCT_STORE_SUPPORTED_CONCEPTS)
        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "period_grain = ?",
            "grain_id = ?",
            "mart_build_id = ?",
        ]
        params: list[Any] = [request.retailer_id, request.source_id, request.period_grain, request.grain_id, mart_build_id]
        if self._facts_have_private_label_scope():
            clauses.append("private_label_scope = ?")
            params.append(request.private_label_scope.value)
        _add_in_filter(clauses, params, "metric_concept", concepts)
        rows = duckdb.sql(
            f"""
                SELECT *
                FROM read_parquet(?)
                WHERE {" AND ".join(clauses)}
                ORDER BY period_start DESC, metric_concept
            """,
            params=[_duckdb_path(self.metric_facts_path), *params],
        ).pl()
        templates: dict[str, dict[str, Any]] = {}
        for row in rows.to_dicts():
            templates.setdefault(str(row["metric_concept"]), row)
        return templates

    def _read_scoped_rollup_facts(
        self,
        request: DashboardMetricQueryRequest,
        *,
        mart_build_id: str,
        period_start: date | None,
    ) -> tuple[pl.DataFrame, str | None, tuple[QueryLimitation, ...]]:
        effective_grain = _effective_filter_grain(request)
        if effective_grain is None:
            return pl.DataFrame(), None, ()
        if _has_product_store_intersection(request):
            return (
                pl.DataFrame(),
                effective_grain,
                (
                    QueryLimitation(
                        "product_store_filter_intersection_not_materialized",
                        "Product and store filters require a materialized product-store analytical scope.",
                    ),
                ),
            )
        if request.metric_definition_ids:
            return (
                pl.DataFrame(),
                effective_grain,
                (
                    QueryLimitation(
                        "scoped_filter_rollup_not_supported_for_metric_definition_id",
                        "Filtered aggregate rollup does not reinterpret explicit metric definition ids.",
                    ),
                ),
            )
        selected = tuple((request.entity_filters or {}).get(effective_grain, ()))
        if not selected:
            return pl.DataFrame(), None, ()
        supported_metrics = tuple(
            concept for concept in request.metric_concepts if concept in SCOPED_ROLLUP_SAFE_CONCEPTS
        ) if request.metric_concepts else ()
        limitations = [
            QueryLimitation(
                "scoped_filter_rollup_not_supported_for_metric",
                "Selected filter scope cannot be safely rolled up for this metric concept.",
                metric_concept=concept,
            )
            for concept in request.metric_concepts
            if concept not in SCOPED_ROLLUP_SAFE_CONCEPTS
        ]
        if request.metric_concepts and not supported_metrics:
            return pl.DataFrame(), effective_grain, tuple(limitations)
        scoped_filters = {
            key: values
            for key, values in (request.entity_filters or {}).items()
            if key != effective_grain and values
        }
        scoped_request = replace(
            request,
            grain_id=effective_grain,
            entity_ids=selected,
            entity_filters=scoped_filters,
            metric_concepts=supported_metrics,
            metric_definition_ids=(),
        )
        scoped = self._read_facts(scoped_request, mart_build_id=mart_build_id, period_start=period_start)
        scoped_limitations = _scoped_rollup_limitations(scoped)
        return _roll_up_scoped_facts(scoped, request), effective_grain, (*limitations, *scoped_limitations)

    def _catalog_limitations(
        self,
        frame: pl.DataFrame,
        request: DashboardMetricQueryRequest,
        *,
        scoped_rollup_grain: str | None = None,
    ) -> tuple[QueryLimitation, ...]:
        if not self.catalog:
            return ()
        limitations: list[QueryLimitation] = []
        scoped_catalog = tuple(
            entry
            for entry in self.catalog
            if entry.retailer_id == request.retailer_id
            and entry.source_id in (None, request.source_id)
        )
        available_concepts = {entry.metric_concept for entry in scoped_catalog}
        for concept in request.metric_concepts:
            if concept not in available_concepts:
                limitations.append(
                    QueryLimitation(
                        "metric_not_in_catalog",
                        f"Metric concept is not available in effective catalog: {concept}",
                        metric_concept=concept,
                    )
                )
        for row in frame.to_dicts():
            entry = catalog_entry_for_fact(
                scoped_catalog,
                retailer_id=str(row["retailer_id"]),
                source_id=str(row["source_id"]),
                metric_definition_id=str(row["metric_definition_id"]),
                metric_definition_version=str(row["metric_definition_version"]),
                metric_config_hash=str(row["metric_config_hash"]) if row.get("metric_config_hash") else None,
                rule_version=str(row["rule_version"]) if row.get("rule_version") else None,
            )
            if entry is None:
                limitations.append(
                    QueryLimitation(
                        "metric_definition_not_in_catalog",
                        "Metric fact definition is not present in the effective catalog",
                        metric_definition_id=str(row["metric_definition_id"]),
                        metric_concept=str(row["metric_concept"]),
                    )
                )
                continue
            validation_grain = (
                str(row["grain_id"])
                if str(row["metric_concept"]) in SOURCE_LIKE_APPROVED_KPI_CONCEPTS
                else scoped_rollup_grain or request.grain_id
            )
            if validation_grain not in entry.grain_support:
                limitations.append(
                    QueryLimitation(
                        "metric_not_supported_for_grain",
                        f"Metric is not supported for grain_id={validation_grain}",
                        metric_definition_id=entry.metric_definition_id,
                        metric_concept=entry.metric_concept,
                    )
                )
            if request.period_grain not in entry.period_support:
                limitations.append(
                    QueryLimitation(
                        "metric_not_supported_for_period_grain",
                        f"Metric is not supported for period_grain={request.period_grain}",
                        metric_definition_id=entry.metric_definition_id,
                        metric_concept=entry.metric_concept,
                    )
                )
            if request.comparison_mode.value not in entry.comparison_support:
                limitations.append(
                    QueryLimitation(
                        "metric_not_supported_for_comparison",
                        f"Metric is not supported for comparison_mode={request.comparison_mode.value}",
                        metric_definition_id=entry.metric_definition_id,
                        metric_concept=entry.metric_concept,
                    )
                )
            if request.private_label_scope not in entry.private_label_scope_support:
                limitations.append(
                    QueryLimitation(
                        "metric_not_supported_for_private_label_scope",
                        f"Metric is not supported for private_label_scope={request.private_label_scope.value}",
                        metric_definition_id=entry.metric_definition_id,
                        metric_concept=entry.metric_concept,
                    )
                )
            fact_strategy = RangeAggregationStrategy(str(row["range_aggregation_strategy"]))
            if entry.range_aggregation_strategy != fact_strategy:
                limitations.append(
                    QueryLimitation(
                        "catalog_range_strategy_mismatch",
                        "Catalog range strategy differs from persisted mart fact strategy",
                        metric_definition_id=entry.metric_definition_id,
                        metric_concept=entry.metric_concept,
                    )
                )
            if entry.availability_status in {
                MetricAvailabilityStatus.NOT_AVAILABLE,
                MetricAvailabilityStatus.NOT_APPLICABLE,
            }:
                limitations.append(
                    QueryLimitation(
                        "metric_not_available",
                        f"Metric availability is {entry.availability_status.value}",
                        metric_definition_id=entry.metric_definition_id,
                        metric_concept=entry.metric_concept,
                    )
                )
        return tuple(_dedupe_limitations(limitations))

    def _private_label_scope_materialization_limitations(
        self,
        request: DashboardMetricQueryRequest,
    ) -> tuple[QueryLimitation, ...]:
        if self._facts_have_private_label_scope() or request.private_label_scope == PrivateLabelScope.INCLUDE:
            return ()
        return (
            QueryLimitation(
                "private_label_scope_not_materialized",
                "Mart facts do not contain private_label_scope for scoped analytical queries.",
            ),
        )

    def _facts_have_private_label_scope(self) -> bool:
        if self._fact_columns is None:
            self._fact_columns = _duckdb_columns(self.metric_facts_path)
        return "private_label_scope" in self._fact_columns

    def _period_grain_limitations(
        self,
        request: DashboardMetricQueryRequest,
    ) -> tuple[QueryLimitation, ...]:
        if request.period_grain in {"month", "day"}:
            return ()
        return (
            QueryLimitation(
                "coverage_period_grain_unsupported",
                f"Coverage calendar expansion is not implemented for period_grain={request.period_grain}",
            ),
        )


def _metric_results(
    frame: pl.DataFrame,
    request: DashboardMetricQueryRequest,
    catalog: tuple[EffectiveMetricCatalogEntry, ...],
    requested_periods: tuple[date, ...],
) -> tuple[tuple[MetricQueryResult, ...], tuple[QueryLimitation, ...]]:
    if frame.is_empty():
        return (), ()
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in frame.to_dicts():
        key = (
            row["metric_definition_id"],
            row["metric_definition_version"],
            row["metric_config_hash"],
            row["rule_version"],
            row["metric_concept"],
            row["metric_name"],
            row["grain_id"],
            row["entity_id"],
            row["parent_entity_ids"],
            row["range_aggregation_strategy"],
            row["share_scope"],
        )
        groups[key].append(row)

    results: list[MetricQueryResult] = []
    limitations: list[QueryLimitation] = []
    for key, rows in sorted(groups.items(), key=lambda item: item[0]):
        strategy = RangeAggregationStrategy(str(key[9]))
        lineage = _lineage(rows[0]) if request.include_lineage else None
        period_values = tuple(_period_value(row) for row in sorted(rows, key=lambda row: row["period_start"]))
        value, numerator, denominator, result_limitations = _aggregate_rows(
            rows,
            strategy,
            request,
            requested_periods,
        )
        limitations.extend(result_limitations)
        results.append(
            MetricQueryResult(
                metric_concept=str(key[4]),
                metric_name=str(key[5]),
                grain_id=str(key[6]),
                entity_id=str(key[7]),
                value=value,
                numerator_value=numerator,
                denominator_value=denominator,
                range_aggregation_strategy=strategy,
                share_scope=str(key[10]) if key[10] is not None else None,
                period_values=period_values,
                lineage=lineage,
                limitations=tuple(item.issue_code for item in result_limitations),
                private_label_scope=request.private_label_scope,
            )
        )
    return tuple(results), tuple(_dedupe_limitations(limitations))


def _aggregate_rows(
    rows: list[dict[str, Any]],
    strategy: RangeAggregationStrategy,
    request: DashboardMetricQueryRequest,
    requested_periods: tuple[date, ...],
) -> tuple[float | None, float | None, float | None, tuple[QueryLimitation, ...]]:
    if request.period_mode == PeriodMode.SINGLE_PERIOD:
        row = max(rows, key=lambda item: item["period_start"])
        return (
            _float_or_none(row["value"]),
            _float_or_none(row["numerator_value"]),
            _float_or_none(row["denominator_value"]),
            (),
        )

    if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET and request.period_grain != "month":
        return None, None, None, (
            QueryLimitation(
                "available_month_set_requires_month_grain",
                "Available-month set semantics are defined only for monthly facts",
                metric_definition_id=str(rows[0]["metric_definition_id"]),
                metric_concept=str(rows[0]["metric_concept"]),
            ),
        )

    result_limitations = list(_result_coverage_limitations(rows, requested_periods))
    if strategy == RangeAggregationStrategy.SUM_AVAILABLE_PERIODS:
        if any(row["value"] is None for row in rows):
            return None, None, None, (
                *result_limitations,
                QueryLimitation(
                    "additive_value_missing",
                    "Additive range aggregation requires non-null values for every returned fact",
                    metric_definition_id=str(rows[0]["metric_definition_id"]),
                    metric_concept=str(rows[0]["metric_concept"]),
                ),
            )
        total = sum(_float_or_zero(row["value"]) for row in rows)
        if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET:
            month_count = len({row["period_start"] for row in rows})
            if month_count == 0:
                return None, total, 0.0, (
                    *result_limitations,
                    QueryLimitation(
                        "available_month_set_empty",
                        "Available-month aggregation requires at least one available month",
                        metric_definition_id=str(rows[0]["metric_definition_id"]),
                        metric_concept=str(rows[0]["metric_concept"]),
                    ),
                )
            return total / month_count, total, float(month_count), tuple(result_limitations)
        return total, None, None, tuple(result_limitations)
    if strategy in {
        RangeAggregationStrategy.RATIO_OF_SUMS,
        RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
        RangeAggregationStrategy.RECOMPUTE_FROM_COMPONENTS,
        RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
    }:
        if any(row["numerator_value"] is None or row["denominator_value"] is None for row in rows):
            return None, None, None, (
                *result_limitations,
                QueryLimitation(
                    "range_components_missing",
                    "Range aggregation requires numerator_value and denominator_value for every period",
                    metric_definition_id=str(rows[0]["metric_definition_id"]),
                    metric_concept=str(rows[0]["metric_concept"]),
                ),
            )
        numerator = sum(_float_or_zero(row["numerator_value"]) for row in rows)
        denominator = sum(_float_or_zero(row["denominator_value"]) for row in rows)
        if denominator == 0:
            return None, numerator, denominator, (
                *result_limitations,
                QueryLimitation(
                    "zero_range_denominator",
                    "Range aggregation denominator is zero",
                    metric_definition_id=str(rows[0]["metric_definition_id"]),
                    metric_concept=str(rows[0]["metric_concept"]),
                ),
            )
        if strategy == RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE:
            share_scopes = {row["share_scope"] for row in rows}
            if len(share_scopes) != 1 or None in share_scopes:
                return None, numerator, denominator, (
                    *result_limitations,
                    QueryLimitation(
                        "share_scope_missing_or_mixed",
                        "Share range aggregation requires one declared share_scope",
                        metric_definition_id=str(rows[0]["metric_definition_id"]),
                        metric_concept=str(rows[0]["metric_concept"]),
                    ),
                )
        return numerator / denominator, numerator, denominator, tuple(result_limitations)
    if strategy == RangeAggregationStrategy.PERIOD_ONLY:
        return None, None, None, (
            *result_limitations,
            QueryLimitation(
                "range_aggregation_period_only",
                "Metric is available as a period series only for selected ranges",
                metric_definition_id=str(rows[0]["metric_definition_id"]),
                metric_concept=str(rows[0]["metric_concept"]),
            ),
        )
    return None, None, None, (
        *result_limitations,
        QueryLimitation(
            "range_aggregation_unsupported",
            "Metric range aggregation is unsupported",
            metric_definition_id=str(rows[0]["metric_definition_id"]),
            metric_concept=str(rows[0]["metric_concept"]),
        ),
    )


def _comparisons(
    frame: pl.DataFrame,
    metric_results: tuple[MetricQueryResult, ...],
    request: DashboardMetricQueryRequest,
) -> tuple[tuple[ComparisonResult, ...], tuple[QueryLimitation, ...]]:
    if request.comparison_mode == ComparisonMode.NONE:
        return (), ()
    if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET:
        return _available_month_set_comparisons(frame, metric_results, request)
    if request.period_mode != PeriodMode.SINGLE_PERIOD:
        return (), (
            QueryLimitation(
                "range_comparison_unsupported",
                "Selected-range comparisons are not implemented in this backend unit",
            ),
        )
    if request.date_from is None:
        return (), (QueryLimitation("comparison_period_required", "Comparison requires date_from"),)
    target = _comparison_target(frame, request)
    if target is None:
        return (), (
            QueryLimitation(
                "comparison_period_missing",
                f"No comparison period is available for {request.comparison_mode.value}",
            ),
        )
    del metric_results
    current_rows = frame.filter(pl.col("period_start") == request.date_from).to_dicts()
    current_by_identity = {_comparison_identity(row): row for row in current_rows}
    comparison_rows = frame.filter(pl.col("period_start") == target).to_dicts()
    comparisons: list[ComparisonResult] = []
    for row in comparison_rows:
        key = _comparison_identity(row)
        current = current_by_identity.get(key)
        if current is None:
            continue
        comparison_value = _float_or_none(row["value"])
        current_value = _float_or_none(current["value"])
        delta = None if current_value is None or comparison_value is None else current_value - comparison_value
        pct_delta = None
        if delta is not None and comparison_value not in (None, 0):
            pct_delta = delta / comparison_value
        gap = _period_gap(target, request.date_from, request.period_grain)
        quality = "HIGH" if request.comparison_mode != ComparisonMode.PREVIOUS_AVAILABLE or gap == 1 else "MEDIUM"
        comparisons.append(
            ComparisonResult(
                comparison_mode=request.comparison_mode,
                metric_definition_id=str(row["metric_definition_id"]),
                entity_id=str(row["entity_id"]),
                current_period_start=request.date_from,
                comparison_period_start=target,
                current_value=current_value,
                comparison_value=comparison_value,
                delta=delta,
                pct_delta=pct_delta,
                quality_status=quality,
                gap_periods=gap,
                private_label_scope=request.private_label_scope,
            )
        )
    return tuple(comparisons), ()


def _available_month_set_comparisons(
    frame: pl.DataFrame,
    metric_results: tuple[MetricQueryResult, ...],
    request: DashboardMetricQueryRequest,
) -> tuple[tuple[ComparisonResult, ...], tuple[QueryLimitation, ...]]:
    if request.comparison_mode != ComparisonMode.YOY:
        return (), (
            QueryLimitation(
                "available_month_comparison_mode_unsupported",
                "Available-month set comparison currently supports matched month year-over-year only",
            ),
        )
    current_periods = _result_periods(metric_results)
    if not current_periods:
        return (), (QueryLimitation("available_month_set_empty", "No current available months matched the request"),)
    reference_periods = _reference_periods_for_matched_yoy(current_periods, frame)
    if len(reference_periods) != len(current_periods):
        return (), (
            QueryLimitation(
                "available_month_reference_set_incomplete",
                "Matched available-month comparison requires the same month numbers on both sides",
            ),
        )
    reference_frame = frame.filter(pl.col("period_start").is_in(reference_periods))
    reference_request = replace(
        request,
        date_from=min(reference_periods),
        date_to=max(reference_periods),
        comparison_mode=ComparisonMode.NONE,
    )
    reference_results, reference_limitations = _metric_results(
        reference_frame,
        reference_request,
        (),
        reference_periods,
    )
    current_by_identity = {_result_comparison_identity(result): result for result in metric_results}
    comparisons: list[ComparisonResult] = []
    for reference in reference_results:
        current = current_by_identity.get(_result_comparison_identity(reference))
        if current is None:
            continue
        comparison_value = reference.value
        current_value = current.value
        delta = None if current_value is None or comparison_value is None else current_value - comparison_value
        pct_delta = None
        if delta is not None and comparison_value not in (None, 0):
            pct_delta = delta / comparison_value
        comparisons.append(
            ComparisonResult(
                comparison_mode=request.comparison_mode,
                metric_definition_id=_result_metric_definition_id(reference),
                entity_id=current.entity_id,
                current_period_start=min(current_periods),
                comparison_period_start=min(reference_periods),
                current_value=current_value,
                comparison_value=comparison_value,
                delta=delta,
                pct_delta=pct_delta,
                quality_status="HIGH",
                gap_periods=_period_gap(min(reference_periods), min(current_periods), request.period_grain),
                private_label_scope=request.private_label_scope,
                current_included_periods=current_periods,
                comparison_included_periods=reference_periods,
                aggregation_method=_available_month_aggregation_method(
                    request,
                    current.range_aggregation_strategy,
                ),
                comparison_policy="MATCHED_AVAILABLE_MONTHS",
            )
        )
    return tuple(comparisons), tuple(reference_limitations)


def _attach_provenance(
    metric_results: tuple[MetricQueryResult, ...],
    *,
    request: DashboardMetricQueryRequest,
    mart_build_id: str,
    analysis_run_ids: tuple[str, ...],
    requested_periods: tuple[date, ...],
    available_periods: tuple[date, ...],
    missing_periods: tuple[date, ...],
    comparisons: tuple[ComparisonResult, ...],
    response_quality_flags: tuple[str, ...],
    scoped_rollup_grain: str | None = None,
    serving_fact_grain: str | None = None,
) -> tuple[MetricQueryResult, ...]:
    return tuple(
        replace(
            result,
            provenance=MetricProvenanceTrace(
                _provenance_payload(
                    result,
                    request=request,
                    mart_build_id=mart_build_id,
                    analysis_run_ids=analysis_run_ids,
                    requested_periods=requested_periods,
                    available_periods=available_periods,
                    missing_periods=missing_periods,
                    comparisons=comparisons,
                    response_quality_flags=response_quality_flags,
                    scoped_rollup_grain=scoped_rollup_grain,
                    serving_fact_grain=serving_fact_grain,
                )
            ),
        )
        for result in metric_results
    )


def _provenance_payload(
    result: MetricQueryResult,
    *,
    request: DashboardMetricQueryRequest,
    mart_build_id: str,
    analysis_run_ids: tuple[str, ...],
    requested_periods: tuple[date, ...],
    available_periods: tuple[date, ...],
    missing_periods: tuple[date, ...],
    comparisons: tuple[ComparisonResult, ...],
    response_quality_flags: tuple[str, ...],
    scoped_rollup_grain: str | None = None,
    serving_fact_grain: str | None = None,
) -> dict[str, Any]:
    lineage = result.lineage
    period_source_revisions = tuple(sorted({period.source_revision_id for period in result.period_values}))
    period_analysis_runs = tuple(sorted({period.analysis_run_id for period in result.period_values}))
    quality_statuses = tuple(sorted({period.quality_status for period in result.period_values}))
    quality_flags = tuple(
        sorted(
            {
                flag
                for flag in (*response_quality_flags, *(period.quality_flags for period in result.period_values))
                if flag
            }
        )
    )
    result_comparisons = tuple(
        item
        for item in comparisons
        if item.entity_id == result.entity_id
        and lineage is not None
        and item.metric_definition_id == lineage.metric_definition_id
        and item.private_label_scope == result.private_label_scope
    )
    comparison_payload = {
        "comparison_mode": request.comparison_mode.value,
        "status": _comparison_provenance_status(request, result_comparisons),
        "quality_statuses": tuple(sorted({item.quality_status for item in result_comparisons})),
        "period_set": _comparison_period_set_payload(request, result_comparisons),
        "periods": tuple(
            {
                "current_period_start": item.current_period_start,
                "comparison_period_start": item.comparison_period_start,
                "current_included_periods": item.current_included_periods,
                "comparison_included_periods": item.comparison_included_periods,
                "aggregation_method": item.aggregation_method,
                "comparison_policy": item.comparison_policy,
                "gap_periods": item.gap_periods,
            }
            for item in result_comparisons
        ),
    }
    business_rule_id = _result_business_rule_id(result)
    denominator_universe_type = _result_denominator_universe_type(result)
    store_alias_versions = tuple(
        sorted({period.store_alias_mapping_version for period in result.period_values if period.store_alias_mapping_version})
    )
    numerator_metric_names = tuple(sorted({period.numerator_metric_name for period in result.period_values if period.numerator_metric_name}))
    denominator_metric_names = tuple(
        sorted({period.denominator_metric_name for period in result.period_values if period.denominator_metric_name})
    )
    missing_fields = list(_lineage_missing_fields(lineage))
    if not result_comparisons and request.comparison_mode != ComparisonMode.NONE:
        missing_fields.extend(("comparison_periods", "comparison_quality"))
    if lineage is None or not lineage.rule_version:
        missing_fields.append("business_rule_version")
    if business_rule_id is None:
        missing_fields.append("business_rule_id")
    if denominator_universe_type is None:
        missing_fields.append("denominator_universe_type")
    if result.metric_concept in {"distribution", STORE_FORMAT_DISTRIBUTION_CONCEPT} and not store_alias_versions:
        missing_fields.append("store_alias_mapping_version")
    missing_fields.append("source_row_ids")

    return {
        "current_analytical_scope": {
            "retailer_id": request.retailer_id,
            "source_id": request.source_id,
            "period_mode": request.period_mode.value,
            "period_grain": request.period_grain,
            "requested_periods": requested_periods,
            "available_periods": available_periods,
            "missing_periods": missing_periods,
            "grain_id": result.grain_id,
            "entity_id": result.entity_id,
            "entity_ids": request.entity_ids,
            "private_label_scope": request.private_label_scope.value,
            "entity_filters": request.entity_filters or {},
            "scope_identity_hash": scope_identity_hash(
                private_label_scope=request.private_label_scope,
                entity_filters=request.entity_filters,
            ),
            "period_set": _period_set_payload(request, result.period_values),
        },
        "metric": {
            "metric_concept": result.metric_concept,
            "metric_name": result.metric_name,
            "metric_definition_id": lineage.metric_definition_id if lineage is not None else None,
            "metric_definition_version": lineage.metric_definition_version if lineage is not None else None,
            "metric_config_hash": lineage.metric_config_hash if lineage is not None else None,
            "semantic_family": lineage.semantic_family if lineage is not None else None,
            "semantic_compatibility_version": lineage.semantic_compatibility_version if lineage is not None else None,
            "cross_retailer_comparable": lineage.cross_retailer_comparable if lineage is not None else None,
        },
        "value": {
            "value": result.value,
            "numerator_value": result.numerator_value,
            "denominator_value": result.denominator_value,
            "aggregation_strategy": result.range_aggregation_strategy.value,
            "range_aggregation_strategy": result.range_aggregation_strategy.value,
            "available_month_aggregation_method": _available_month_aggregation_method(
                request,
                result.range_aggregation_strategy,
            ),
            "share_scope": result.share_scope,
            "period_values": tuple(
                {
                    "period_start": period.period_start,
                    "period_end": period.period_end,
                    "business_period_id": period.business_period_id,
                    "value": period.value,
                    "numerator_value": period.numerator_value,
                    "denominator_value": period.denominator_value,
                    "quality_status": period.quality_status,
                }
                for period in result.period_values
            ),
        },
        "comparison": comparison_payload,
        "business_rule": {
            "business_rule_id": business_rule_id,
            "business_rule_version": lineage.rule_version if lineage is not None else None,
        },
        "run_lineage": {
            "analysis_run_ids": analysis_run_ids or period_analysis_runs,
            "mart_build_id": mart_build_id,
            "source_revision_ids": period_source_revisions,
        },
        "source_evidence": {
            "status": "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS",
            "period_fact_count": len(result.period_values),
            "source_revision_ids": period_source_revisions,
            "source_row_ids": (),
            "denominator_universe_type": denominator_universe_type,
            "store_alias_mapping_versions": store_alias_versions,
            "numerator_metric_names": numerator_metric_names,
            "denominator_metric_names": denominator_metric_names,
        },
        "scoped_rollup": {
            "status": _rollup_provenance_status(scoped_rollup_grain, serving_fact_grain),
            "source_fact_grain": serving_fact_grain or scoped_rollup_grain,
            "requested_grain": request.grain_id,
            "entity_filters": request.entity_filters or {},
            "formula": "sum child values or recompute ratio from child numerators and denominators"
            if scoped_rollup_grain or serving_fact_grain
            else None,
            "rolled_period_count": len(result.period_values),
            "serving_projection_version": "product_store_serving.v1" if serving_fact_grain else None,
        },
        "quality": {
            "quality_statuses": quality_statuses,
            "quality_flags": quality_flags,
            "result_limitations": result.limitations,
        },
        "missing_fields": tuple(dict.fromkeys(missing_fields)),
    }


def _comparison_provenance_status(
    request: DashboardMetricQueryRequest,
    comparisons: tuple[ComparisonResult, ...],
) -> str:
    if request.comparison_mode == ComparisonMode.NONE:
        return "NOT_APPLICABLE"
    return "COMPLETE" if comparisons else "PARTIAL"


def _lineage_missing_fields(lineage: MetricDefinitionLineage | None) -> tuple[str, ...]:
    if lineage is not None:
        return ()
    return (
        "metric_definition_id",
        "metric_definition_version",
        "metric_config_hash",
        "semantic_family",
        "semantic_compatibility_version",
    )


def _requests_store_format_distribution(request: DashboardMetricQueryRequest) -> bool:
    if STORE_FORMAT_DISTRIBUTION_CONCEPT in request.metric_concepts:
        return True
    return any(STORE_FORMAT_DISTRIBUTION_CONCEPT in item for item in request.metric_definition_ids)


def _source_like_approved_kpi_concepts(request: DashboardMetricQueryRequest) -> tuple[str, ...]:
    concepts = [concept for concept in request.metric_concepts if concept in SOURCE_LIKE_APPROVED_KPI_CONCEPTS]
    concepts.extend(
        concept
        for concept in (
            _source_like_metric_concept_from_definition_id(
                request.retailer_id,
                request.grain_id,
                metric_definition_id,
            )
            for metric_definition_id in request.metric_definition_ids
        )
        if concept is not None
    )
    return tuple(dict.fromkeys(concepts))


def _request_without_source_like_approved_kpis(
    request: DashboardMetricQueryRequest,
) -> DashboardMetricQueryRequest:
    remaining_definition_ids = tuple(
        metric_definition_id
        for metric_definition_id in request.metric_definition_ids
        if _source_like_metric_concept_from_definition_id(
            request.retailer_id,
            request.grain_id,
            metric_definition_id,
        )
        is None
    )
    if not request.metric_concepts and remaining_definition_ids == request.metric_definition_ids:
        return request
    concepts = tuple(concept for concept in request.metric_concepts if concept not in SOURCE_LIKE_APPROVED_KPI_CONCEPTS)
    return replace(request, metric_concepts=concepts, metric_definition_ids=remaining_definition_ids)


def _source_like_only_request(
    request: DashboardMetricQueryRequest,
    fact_request: DashboardMetricQueryRequest,
) -> bool:
    return (
        bool(_source_like_approved_kpi_concepts(request))
        and not fact_request.metric_concepts
        and not fact_request.metric_definition_ids
    )


def _source_like_effective_scope_request(request: DashboardMetricQueryRequest) -> DashboardMetricQueryRequest:
    if request.metric_definition_ids:
        return request
    effective_grain = _source_like_effective_filter_grain(request)
    if effective_grain not in {"category", "brand", "sku"}:
        return request
    semantic_filters = _source_like_semantic_filters(request)
    selected = tuple(semantic_filters.get(effective_grain, ()))
    if len(selected) != 1:
        return request
    remaining_filters = {
        grain: values
        for grain, values in semantic_filters.items()
        if grain != effective_grain and values
    }
    return replace(
        request,
        grain_id=effective_grain,
        entity_ids=selected,
        entity_filters=remaining_filters,
    )


def _source_like_effective_filter_grain(request: DashboardMetricQueryRequest) -> str | None:
    selected = _source_like_semantic_filters(request)
    for grain in SOURCE_LIKE_APPROVED_KPI_FILTER_PRECEDENCE:
        if selected.get(grain):
            return grain
    return _effective_filter_grain(request)


def _source_like_semantic_filters(request: DashboardMetricQueryRequest) -> dict[str, tuple[str, ...]]:
    return request.user_entity_filters or request.entity_filters or {}


def _source_like_metric_concept_from_definition_id(
    retailer_id: str,
    grain_id: str,
    metric_definition_id: str,
) -> str | None:
    prefix = f"{retailer_id}.{grain_id}."
    suffix = ".v1"
    if not metric_definition_id.startswith(prefix) or not metric_definition_id.endswith(suffix):
        return None
    concept = metric_definition_id[len(prefix) : -len(suffix)]
    if concept not in SOURCE_LIKE_APPROVED_KPI_CONCEPTS:
        return None
    return concept


def _source_like_approved_kpi_limitations(
    request: DashboardMetricQueryRequest,
    metric_concepts: tuple[str, ...],
) -> tuple[QueryLimitation, ...]:
    limitations: list[QueryLimitation] = []
    for concept in metric_concepts:
        if request.grain_id not in SOURCE_LIKE_APPROVED_KPI_SUPPORT.get(concept, frozenset()):
            limitations.append(
                QueryLimitation(
                    "metric_not_supported_for_grain",
                    f"Approved KPI is not supported for grain_id={request.grain_id}",
                    metric_definition_id=_source_like_metric_definition_id(request.retailer_id, request.grain_id, concept),
                    metric_concept=concept,
                )
            )
    if request.grain_id == "manufacturer":
        for concept in metric_concepts:
            limitations.append(
                QueryLimitation(
                    "manufacturer_kpi_grain_unsupported",
                    "Approved KPI rules do not introduce manufacturer as a supported KPI grain.",
                    metric_definition_id=_source_like_metric_definition_id(request.retailer_id, request.grain_id, concept),
                    metric_concept=concept,
                )
            )
    return tuple(_dedupe_limitations(limitations))


def _source_like_approved_kpi_rows(
    source: pl.DataFrame,
    request: DashboardMetricQueryRequest,
    build: MartBuildMetadata,
    concept: str,
) -> list[dict[str, Any]]:
    scoped = _source_like_product_scoped_rows(source, request)
    if scoped.is_empty() and request.grain_id != "network":
        return []
    active_universe = _active_store_universe_by_period(source)
    rows: list[dict[str, Any]] = []
    for period in sorted(source.get_column("period").unique().to_list()):
        period_source = source.filter(pl.col("period") == period)
        period_scoped = scoped.filter(pl.col("period") == period)
        if request.grain_id == "network":
            groups = [(request.entity_ids[0] if request.entity_ids else request.grain_id, period_scoped, {})]
        else:
            entity_column = SOURCE_LIKE_ENTITY_COLUMNS[request.grain_id]
            assert entity_column is not None
            groups = []
            for entity_id in sorted(period_scoped.get_column(entity_column).drop_nulls().unique().to_list()):
                entity_rows = period_scoped.filter(pl.col(entity_column) == entity_id)
                groups.append((str(entity_id), entity_rows, _source_like_parent_ids(entity_rows, request.grain_id, str(entity_id))))
        for entity_id, entity_rows, parent_ids in groups:
            if entity_rows.is_empty():
                continue
            numerator, denominator = _source_like_components_for_concept(
                concept,
                entity_rows,
                period_source,
                active_universe.get(period, 0.0),
            )
            rows.append(
                _source_like_metric_fact_row(
                    request=request,
                    build=build,
                    period=period,
                    entity_id=str(entity_id),
                    parent_entity_ids=parent_ids,
                    concept=concept,
                    numerator=numerator,
                    denominator=denominator,
                )
            )
    return rows


def _source_like_product_scoped_rows(source: pl.DataFrame, request: DashboardMetricQueryRequest) -> pl.DataFrame:
    result = source
    for key, values in (request.entity_filters or {}).items():
        column = SOURCE_LIKE_ENTITY_COLUMNS.get(key)
        if column is not None and values:
            result = result.filter(pl.col(column).cast(pl.Utf8).is_in([str(value) for value in values]))
    entity_column = SOURCE_LIKE_ENTITY_COLUMNS.get(request.grain_id)
    if request.entity_ids and entity_column is not None:
        result = result.filter(pl.col(entity_column).cast(pl.Utf8).is_in([str(value) for value in request.entity_ids]))
    return result


def _source_like_range_components(
    source: pl.DataFrame,
    request: DashboardMetricQueryRequest,
    metric_concepts: tuple[str, ...],
) -> dict[tuple[str, str], tuple[float | None, float | None]]:
    scoped = _source_like_product_scoped_rows(source, request)
    active_universe = _distinct_active_stores(source)
    overrides: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    if request.grain_id == "network":
        entity_id = request.entity_ids[0] if request.entity_ids else request.grain_id
        groups = [(str(entity_id), scoped)]
    else:
        entity_column = SOURCE_LIKE_ENTITY_COLUMNS[request.grain_id]
        assert entity_column is not None
        groups = [
            (str(entity_id), scoped.filter(pl.col(entity_column).cast(pl.Utf8) == str(entity_id)))
            for entity_id in sorted(scoped.get_column(entity_column).drop_nulls().unique().to_list())
        ]
    for entity_id, entity_rows in groups:
        for concept in metric_concepts:
            if request.grain_id not in SOURCE_LIKE_APPROVED_KPI_SUPPORT.get(concept, frozenset()):
                continue
            overrides[(concept, entity_id)] = _source_like_components_for_concept(
                concept,
                entity_rows,
                source,
                active_universe,
            )
    return overrides


def _active_store_universe_by_period(source: pl.DataFrame) -> dict[date, float]:
    if source.is_empty():
        return {}
    frame = (
        source.filter((pl.col("units") > 0) & pl.col("canonical_store_id").is_not_null())
        .group_by("period")
        .agg(pl.col("canonical_store_id").n_unique().alias("active_store_count"))
    )
    return {row["period"]: float(row["active_store_count"]) for row in frame.to_dicts()}


def _source_like_components_for_concept(
    concept: str,
    entity_rows: pl.DataFrame,
    period_source: pl.DataFrame,
    active_store_universe: float,
) -> tuple[float | None, float | None]:
    if concept == "velocity":
        numerator = _sum(entity_rows, "units")
        denominator = _distinct_active_stores(entity_rows)
        return numerator, denominator
    if concept == "distribution":
        numerator = _distinct_active_stores(entity_rows)
        return numerator, active_store_universe
    if concept == "weighted_distribution":
        categories = [str(value) for value in entity_rows.get_column("category").drop_nulls().unique().to_list()]
        if len(categories) != 1:
            return None, None
        category_rows = period_source.filter(pl.col("category").cast(pl.Utf8) == categories[0])
        active_stores = [
            str(value)
            for value in entity_rows.filter((pl.col("units") > 0) & pl.col("canonical_store_id").is_not_null())
            .get_column("canonical_store_id")
            .unique()
            .to_list()
        ]
        numerator = _sum(category_rows.filter(pl.col("canonical_store_id").cast(pl.Utf8).is_in(active_stores)), "revenue_vat")
        denominator = _sum(category_rows, "revenue_vat")
        return numerator, denominator
    if concept == "average_price_per_liter":
        valid = entity_rows.filter(
            pl.col("volume_l").is_not_null()
            & (pl.col("volume_l") > 0)
            & pl.col("units").is_not_null()
            & pl.col("revenue_vat").is_not_null()
        )
        numerator = _sum(valid, "revenue_vat")
        denominator = _sum_expr(valid, pl.col("units") * pl.col("volume_l"))
        return numerator, denominator
    raise ValueError(f"Unsupported approved KPI concept: {concept}")


def _source_like_metric_fact_row(
    *,
    request: DashboardMetricQueryRequest,
    build: MartBuildMetadata,
    period: date,
    entity_id: str,
    parent_entity_ids: dict[str, Any],
    concept: str,
    numerator: float | None,
    denominator: float | None,
) -> dict[str, Any]:
    value = None if numerator is None or denominator in (None, 0) else numerator / denominator
    period_end = date(period.year, period.month, calendar.monthrange(period.year, period.month)[1])
    return {
        "retailer_id": request.retailer_id,
        "source_id": request.source_id,
        "source_revision_id": build.source_revision_ids[0],
        "analysis_run_id": build.analysis_run_ids[0],
        "mart_build_id": build.mart_build_id,
        "private_label_scope": request.private_label_scope.value,
        "period_grain": request.period_grain,
        "period_start": period,
        "period_end": period_end,
        "business_period_id": period.isoformat(),
        "grain_id": request.grain_id,
        "entity_id": entity_id,
        "parent_entity_ids": _json_parent_ids(parent_entity_ids),
        "metric_concept": concept,
        "metric_name": _source_like_metric_name(concept),
        "metric_definition_id": _source_like_metric_definition_id(request.retailer_id, request.grain_id, concept),
        "metric_definition_version": "v1",
        "metric_config_hash": build.metric_config_hashes[0],
        "semantic_family": None,
        "semantic_compatibility_version": None,
        "cross_retailer_comparable": False,
        "value": value,
        "numerator_value": numerator,
        "denominator_value": denominator,
        "business_rule_id": _source_like_business_rule_id(concept),
        "denominator_universe_type": _source_like_denominator_universe_type(concept),
        "store_alias_mapping_version": None,
        "numerator_metric_name": _source_like_numerator_metric_name(concept),
        "denominator_metric_name": _source_like_denominator_metric_name(concept),
        "aggregation": "ratio_of_sums",
        "range_aggregation_strategy": RangeAggregationStrategy.RATIO_OF_SUMS.value,
        "share_scope": _source_like_share_scope(concept),
        "rule_version": build.rule_versions[0],
        "quality_status": "valid" if value is not None else "missing",
        "quality_flags": None if value is not None else _source_like_null_quality_flag(concept),
        "created_at": build.built_at,
    }


def _source_like_parent_ids(rows: pl.DataFrame, grain: str, entity_id: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for column in ("category", "manufacturer", "brand"):
        unique = rows.get_column(column).drop_nulls().unique().to_list() if column in rows.columns else []
        if len(unique) == 1:
            values[column] = str(unique[0])
    if grain == "sku":
        values["canonical_product_id"] = entity_id
    elif grain in {"category", "brand", "manufacturer", "store"}:
        values[PARENT_ENTITY_JSON_KEYS[grain]] = entity_id
    return values


def _source_like_metric_definition_id(retailer_id: str, grain: str, concept: str) -> str:
    return f"{retailer_id}.{grain}.{concept}.v1"


def _source_like_metric_name(concept: str) -> str:
    return {
        "velocity": "units_per_selling_store",
        "distribution": "numeric_distribution",
        "weighted_distribution": "weighted_distribution",
        "average_price_per_liter": "average_price_per_liter",
    }[concept]


def _source_like_business_rule_id(concept: str) -> str:
    return {
        "velocity": "BR-VPO",
        "distribution": "BR-ND",
        "weighted_distribution": "BR-WD",
        "average_price_per_liter": "BR-PPL",
    }[concept]


def _source_like_denominator_universe_type(concept: str) -> str:
    return {
        "velocity": "selling_store_count",
        "distribution": "selected_period_file_active_store_universe",
        "weighted_distribution": "category_revenue_outlet_universe",
        "average_price_per_liter": "sold_liters_valid_volume_rows",
    }[concept]


def _source_like_numerator_metric_name(concept: str) -> str:
    return {
        "velocity": "units",
        "distribution": "selling_store_count",
        "weighted_distribution": "category_revenue_in_object_active_outlets",
        "average_price_per_liter": "revenue_vat_valid_volume_rows",
    }[concept]


def _source_like_denominator_metric_name(concept: str) -> str:
    return {
        "velocity": "selling_store_count",
        "distribution": "active_store_count",
        "weighted_distribution": "category_revenue_total",
        "average_price_per_liter": "sold_liters",
    }[concept]


def _source_like_share_scope(concept: str) -> str | None:
    if concept == "weighted_distribution":
        return "category"
    if concept == "distribution":
        return "selected_period_file_active_store_universe"
    return None


def _source_like_null_quality_flag(concept: str) -> str:
    return {
        "velocity": "no_active_selling_outlets",
        "distribution": "empty_active_store_universe",
        "weighted_distribution": "category_revenue_denominator_unavailable",
        "average_price_per_liter": "sold_liters_denominator_unavailable",
    }[concept]


def _distinct_active_stores(frame: pl.DataFrame) -> float:
    if frame.is_empty():
        return 0.0
    return float(
        frame.filter((pl.col("units") > 0) & pl.col("canonical_store_id").is_not_null())
        .get_column("canonical_store_id")
        .n_unique()
    )


def _sum(frame: pl.DataFrame, column: str) -> float:
    if frame.is_empty():
        return 0.0
    value = frame.select(pl.col(column).sum()).item()
    return 0.0 if value is None else float(value)


def _sum_expr(frame: pl.DataFrame, expr: pl.Expr) -> float:
    if frame.is_empty():
        return 0.0
    value = frame.select(expr.sum()).item()
    return 0.0 if value is None else float(value)


def _add_source_like_filter(clauses: list[str], params: list[Any], column: str, values: tuple[str, ...]) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    clauses.append(f"CAST({column} AS VARCHAR) IN ({placeholders})")
    params.extend(str(value) for value in values)


def _concat_fact_frames(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
    frames = [frame for frame in (left, right) if not frame.is_empty()]
    if not frames:
        return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA)
    return pl.concat(frames, how="diagonal_relaxed").select(
        [pl.col(column).cast(dtype) for column, dtype in MART_METRIC_FACT_SCHEMA.items()]
    )


def _unsupported_distribution_scope_limitations(
    request: DashboardMetricQueryRequest,
) -> tuple[QueryLimitation, ...]:
    if _requests_store_format_distribution(request):
        return ()
    requested_distribution = "distribution" in request.metric_concepts or any(
        ".numeric_distribution." in item or item.endswith(".numeric_distribution.v1")
        for item in request.metric_definition_ids
    )
    if not requested_distribution:
        return ()
    filters = request.entity_filters or {}
    limitations: list[QueryLimitation] = []
    if filters.get("store_format"):
        limitations.append(
            QueryLimitation(
                "global_distribution_store_format_filter_unsupported",
                "Global BR-009 distribution is not reinterpreted under store-format filters; request numeric_distribution_store_format instead.",
                metric_concept="distribution",
            )
        )
    for column in ("territory", "fo", "fo2", "region"):
        if filters.get(column):
            limitations.append(
                QueryLimitation(
                    "territory_distribution_unsupported",
                    "Territory, FO2, and region distribution semantics are not approved.",
                    metric_concept="distribution",
                )
            )
    return tuple(_dedupe_limitations(limitations))


def _store_format_distribution_request_limitations(
    request: DashboardMetricQueryRequest,
) -> tuple[QueryLimitation, ...]:
    limitations: list[QueryLimitation] = []
    filters = request.entity_filters or {}
    store_formats = filters.get("store_format", ())
    extra_concepts = tuple(concept for concept in request.metric_concepts if concept != STORE_FORMAT_DISTRIBUTION_CONCEPT)
    if extra_concepts:
        limitations.append(
            QueryLimitation(
                "store_format_distribution_mixed_metric_request_unsupported",
                "Store-format distribution requests must not silently mix with other metric concepts.",
                metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
            )
        )
    if request.metric_definition_ids:
        limitations.append(
            QueryLimitation(
                "store_format_distribution_metric_definition_ids_unsupported",
                "Store-format distribution backend recomposition does not accept explicit metric_definition_ids.",
                metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
            )
        )
    if request.grain_id not in STORE_FORMAT_DISTRIBUTION_SUPPORTED_GRAINS:
        limitations.append(
            QueryLimitation(
                "store_format_distribution_grain_unsupported",
                "Store-format distribution is supported only for category, manufacturer, brand, and SKU entity grains.",
                metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
            )
        )
    if request.period_grain != "month":
        limitations.append(
            QueryLimitation(
                "store_format_distribution_period_grain_unsupported",
                "Store-format distribution is currently defined only for monthly periods.",
                metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
            )
        )
    if request.period_mode not in {PeriodMode.SINGLE_PERIOD, PeriodMode.DATE_RANGE, PeriodMode.FULL_AVAILABLE_HISTORY}:
        limitations.append(
            QueryLimitation(
                "store_format_distribution_period_mode_unsupported",
                "Store-format distribution only supports monthly period series and point-in-time values.",
                metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
            )
        )
    if len(store_formats) != 1:
        limitations.append(
            QueryLimitation(
                "store_format_distribution_requires_single_format",
                "Store-format distribution requires exactly one selected store_format universe.",
                metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
            )
        )
    if filters.get("store"):
        limitations.append(
            QueryLimitation(
                "store_filter_distribution_unsupported",
                "Store-filtered distribution is not an approved denominator semantics.",
                metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
            )
        )
    unsupported = sorted(set(filters) - {"category", "manufacturer", "brand", "sku", "store_format", "store"})
    for column in unsupported:
        limitations.append(
            QueryLimitation(
                "store_format_distribution_filter_unsupported",
                f"Store-format distribution does not support filter column: {column}",
                metric_concept=STORE_FORMAT_DISTRIBUTION_CONCEPT,
            )
        )
    return tuple(_dedupe_limitations(limitations))


def _store_format_distribution_metric_rows(
    product_store: pl.DataFrame,
    universe: pl.DataFrame,
    request: DashboardMetricQueryRequest,
    mart_build_id: str,
    store_format: str,
) -> pl.DataFrame:
    entity_column = _product_store_filter_column(request.grain_id)
    entity_parent_columns = {
        "category": (),
        "manufacturer": ("category",),
        "brand": ("category", "manufacturer"),
        "sku": ("category", "manufacturer", "brand"),
    }[request.grain_id]
    denominator_rows = (
        universe.group_by(
            [
                "retailer_id",
                "source_id",
                "period_grain",
                "period_start",
                "period_end",
            ]
        )
        .agg(
            pl.col("canonical_store_id").n_unique().cast(pl.Float64).alias("denominator_value"),
            pl.col("analysis_run_id").drop_nulls().first().alias("analysis_run_id"),
            pl.col("store_alias_mapping_version").drop_nulls().first().alias("store_alias_mapping_version"),
            pl.col("created_at").max().alias("created_at"),
        )
    )
    identity_groups = [
        "retailer_id",
        "source_id",
        "source_revision_id",
        "analysis_run_id",
        "mart_build_id",
        "period_grain",
        "period_start",
        "period_end",
        "business_period_id",
        entity_column,
        *entity_parent_columns,
    ]
    entity_scope = product_store.group_by(identity_groups).agg(
        pl.col("metric_config_hash").drop_nulls().first().alias("metric_config_hash"),
        pl.col("rule_version").drop_nulls().first().alias("rule_version"),
        pl.col("created_at").max().alias("created_at"),
    )
    selling = (
        product_store.filter(pl.col("value") > 0)
        .group_by(identity_groups)
        .agg(pl.col("canonical_store_id").n_unique().cast(pl.Float64).alias("numerator_value"))
    )
    rows = entity_scope.join(selling, on=identity_groups, how="left").with_columns(
        pl.col("numerator_value").fill_null(0.0)
    )
    rows = rows.join(
        denominator_rows,
        on=[
            "retailer_id",
            "source_id",
            "period_grain",
            "period_start",
            "period_end",
        ],
        how="inner",
        suffix="_universe",
    )
    rows = rows.with_columns(
        pl.when((pl.col("denominator_value") == 0) | pl.col("denominator_value").is_null())
        .then(None)
        .otherwise(pl.col("numerator_value") / pl.col("denominator_value"))
        .alias("value"),
        pl.col(entity_column).cast(pl.Utf8).alias("entity_id"),
        pl.struct(
            [
                *[pl.col(column).cast(pl.Utf8).alias(column) for column in entity_parent_columns],
                pl.lit(store_format).alias("store_format"),
            ]
        ).map_elements(
            lambda row: _json_parent_ids({key: value for key, value in row.items() if value is not None}),
            return_dtype=pl.Utf8,
        ).alias("parent_entity_ids"),
        pl.lit(STORE_FORMAT_DISTRIBUTION_CONCEPT).alias("metric_concept"),
        pl.lit(STORE_FORMAT_DISTRIBUTION_CONCEPT).alias("metric_name"),
        (
            pl.col("retailer_id")
            + pl.lit(".")
            + pl.lit(request.grain_id)
            + pl.lit(".")
            + pl.lit(STORE_FORMAT_DISTRIBUTION_CONCEPT)
            + pl.lit(".v1")
        ).alias("metric_definition_id"),
        pl.lit("v1").alias("metric_definition_version"),
        pl.lit(None, dtype=pl.Utf8).alias("semantic_family"),
        pl.lit(None, dtype=pl.Utf8).alias("semantic_compatibility_version"),
        pl.lit(False).alias("cross_retailer_comparable"),
        pl.lit("ratio_of_sums").alias("aggregation"),
        pl.lit(RangeAggregationStrategy.PERIOD_ONLY.value).alias("range_aggregation_strategy"),
        pl.lit(MONTHLY_STORE_FORMAT_UNIVERSE).alias("share_scope"),
        pl.lit(STORE_FORMAT_DISTRIBUTION_RULE_ID).alias("business_rule_id"),
        pl.lit(MONTHLY_STORE_FORMAT_UNIVERSE).alias("denominator_universe_type"),
        pl.lit("selling_store_count").alias("numerator_metric_name"),
        pl.lit("monthly_store_format_universe_count").alias("denominator_metric_name"),
        pl.lit("valid").alias("quality_status"),
        pl.lit(None, dtype=pl.Utf8).alias("quality_flags"),
        pl.lit(request.private_label_scope.value).alias("private_label_scope"),
        pl.lit(request.grain_id).alias("grain_id"),
    )
    return rows.select([pl.col(column).cast(dtype) for column, dtype in MART_METRIC_FACT_SCHEMA.items()])


def _result_business_rule_id(result: MetricQueryResult) -> str | None:
    period_values = {period.business_rule_id for period in result.period_values if period.business_rule_id}
    if len(period_values) == 1:
        return next(iter(period_values))
    if result.metric_concept == STORE_FORMAT_DISTRIBUTION_CONCEPT:
        return STORE_FORMAT_DISTRIBUTION_RULE_ID
    if result.metric_concept == "distribution":
        return "BR-009"
    return None


def _result_denominator_universe_type(result: MetricQueryResult) -> str | None:
    period_values = {
        period.denominator_universe_type
        for period in result.period_values
        if period.denominator_universe_type
    }
    if len(period_values) == 1:
        return next(iter(period_values))
    if result.metric_concept == STORE_FORMAT_DISTRIBUTION_CONCEPT:
        return MONTHLY_STORE_FORMAT_UNIVERSE
    if result.metric_concept == "distribution":
        return "monthly_file_store_universe"
    return None


def _comparison_target(frame: pl.DataFrame, request: DashboardMetricQueryRequest) -> date | None:
    if request.date_from is None:
        return None
    periods = sorted(set(frame.get_column("period_start").to_list())) if not frame.is_empty() else []
    if request.comparison_mode == ComparisonMode.YOY:
        candidate = date(request.date_from.year - 1, request.date_from.month, request.date_from.day)
        return candidate if candidate in periods else None
    if request.comparison_mode == ComparisonMode.MOM:
        candidate = _add_months(request.date_from, -1)
        return candidate if candidate in periods else None
    earlier = [period for period in periods if period < request.date_from]
    return earlier[-1] if earlier else None


def _effective_filter_grain(request: DashboardMetricQueryRequest) -> str | None:
    selected = request.entity_filters or {}
    candidates = [grain for grain in FILTER_GRAIN_ORDER if selected.get(grain)]
    if not candidates:
        return None
    requested_index = FILTER_GRAIN_ORDER.index(request.grain_id) if request.grain_id in FILTER_GRAIN_ORDER else -1
    effective = candidates[-1]
    effective_index = FILTER_GRAIN_ORDER.index(effective)
    return effective if effective_index > requested_index else None


def _has_product_store_intersection(request: DashboardMetricQueryRequest) -> bool:
    selected = request.entity_filters or {}
    product_scope_requested = request.grain_id in {"category", "manufacturer", "brand", "sku"}
    store_scope_requested = request.grain_id == "store"
    product_scope_filtered = any(selected.get(key) for key in ("category", "manufacturer", "brand", "sku"))
    store_scope_filtered = bool(selected.get("store"))
    return (store_scope_filtered and (product_scope_requested or product_scope_filtered)) or (
        store_scope_requested and product_scope_filtered
    )


def _product_store_filter_column(filter_name: str) -> str:
    return PARENT_ENTITY_JSON_KEYS[filter_name]


def _add_product_store_entity_id_filter(
    clauses: list[str],
    params: list[Any],
    grain_id: str,
    entity_ids: tuple[str, ...],
) -> None:
    if not entity_ids:
        return
    if grain_id == "network":
        return
    _add_in_filter(clauses, params, _product_store_filter_column(grain_id), entity_ids)


def _roll_up_product_store_facts(
    frame: pl.DataFrame,
    request: DashboardMetricQueryRequest,
    templates: dict[str, dict[str, Any]],
) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA)
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in frame.to_dicts():
        entity_id, parent_entity_ids = _product_store_result_identity(row, request)
        key = (
            row["retailer_id"],
            row["source_id"],
            row["source_revision_id"],
            row["analysis_run_id"],
            row["mart_build_id"],
            row.get("private_label_scope"),
            row["period_grain"],
            row["period_start"],
            row["period_end"],
            row["business_period_id"],
            row["metric_concept"],
            request.grain_id,
            entity_id,
            parent_entity_ids,
        )
        grouped[key].append(row)
    rolled: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        concept = str(key[10])
        template = templates.get(concept, rows[0])
        value, numerator_value, denominator_value = _roll_up_metric_values(rows)
        rolled.append(
            {
                "retailer_id": key[0],
                "source_id": key[1],
                "source_revision_id": key[2],
                "analysis_run_id": key[3],
                "mart_build_id": key[4],
                "private_label_scope": key[5],
                "period_grain": key[6],
                "period_start": key[7],
                "period_end": key[8],
                "business_period_id": key[9],
                "grain_id": key[11],
                "entity_id": key[12],
                "parent_entity_ids": key[13],
                "metric_concept": concept,
                "metric_name": template["metric_name"],
                "metric_definition_id": template["metric_definition_id"],
                "metric_definition_version": template["metric_definition_version"],
                "metric_config_hash": template["metric_config_hash"],
                "semantic_family": template["semantic_family"],
                "semantic_compatibility_version": template["semantic_compatibility_version"],
                "cross_retailer_comparable": template["cross_retailer_comparable"],
                "value": value,
                "numerator_value": numerator_value,
                "denominator_value": denominator_value,
                "business_rule_id": template.get("business_rule_id"),
                "denominator_universe_type": template.get("denominator_universe_type"),
                "store_alias_mapping_version": template.get("store_alias_mapping_version"),
                "numerator_metric_name": template.get("numerator_metric_name"),
                "denominator_metric_name": template.get("denominator_metric_name"),
                "aggregation": template["aggregation"],
                "range_aggregation_strategy": template["range_aggregation_strategy"],
                "share_scope": template["share_scope"],
                "rule_version": template["rule_version"],
                "quality_status": _roll_up_quality_status(rows),
                "quality_flags": _roll_up_quality_flags(rows),
                "created_at": max(item["created_at"] for item in rows if item["created_at"] is not None),
            }
        )
    return pl.DataFrame(rolled, schema=MART_METRIC_FACT_SCHEMA)


def _product_store_result_identity(row: dict[str, Any], request: DashboardMetricQueryRequest) -> tuple[str, str]:
    if request.grain_id == "network":
        return (request.entity_ids[0] if request.entity_ids else "network"), "{}"
    if request.grain_id == "category":
        return str(row["category"]), "{}"
    if request.grain_id == "manufacturer":
        return str(row["manufacturer"]), _json_parent_ids({"category": row.get("category")})
    if request.grain_id == "brand":
        return str(row["brand"]), _json_parent_ids({"category": row.get("category"), "manufacturer": row.get("manufacturer")})
    if request.grain_id == "sku":
        return str(row["canonical_product_id"]), _json_parent_ids(
            {"category": row.get("category"), "manufacturer": row.get("manufacturer"), "brand": row.get("brand")}
        )
    if request.grain_id == "store":
        return str(row["canonical_store_id"]), "{}"
    raise ValueError(f"Unsupported product-store rollup grain_id: {request.grain_id}")


def _json_parent_ids(values: dict[str, Any]) -> str:
    import json

    return json.dumps({key: value for key, value in values.items() if value is not None}, ensure_ascii=False, sort_keys=True)


def _rollup_provenance_status(scoped_rollup_grain: str | None, serving_fact_grain: str | None) -> str:
    if serving_fact_grain:
        return "DERIVED_FROM_PRODUCT_STORE_FACTS"
    if scoped_rollup_grain:
        return "DERIVED_FROM_FILTERED_FACTS"
    return "NOT_APPLICABLE"


def _scoped_rollup_limitations(frame: pl.DataFrame) -> tuple[QueryLimitation, ...]:
    if frame.is_empty():
        return ()
    limitations: list[QueryLimitation] = []
    for row in frame.to_dicts():
        strategy = RangeAggregationStrategy(str(row["range_aggregation_strategy"]))
        if strategy == RangeAggregationStrategy.SUM_AVAILABLE_PERIODS and row["value"] is None:
            limitations.append(
                QueryLimitation(
                    "scoped_rollup_additive_value_missing",
                    "Filtered aggregate requires non-null additive child values.",
                    metric_definition_id=str(row["metric_definition_id"]),
                    metric_concept=str(row["metric_concept"]),
                )
            )
        if strategy in {
            RangeAggregationStrategy.RATIO_OF_SUMS,
            RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
            RangeAggregationStrategy.RECOMPUTE_FROM_COMPONENTS,
        }:
            if row["numerator_value"] is None or row["denominator_value"] is None:
                limitations.append(
                    QueryLimitation(
                        "scoped_rollup_components_missing",
                        "Filtered aggregate requires numerator and denominator child values.",
                        metric_definition_id=str(row["metric_definition_id"]),
                        metric_concept=str(row["metric_concept"]),
                    )
                )
            elif _float_or_none(row["denominator_value"]) == 0:
                limitations.append(
                    QueryLimitation(
                        "scoped_rollup_zero_denominator",
                        "Filtered aggregate denominator is zero.",
                        metric_definition_id=str(row["metric_definition_id"]),
                        metric_concept=str(row["metric_concept"]),
                    )
                )
    return tuple(_dedupe_limitations(limitations))


def _roll_up_scoped_facts(frame: pl.DataFrame, request: DashboardMetricQueryRequest) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    rows = [row for row in frame.to_dicts() if row["metric_concept"] in SCOPED_ROLLUP_SAFE_CONCEPTS]
    if not rows:
        return pl.DataFrame(schema=MART_METRIC_FACT_SCHEMA)
    target_entity_id = request.entity_ids[0] if request.entity_ids else request.grain_id
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["retailer_id"],
            row["source_id"],
            row["source_revision_id"],
            row["analysis_run_id"],
            row["mart_build_id"],
            row.get("private_label_scope"),
            row["period_grain"],
            row["period_start"],
            row["period_end"],
            row["business_period_id"],
            row["metric_concept"],
            row["metric_name"],
            row["metric_definition_id"],
            row["metric_definition_version"],
            row["metric_config_hash"],
            row["semantic_family"],
            row["semantic_compatibility_version"],
            row["cross_retailer_comparable"],
            row["aggregation"],
            row["range_aggregation_strategy"],
            row["share_scope"],
            row["rule_version"],
        )
        grouped[key].append(row)

    rolled_rows: list[dict[str, Any]] = []
    for key, items in grouped.items():
        template = dict(items[0])
        template["grain_id"] = request.grain_id
        template["entity_id"] = target_entity_id
        template["parent_entity_ids"] = "{}"
        template["quality_status"] = _roll_up_quality_status(items)
        template["quality_flags"] = _roll_up_quality_flags(items)
        template["created_at"] = max(item["created_at"] for item in items if item["created_at"] is not None)
        template["value"], template["numerator_value"], template["denominator_value"] = _roll_up_metric_values(items)
        rolled_rows.append(template)
    return pl.DataFrame(rolled_rows, schema=MART_METRIC_FACT_SCHEMA)


def _roll_up_quality_status(rows: list[dict[str, Any]]) -> str:
    statuses = {str(row["quality_status"]) for row in rows}
    return "valid" if statuses == {"valid"} else "mixed"


def _roll_up_quality_flags(rows: list[dict[str, Any]]) -> str | None:
    flags = sorted(
        {
            flag.strip()
            for row in rows
            for flag in str(row["quality_flags"] or "").split(",")
            if flag.strip()
        }
    )
    return ",".join(flags) if flags else None


def _roll_up_metric_values(rows: list[dict[str, Any]]) -> tuple[float | None, float | None, float | None]:
    if len(rows) == 1:
        row = rows[0]
        return _float_or_none(row["value"]), _float_or_none(row["numerator_value"]), _float_or_none(row["denominator_value"])
    strategy = RangeAggregationStrategy(str(rows[0]["range_aggregation_strategy"]))
    if strategy == RangeAggregationStrategy.SUM_AVAILABLE_PERIODS:
        if any(row["value"] is None for row in rows):
            return None, None, None
        return sum(_float_or_zero(row["value"]) for row in rows), None, None
    if strategy in {
        RangeAggregationStrategy.RATIO_OF_SUMS,
        RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
        RangeAggregationStrategy.RECOMPUTE_FROM_COMPONENTS,
    }:
        if any(row["numerator_value"] is None or row["denominator_value"] is None for row in rows):
            return None, None, None
        numerator = sum(_float_or_zero(row["numerator_value"]) for row in rows)
        denominator = sum(_float_or_zero(row["denominator_value"]) for row in rows)
        return (None if denominator == 0 else numerator / denominator), numerator, denominator
    return None, None, None


def _filter_requested_periods(frame: pl.DataFrame, request: DashboardMetricQueryRequest) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET:
        return _filter_available_month_set_periods(frame, request)
    result = frame
    if request.date_from is not None:
        result = result.filter(pl.col("period_start") >= request.date_from)
    if request.date_to is not None:
        result = result.filter(pl.col("period_start") <= request.date_to)
    return result


def _filter_available_month_set_periods(frame: pl.DataFrame, request: DashboardMetricQueryRequest) -> pl.DataFrame:
    result = frame
    if request.date_from is not None:
        result = result.filter(pl.col("period_start") >= request.date_from)
    if request.date_to is not None:
        result = result.filter(pl.col("period_start") <= request.date_to)
    if request.comparison_mode != ComparisonMode.YOY:
        return result
    matched_months = _matched_yoy_month_numbers(frame, request)
    if not matched_months:
        return result.filter(pl.lit(False))
    return result.filter(pl.col("period_start").dt.month().is_in(matched_months))


def _expected_periods(request: DashboardMetricQueryRequest, frame: pl.DataFrame) -> tuple[date, ...]:
    if request.period_mode == PeriodMode.AVAILABLE_MONTH_SET:
        if frame.is_empty():
            return ()
        return tuple(sorted(set(frame.get_column("period_start").to_list())))
    if request.period_mode == PeriodMode.FULL_AVAILABLE_HISTORY:
        if frame.is_empty():
            return ()
        return tuple(sorted(set(frame.get_column("period_start").to_list())))
    if request.date_from is None or request.date_to is None:
        return ()
    if request.period_grain == "month":
        current = date(request.date_from.year, request.date_from.month, 1)
        end = date(request.date_to.year, request.date_to.month, 1)
        periods: list[date] = []
        while current <= end:
            periods.append(current)
            current = _add_months(current, 1)
        return tuple(periods)
    if request.period_grain == "day":
        days = (request.date_to - request.date_from).days
        return tuple(request.date_from.fromordinal(request.date_from.toordinal() + offset) for offset in range(days + 1))
    return ()


def _matched_yoy_month_numbers(frame: pl.DataFrame, request: DashboardMetricQueryRequest) -> tuple[int, ...]:
    if frame.is_empty() or request.date_from is None:
        return ()
    current = _available_periods_in_range(frame, request.date_from, request.date_to)
    reference_start = date(request.date_from.year - 1, 1, 1)
    reference_end = date(request.date_from.year - 1, 12, 31)
    reference = _available_periods_in_range(frame, reference_start, reference_end)
    current_months = {period.month for period in current}
    reference_months = {period.month for period in reference}
    return tuple(sorted(current_months & reference_months))


def _available_periods_in_range(frame: pl.DataFrame, start: date, end: date | None) -> tuple[date, ...]:
    scoped = frame.filter(pl.col("period_start") >= start)
    if end is not None:
        scoped = scoped.filter(pl.col("period_start") <= end)
    if scoped.is_empty():
        return ()
    return tuple(sorted(set(scoped.get_column("period_start").to_list())))


def _result_periods(results: tuple[MetricQueryResult, ...]) -> tuple[date, ...]:
    return tuple(sorted({period.period_start for result in results for period in result.period_values}))


def _reference_periods_for_matched_yoy(
    current_periods: tuple[date, ...],
    frame: pl.DataFrame,
) -> tuple[date, ...]:
    available = set(frame.get_column("period_start").to_list()) if not frame.is_empty() else set()
    return tuple(
        period
        for period in (date(current.year - 1, current.month, 1) for current in current_periods)
        if period in available
    )


def _result_comparison_identity(result: MetricQueryResult) -> tuple[Any, ...]:
    lineage = result.lineage
    return (
        result.grain_id,
        result.entity_id,
        result.metric_concept,
        lineage.metric_definition_id if lineage is not None else result.metric_name,
        lineage.metric_definition_version if lineage is not None else None,
        lineage.metric_config_hash if lineage is not None else None,
        lineage.rule_version if lineage is not None else None,
        result.private_label_scope,
    )


def _result_metric_definition_id(result: MetricQueryResult) -> str:
    if result.lineage is not None:
        return result.lineage.metric_definition_id
    return result.metric_name


def _period_set_payload(
    request: DashboardMetricQueryRequest,
    period_values: tuple[PeriodValue, ...],
) -> dict[str, Any] | None:
    if request.period_mode != PeriodMode.AVAILABLE_MONTH_SET:
        return None
    periods = tuple(sorted({period.period_start for period in period_values}))
    return {
        "scope_type": "AVAILABLE_MONTH_SET",
        "comparison_policy": "MATCHED_AVAILABLE_MONTHS"
        if request.comparison_mode == ComparisonMode.YOY
        else "ALL_AVAILABLE_MONTHS_PER_SIDE",
        "included_periods": periods,
        "included_month_numbers": tuple(period.month for period in periods),
        "included_month_labels": tuple(period.strftime("%b") for period in periods),
        "coverage_count": len(periods),
        "source_revision_ids": tuple(sorted({period.source_revision_id for period in period_values})),
    }


def _comparison_period_set_payload(
    request: DashboardMetricQueryRequest,
    comparisons: tuple[ComparisonResult, ...],
) -> dict[str, Any] | None:
    if request.period_mode != PeriodMode.AVAILABLE_MONTH_SET or not comparisons:
        return None
    current_periods = tuple(sorted({period for item in comparisons for period in item.current_included_periods}))
    comparison_periods = tuple(sorted({period for item in comparisons for period in item.comparison_included_periods}))
    return {
        "scope_type": "AVAILABLE_MONTH_SET_COMPARISON",
        "comparison_policy": comparisons[0].comparison_policy,
        "current_included_periods": current_periods,
        "comparison_included_periods": comparison_periods,
        "current_month_numbers": tuple(period.month for period in current_periods),
        "comparison_month_numbers": tuple(period.month for period in comparison_periods),
        "current_coverage_count": len(current_periods),
        "comparison_coverage_count": len(comparison_periods),
    }


def _available_month_aggregation_method(
    request: DashboardMetricQueryRequest,
    strategy: RangeAggregationStrategy,
) -> str | None:
    if request.period_mode != PeriodMode.AVAILABLE_MONTH_SET:
        return None
    if strategy == RangeAggregationStrategy.SUM_AVAILABLE_PERIODS:
        return "ARITHMETIC_MEAN_OF_MONTHLY_TOTALS"
    if strategy in {
        RangeAggregationStrategy.RATIO_OF_SUMS,
        RangeAggregationStrategy.WEIGHTED_RATIO_OF_SUMS,
        RangeAggregationStrategy.RECOMPUTE_FROM_COMPONENTS,
        RangeAggregationStrategy.RECOMPUTE_SHARE_SCOPE,
    }:
        return "RECOMPUTE_FROM_AVAILABLE_MONTH_COMPONENTS"
    if strategy == RangeAggregationStrategy.PERIOD_ONLY:
        return "POINT_IN_TIME_ONLY_UNSUPPORTED_FOR_AVAILABLE_MONTH_SET"
    return "UNSUPPORTED"


def _coverage(
    requested_periods: tuple[date, ...],
    available_periods: tuple[date, ...],
) -> tuple[float | None, CoverageStatus]:
    if not requested_periods:
        return None, CoverageStatus.UNSUPPORTED
    ratio = len(set(available_periods)) / len(set(requested_periods))
    if ratio == 1:
        return ratio, CoverageStatus.COMPLETE
    if ratio == 0:
        return ratio, CoverageStatus.NONE
    return ratio, CoverageStatus.PARTIAL


def _result_coverage_limitations(
    rows: list[dict[str, Any]],
    requested_periods: tuple[date, ...],
) -> tuple[QueryLimitation, ...]:
    if not requested_periods:
        return ()
    row_periods = {row["period_start"] for row in rows}
    missing = [period for period in requested_periods if period not in row_periods]
    if not missing:
        return ()
    return (
        QueryLimitation(
            "metric_partial_coverage",
            "Metric result does not cover every requested period",
            metric_definition_id=str(rows[0]["metric_definition_id"]),
            metric_concept=str(rows[0]["metric_concept"]),
        ),
    )


def _comparison_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["retailer_id"],
        row["source_id"],
        row["mart_build_id"],
        row.get("private_label_scope"),
        row["grain_id"],
        row["entity_id"],
        row["parent_entity_ids"],
        row["metric_definition_id"],
        row["metric_definition_version"],
        row["metric_config_hash"],
        row["rule_version"],
    )


def _reject_source_revision_ambiguity(frame: pl.DataFrame) -> None:
    if frame.is_empty():
        return
    ambiguous = (
        frame.group_by(["retailer_id", "source_id", "business_period_id"])
        .agg(pl.col("source_revision_id").n_unique().alias("revision_count"))
        .filter(pl.col("revision_count") > 1)
    )
    if not ambiguous.is_empty():
        raise ValueError("Multiple source revisions contribute to the same business period")


def _reject_duplicate_fact_contributors(frame: pl.DataFrame) -> None:
    if frame.is_empty():
        return
    identity_columns = [
        "retailer_id",
        "source_id",
        "mart_build_id",
        "period_grain",
        "period_start",
        "period_end",
        "business_period_id",
        "grain_id",
        "entity_id",
        "parent_entity_ids",
        "metric_definition_id",
        "metric_definition_version",
        "metric_config_hash",
        "rule_version",
        "source_revision_id",
    ]
    if "private_label_scope" in frame.columns:
        identity_columns.insert(3, "private_label_scope")
    duplicates = frame.group_by(identity_columns).len().filter(pl.col("len") > 1)
    if not duplicates.is_empty():
        raise ValueError("Duplicate mart fact contributors detected for a query scope")


def _comparison_fetch_start(request: DashboardMetricQueryRequest) -> date | None:
    if request.comparison_mode == ComparisonMode.YOY and request.date_from is not None:
        return date(request.date_from.year - 1, request.date_from.month, request.date_from.day)
    if request.comparison_mode == ComparisonMode.MOM and request.date_from is not None:
        return _add_months(request.date_from, -1)
    if request.comparison_mode == ComparisonMode.PREVIOUS_AVAILABLE:
        return None
    return request.date_from


def _lineage(row: dict[str, Any]) -> MetricDefinitionLineage:
    return MetricDefinitionLineage(
        metric_definition_id=str(row["metric_definition_id"]),
        metric_definition_version=str(row["metric_definition_version"]),
        metric_config_hash=str(row["metric_config_hash"]),
        rule_version=str(row["rule_version"]),
        semantic_family=str(row["semantic_family"]) if row["semantic_family"] is not None else None,
        semantic_compatibility_version=str(row["semantic_compatibility_version"])
        if row["semantic_compatibility_version"] is not None
        else None,
        cross_retailer_comparable=bool(row["cross_retailer_comparable"]),
    )


def _period_value(row: dict[str, Any]) -> PeriodValue:
    return PeriodValue(
        period_start=row["period_start"],
        period_end=row["period_end"],
        business_period_id=str(row["business_period_id"]),
        value=_float_or_none(row["value"]),
        numerator_value=_float_or_none(row["numerator_value"]),
        denominator_value=_float_or_none(row["denominator_value"]),
        business_rule_id=str(row["business_rule_id"]) if row.get("business_rule_id") is not None else None,
        denominator_universe_type=str(row["denominator_universe_type"]) if row.get("denominator_universe_type") is not None else None,
        store_alias_mapping_version=str(row["store_alias_mapping_version"]) if row.get("store_alias_mapping_version") is not None else None,
        numerator_metric_name=str(row["numerator_metric_name"]) if row.get("numerator_metric_name") is not None else None,
        denominator_metric_name=str(row["denominator_metric_name"]) if row.get("denominator_metric_name") is not None else None,
        source_revision_id=str(row["source_revision_id"]),
        analysis_run_id=str(row["analysis_run_id"]),
        quality_status=str(row["quality_status"]),
        quality_flags=str(row["quality_flags"]) if row["quality_flags"] is not None else None,
    )


def _quality_flags(frame: pl.DataFrame) -> tuple[str, ...]:
    if frame.is_empty() or "quality_flags" not in frame.columns:
        return ()
    return tuple(sorted(str(value) for value in frame["quality_flags"].drop_nulls().unique().to_list()))


def _add_in_filter(clauses: list[str], params: list[Any], column: str, values: tuple[str, ...]) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    clauses.append(f"{column} IN ({placeholders})")
    params.extend(values)


def _add_json_parent_filter(clauses: list[str], params: list[Any], key: str, values: tuple[str, ...]) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    json_key = PARENT_ENTITY_JSON_KEYS.get(key, key)
    clauses.append(f"json_extract_string(parent_entity_ids, '$.{json_key}') IN ({placeholders})")
    params.extend(values)


def _dedupe_limitations(limitations: list[QueryLimitation]) -> tuple[QueryLimitation, ...]:
    seen: set[tuple[str, str | None, str | None]] = set()
    result: list[QueryLimitation] = []
    for item in limitations:
        key = (item.issue_code, item.metric_definition_id, item.metric_concept)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def _duckdb_path(path: Path) -> str:
    raw = path.as_posix()
    if path.is_dir():
        raw = f"{raw}/**/*.parquet"
    return raw


def _duckdb_columns(path: Path) -> set[str]:
    rows = duckdb.sql("DESCRIBE SELECT * FROM read_parquet(?) LIMIT 0", params=[_duckdb_path(path)]).fetchall()
    return {str(row[0]) for row in rows}


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _float_or_zero(value: Any) -> float:
    return 0.0 if value is None else float(value)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _period_gap(left: date, right: date, period_grain: str) -> int:
    if period_grain == "month":
        return (right.year - left.year) * 12 + right.month - left.month
    return (right - left).days
