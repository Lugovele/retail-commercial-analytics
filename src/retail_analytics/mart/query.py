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
from retail_analytics.mart.scopes import PrivateLabelScope, scope_identity_hash

FILTER_GRAIN_ORDER = ("category", "manufacturer", "brand", "sku", "store")
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
    ) -> None:
        self.metric_facts_path = Path(metric_facts_path)
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
        if _has_product_store_intersection(request):
            raw = pl.DataFrame()
            limitations.append(
                QueryLimitation(
                    "product_store_filter_intersection_not_materialized",
                    "Product and store filters require a materialized product-store analytical scope.",
                )
            )
        else:
            raw = self._read_facts(request, mart_build_id=mart_build_id, period_start=fetch_start)
        if raw.is_empty() and request.entity_filters and not _has_product_store_intersection(request):
            raw, scoped_rollup_grain, rollup_limitations = self._read_scoped_rollup_facts(
                request,
                mart_build_id=mart_build_id,
                period_start=fetch_start,
            )
            limitations.extend(rollup_limitations)
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
            validation_grain = scoped_rollup_grain or request.grain_id
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
        return sum(_float_or_zero(row["value"]) for row in rows), None, None, tuple(result_limitations)
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
        "periods": tuple(
            {
                "current_period_start": item.current_period_start,
                "comparison_period_start": item.comparison_period_start,
                "gap_periods": item.gap_periods,
            }
            for item in result_comparisons
        ),
    }
    missing_fields = list(_lineage_missing_fields(lineage))
    if not result_comparisons and request.comparison_mode != ComparisonMode.NONE:
        missing_fields.extend(("comparison_periods", "comparison_quality"))
    if lineage is None or not lineage.rule_version:
        missing_fields.append("business_rule_version")
    missing_fields.extend(("business_rule_id", "source_row_ids"))

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
            "business_rule_id": None,
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
        },
        "scoped_rollup": {
            "status": "DERIVED_FROM_FILTERED_FACTS" if scoped_rollup_grain else "NOT_APPLICABLE",
            "source_fact_grain": scoped_rollup_grain,
            "requested_grain": request.grain_id,
            "entity_filters": request.entity_filters or {},
            "formula": "sum child values or recompute ratio from child numerators and denominators"
            if scoped_rollup_grain
            else None,
            "rolled_period_count": len(result.period_values),
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
    product_scope_filtered = any(selected.get(key) for key in ("category", "manufacturer", "brand", "sku"))
    return bool(selected.get("store")) and (product_scope_requested or product_scope_filtered)


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
    result = frame
    if request.date_from is not None:
        result = result.filter(pl.col("period_start") >= request.date_from)
    if request.date_to is not None:
        result = result.filter(pl.col("period_start") <= request.date_to)
    return result


def _expected_periods(request: DashboardMetricQueryRequest, frame: pl.DataFrame) -> tuple[date, ...]:
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
