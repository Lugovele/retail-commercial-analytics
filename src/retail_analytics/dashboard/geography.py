"""Store geography and format projections for the Stores screen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from retail_analytics.history import SourceLedgerEntry
from retail_analytics.mart import MartBuildMetadata, PrivateLabelScope

SUPPORTED_GROUPINGS = frozenset({"region", "store_format", "region_store_format"})
SUPPORTED_METRICS = ("revenue", "revenue_vat", "units", "retailer_margin_abs", "retailer_margin_pct")
_FILTER_COLUMNS = {
    "category": "category",
    "manufacturer": "manufacturer",
    "brand": "brand",
    "package": "package",
    "volume": "volume_l",
    "sku": "canonical_product_id",
    "store": "canonical_store_id",
}


@dataclass(frozen=True)
class GeographyQueryRequest:
    """UI request for approved additive geography/store-format grouping."""

    retailer_id: str
    source_id: str
    period_mode: str
    period_grain: str
    grouping: str
    metric_concepts: tuple[str, ...]
    date_from: date | None = None
    date_to: date | None = None
    entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: str = "NONE"
    comparison_period_start: date | None = None
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None


class GeographyQueryService:
    """Aggregate approved additive metrics by region and store format."""

    def __init__(
        self,
        product_store_facts_path: str | Path | None,
        *,
        mart_builds: tuple[MartBuildMetadata, ...] = (),
        source_ledger: tuple[SourceLedgerEntry, ...] = (),
    ) -> None:
        self.product_store_facts_path = Path(product_store_facts_path) if product_store_facts_path is not None else None
        self.mart_builds = mart_builds
        self.source_ledger = source_ledger

    def query(self, request: GeographyQueryRequest) -> dict[str, Any]:
        """Return grouped geography metrics without introducing new formulas."""

        if request.grouping not in SUPPORTED_GROUPINGS:
            raise ValueError(f"Unsupported geography grouping: {request.grouping}")
        unsupported_filters = sorted(set(request.entity_filters or ()) - set(_FILTER_COLUMNS))
        if unsupported_filters:
            raise ValueError(f"Unsupported geography filter column: {', '.join(unsupported_filters)}")
        build = self._resolve_build(request)
        limitations: list[dict[str, Any]] = []
        if self.product_store_facts_path is None or not self.product_store_facts_path.exists():
            return self._empty_response(request, build, "geography_product_store_facts_missing")

        requested = tuple(concept for concept in request.metric_concepts if concept in SUPPORTED_METRICS)
        limitations.extend(
            {
                "issue_code": "geography_metric_unsupported",
                "message": "Geography grouping supports only approved additive metrics and margin ratio-of-sums.",
                "metric_concept": concept,
            }
            for concept in request.metric_concepts
            if concept not in SUPPORTED_METRICS
        )
        if not requested:
            return self._empty_response(request, build, "geography_no_supported_metrics", limitations=tuple(limitations))

        current_periods = self._current_periods(request, build)
        reference_periods = self._reference_periods(request, build, current_periods)
        current_rows = self._aggregate(request, build, current_periods, requested)
        reference_rows = self._aggregate(request, build, reference_periods, requested) if reference_periods else {}
        metric_results = _metric_results(request, build, current_rows, current_periods, requested)
        comparisons = _comparisons(request, current_rows, reference_rows, current_periods, reference_periods, requested)
        return {
            "request_scope": {
                "retailer_id": request.retailer_id,
                "source_id": request.source_id,
                "period_mode": request.period_mode,
                "period_grain": request.period_grain,
                "grouping": request.grouping,
                "metric_concepts": requested,
                "entity_filters": request.entity_filters or {},
                "comparison_mode": request.comparison_mode,
                "comparison_period_start": request.comparison_period_start.isoformat() if request.comparison_period_start else None,
                "private_label_scope": request.private_label_scope.value,
                "mart_build_id": build.mart_build_id,
            },
            "grouping": request.grouping,
            "available_periods": [period.isoformat() for period in current_periods],
            "reference_periods": [period.isoformat() for period in reference_periods],
            "metric_results": metric_results,
            "comparisons": comparisons,
            "limitations": limitations,
            "mart_build_id": build.mart_build_id,
            "source_revision_ids": list(build.source_revision_ids),
            "private_label_scope": request.private_label_scope.value,
        }

    def _resolve_build(self, request: GeographyQueryRequest) -> MartBuildMetadata:
        candidates = [
            build
            for build in self.mart_builds
            if build.retailer_id == request.retailer_id
            and request.source_id in build.source_ids
            and (request.mart_build_id is None or build.mart_build_id == request.mart_build_id)
        ]
        if not candidates:
            raise ValueError("No mart build matches geography request")
        approved = [build for build in candidates if build.status == "approved"]
        selected = approved or candidates
        if request.mart_build_id:
            return selected[0]
        return max(selected, key=lambda build: build.built_at)

    def _current_periods(self, request: GeographyQueryRequest, build: MartBuildMetadata) -> tuple[date, ...]:
        periods = self._available_periods(request, build, request.date_from, request.date_to)
        if request.period_mode == "SINGLE_PERIOD":
            return tuple(period for period in periods if request.date_from is None or period == request.date_from)
        if request.period_mode in {"DATE_RANGE", "AVAILABLE_MONTH_SET"}:
            if request.period_mode == "AVAILABLE_MONTH_SET" and request.comparison_mode in {"YOY", "CUSTOM"}:
                matched_months = self._matched_month_numbers(request, build)
                return tuple(period for period in periods if period.month in matched_months)
            return periods
        return ()

    def _reference_periods(
        self,
        request: GeographyQueryRequest,
        build: MartBuildMetadata,
        current_periods: tuple[date, ...],
    ) -> tuple[date, ...]:
        if request.comparison_mode == "NONE" or not current_periods:
            return ()
        if request.comparison_mode == "CUSTOM" and request.period_mode != "AVAILABLE_MONTH_SET":
            if request.comparison_period_start is None:
                return ()
            available_reference_periods = set(
                self._available_periods(
                    request,
                    build,
                    request.comparison_period_start,
                    request.comparison_period_start,
                )
            )
            return (request.comparison_period_start,) if request.comparison_period_start in available_reference_periods else ()
        if request.comparison_mode in {"YOY", "CUSTOM"}:
            reference_year = request.comparison_period_start.year if request.comparison_period_start is not None else min(current_periods).year - 1
            candidates = tuple(date(reference_year, period.month, 1) for period in current_periods)
            available_reference_periods = set(
                self._available_periods(request, build, date(min(candidates).year, 1, 1), date(max(candidates).year, 12, 31))
            )
            return tuple(period for period in candidates if period in available_reference_periods)
        if request.comparison_mode == "PREVIOUS_AVAILABLE":
            available_periods = self._available_periods(request, build, None, request.date_from)
            previous = tuple(period for period in available_periods if request.date_from is None or period < request.date_from)
            return previous[-1:] if previous else ()
        return ()

    def _available_periods(
        self,
        request: GeographyQueryRequest,
        build: MartBuildMetadata,
        start: date | None,
        end: date | None,
    ) -> tuple[date, ...]:
        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "mart_build_id = ?",
            "period_grain = ?",
            "private_label_scope = ?",
        ]
        params: list[Any] = [
            request.retailer_id,
            request.source_id,
            build.mart_build_id,
            request.period_grain,
            request.private_label_scope.value,
        ]
        if start is not None:
            clauses.append("period_start >= CAST(? AS DATE)")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("period_start <= CAST(? AS DATE)")
            params.append(end.isoformat())
        rows = duckdb.sql(
            f"""
                SELECT DISTINCT period_start
                FROM read_parquet(?)
                WHERE {" AND ".join(clauses)}
                ORDER BY period_start
            """,
            params=[_duckdb_path(self.product_store_facts_path), *params],
        ).fetchall()
        return tuple(row[0] for row in rows)

    def _matched_month_numbers(self, request: GeographyQueryRequest, build: MartBuildMetadata) -> tuple[int, ...]:
        current = self._available_periods(request, build, request.date_from, request.date_to)
        if request.date_from is None:
            return ()
        reference_year = request.comparison_period_start.year if request.comparison_period_start is not None else request.date_from.year - 1
        reference = self._available_periods(request, build, date(reference_year, 1, 1), date(reference_year, 12, 31))
        return tuple(sorted({period.month for period in current} & {period.month for period in reference}))

    def _aggregate(
        self,
        request: GeographyQueryRequest,
        build: MartBuildMetadata,
        periods: tuple[date, ...],
        metric_concepts: tuple[str, ...],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        if not periods:
            return {}
        dimension_columns = _dimension_columns(request.grouping)
        clauses = [
            "retailer_id = ?",
            "source_id = ?",
            "mart_build_id = ?",
            "period_grain = ?",
            "private_label_scope = ?",
        ]
        params: list[Any] = [
            request.retailer_id,
            request.source_id,
            build.mart_build_id,
            request.period_grain,
            request.private_label_scope.value,
        ]
        placeholders = ", ".join("?" for _ in periods)
        clauses.append(f"period_start IN ({placeholders})")
        params.extend(period.isoformat() for period in periods)
        _add_scope_filters(clauses, params, request.entity_filters or {})
        requested_base_metrics = [concept for concept in metric_concepts if concept != "retailer_margin_pct"]
        if "retailer_margin_pct" in metric_concepts:
            requested_base_metrics.extend(["revenue", "retailer_margin_abs"])
        requested_base_metrics = sorted(set(requested_base_metrics) & {"revenue", "revenue_vat", "units", "retailer_margin_abs"})
        metric_placeholders = ", ".join("?" for _ in requested_base_metrics)
        sql = f"""
            SELECT
                {", ".join(dimension_columns)},
                metric_concept,
                SUM(value) AS value,
                SUM(numerator_value) AS numerator_value,
                SUM(denominator_value) AS denominator_value,
                COUNT(DISTINCT canonical_store_id) AS store_count,
                MIN(metric_name) AS metric_name,
                MIN(metric_definition_id) AS metric_definition_id,
                MIN(metric_definition_version) AS metric_definition_version,
                MIN(metric_config_hash) AS metric_config_hash,
                MIN(rule_version) AS rule_version,
                MIN(semantic_family) AS semantic_family,
                MIN(semantic_compatibility_version) AS semantic_compatibility_version,
                MIN(cross_retailer_comparable) AS cross_retailer_comparable,
                MIN(source_revision_id) AS source_revision_id,
                MIN(analysis_run_id) AS analysis_run_id
            FROM read_parquet(?)
            WHERE {" AND ".join(clauses)}
              AND metric_concept IN ({metric_placeholders})
              AND {" AND ".join(f"{column} IS NOT NULL AND {column} <> ''" for column in dimension_columns)}
            GROUP BY {", ".join(dimension_columns)}, metric_concept
            ORDER BY {", ".join(dimension_columns)}, metric_concept
        """
        rows = duckdb.sql(sql, params=[_duckdb_path(self.product_store_facts_path), *params, *requested_base_metrics]).fetchall()
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            dims = tuple(str(row[index]) for index in range(len(dimension_columns)))
            entity_id = _entity_id(request.grouping, dims)
            key_base = (entity_id, "")
            bucket = result.setdefault(
                key_base,
                {
                    "entity_id": entity_id,
                    "label": _entity_label(request.grouping, dims),
                    "dimension_values": dict(zip(dimension_columns, dims, strict=True)),
                    "store_count": int(row[len(dimension_columns) + 4] or 0),
                    "metrics": {},
                    "lineage": {},
                },
            )
            metric = str(row[len(dimension_columns)])
            value = float(row[len(dimension_columns) + 1] or 0.0)
            bucket["metrics"][metric] = value
            bucket["lineage"][metric] = _lineage_payload(row, len(dimension_columns))
        for bucket in result.values():
            revenue = bucket["metrics"].get("revenue")
            margin = bucket["metrics"].get("retailer_margin_abs")
            if "retailer_margin_pct" in metric_concepts:
                bucket["metrics"]["retailer_margin_pct"] = None if not revenue else (margin or 0.0) / revenue
                bucket["lineage"]["retailer_margin_pct"] = bucket["lineage"].get("retailer_margin_abs") or bucket["lineage"].get("revenue")
        return result

    def _empty_response(
        self,
        request: GeographyQueryRequest,
        build: MartBuildMetadata,
        code: str,
        *,
        limitations: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        return {
            "request_scope": {
                "retailer_id": request.retailer_id,
                "source_id": request.source_id,
                "period_mode": request.period_mode,
                "period_grain": request.period_grain,
                "grouping": request.grouping,
                "entity_filters": request.entity_filters or {},
                "comparison_mode": request.comparison_mode,
                "private_label_scope": request.private_label_scope.value,
                "mart_build_id": build.mart_build_id,
            },
            "grouping": request.grouping,
            "available_periods": [],
            "reference_periods": [],
            "metric_results": [],
            "comparisons": [],
            "limitations": [
                {
                    "issue_code": code,
                    "message": "Geography additive grouping is unavailable for the selected runtime scope.",
                },
                *limitations,
            ],
            "mart_build_id": build.mart_build_id,
            "source_revision_ids": list(build.source_revision_ids),
            "private_label_scope": request.private_label_scope.value,
        }


def build_geography_request(payload: GeographyQueryRequest | dict[str, Any]) -> GeographyQueryRequest:
    """Build a geography query request from UI payload."""

    if isinstance(payload, GeographyQueryRequest):
        return payload
    raw_filters = payload.get("entity_filters")
    filters = (
        {str(key): tuple(str(item) for item in values) for key, values in raw_filters.items()}
        if isinstance(raw_filters, dict)
        else None
    )
    return GeographyQueryRequest(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        date_from=_date_or_none(payload.get("date_from")),
        date_to=_date_or_none(payload.get("date_to")),
        period_mode=str(payload.get("period_mode", "SINGLE_PERIOD")),
        period_grain=str(payload.get("period_grain", "month")),
        grouping=str(payload.get("grouping", "region")),
        metric_concepts=tuple(str(item) for item in payload.get("metric_concepts", SUPPORTED_METRICS)),
        entity_filters=filters,
        comparison_mode=str(payload.get("comparison_mode", "NONE")),
        comparison_period_start=_date_or_none(payload.get("comparison_period_start")),
        private_label_scope=PrivateLabelScope(payload.get("private_label_scope", PrivateLabelScope.INCLUDE)),
        mart_build_id=payload.get("mart_build_id"),
    )


def _metric_results(
    request: GeographyQueryRequest,
    build: MartBuildMetadata,
    current_rows: dict[tuple[str, str], dict[str, Any]],
    current_periods: tuple[date, ...],
    requested: tuple[str, ...],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in current_rows.values():
        for concept in requested:
            if concept not in row["metrics"]:
                continue
            value = row["metrics"][concept]
            lineage = dict(row["lineage"].get(concept) or {})
            if concept == "retailer_margin_pct":
                lineage["metric_name"] = concept
                lineage["metric_definition_id"] = concept
                lineage["numerator_value"] = row["metrics"].get("retailer_margin_abs")
                lineage["denominator_value"] = row["metrics"].get("revenue")
            results.append(
                {
                    "metric_concept": concept,
                    "metric_name": lineage.get("metric_name") or concept,
                    "grain_id": request.grouping,
                    "entity_id": row["entity_id"],
                    "label": row["label"],
                    "dimension_values": row["dimension_values"],
                    "store_count": row["store_count"],
                    "value": value,
                    "numerator_value": lineage.get("numerator_value"),
                    "denominator_value": lineage.get("denominator_value"),
                    "range_aggregation_strategy": "ratio_of_sums" if concept == "retailer_margin_pct" else "sum_available_periods",
                    "share_scope": request.grouping,
                    "period_values": [],
                    "lineage": lineage,
                    "limitations": [],
                    "private_label_scope": request.private_label_scope.value,
                    "provenance": _provenance(request, build, row, concept, lineage, current_periods),
                }
            )
    return results


def _comparisons(
    request: GeographyQueryRequest,
    current_rows: dict[tuple[str, str], dict[str, Any]],
    reference_rows: dict[tuple[str, str], dict[str, Any]],
    current_periods: tuple[date, ...],
    reference_periods: tuple[date, ...],
    requested: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not reference_rows:
        return []
    comparisons: list[dict[str, Any]] = []
    for row in current_rows.values():
        reference = reference_rows.get((row["entity_id"], ""))
        if reference is None:
            continue
        for concept in requested:
            current_value = row["metrics"].get(concept)
            comparison_value = reference["metrics"].get(concept)
            if current_value is None or comparison_value is None:
                delta = None
                pct_delta = None
            else:
                delta = current_value - comparison_value
                pct_delta = None if comparison_value == 0 else delta / abs(comparison_value)
            comparisons.append(
                {
                    "comparison_mode": request.comparison_mode,
                    "metric_definition_id": concept
                    if concept == "retailer_margin_pct"
                    else row["lineage"].get(concept, {}).get("metric_definition_id") or concept,
                    "entity_id": row["entity_id"],
                    "current_period_start": current_periods[-1].isoformat() if current_periods else None,
                    "comparison_period_start": reference_periods[-1].isoformat() if reference_periods else None,
                    "current_value": current_value,
                    "comparison_value": comparison_value,
                    "delta": delta,
                    "pct_delta": pct_delta,
                    "quality_status": "valid",
                    "gap_periods": [],
                    "private_label_scope": request.private_label_scope.value,
                    "current_included_periods": [period.isoformat() for period in current_periods],
                    "comparison_included_periods": [period.isoformat() for period in reference_periods],
                    "aggregation_method": "ratio_of_sums" if concept == "retailer_margin_pct" else "sum_available_periods",
                    "comparison_policy": "MATCHED_AVAILABLE_MONTHS"
                    if request.period_mode == "AVAILABLE_MONTH_SET"
                    else request.comparison_mode,
                }
            )
    return comparisons


def _provenance(
    request: GeographyQueryRequest,
    build: MartBuildMetadata,
    row: dict[str, Any],
    concept: str,
    lineage: dict[str, Any],
    current_periods: tuple[date, ...],
) -> dict[str, Any]:
    aggregation_method = "ratio_of_sums" if concept == "retailer_margin_pct" else "sum_available_periods"
    return {
        "metric": {
            "metric_concept": concept,
            "metric_definition_id": lineage.get("metric_definition_id") or concept,
            "metric_definition_version": lineage.get("metric_definition_version"),
            "metric_config_hash": lineage.get("metric_config_hash"),
        },
        "value": {
            "value": row["metrics"].get(concept),
            "numerator_value": lineage.get("numerator_value"),
            "denominator_value": lineage.get("denominator_value"),
            "range_aggregation_strategy": aggregation_method,
            "available_month_aggregation_method": aggregation_method
            if request.period_mode == "AVAILABLE_MONTH_SET"
            else None,
        },
        "current_analytical_scope": {
            "retailer_id": request.retailer_id,
            "source_id": request.source_id,
            "grain_id": request.grouping,
            "entity_id": row["entity_id"],
            "dimension_type": request.grouping,
            "dimension_values": row["dimension_values"],
            "entity_filters": request.entity_filters or {},
            "requested_periods": [period.isoformat() for period in current_periods],
            "available_periods": [period.isoformat() for period in current_periods],
            "missing_periods": [],
            "period_set": {
                "scope_type": request.period_mode,
                "included_periods": [period.isoformat() for period in current_periods],
                "coverage_count": len(current_periods),
            }
            if request.period_mode == "AVAILABLE_MONTH_SET"
            else {},
            "period_mode": request.period_mode,
            "comparison_mode": request.comparison_mode,
            "private_label_scope": request.private_label_scope.value,
        },
        "calculation": {
            "metric_concept": concept,
            "aggregation_method": aggregation_method,
            "formula_summary": "ratio of summed margin to summed revenue" if concept == "retailer_margin_pct" else "sum of additive metric values",
        },
        "run_lineage": {
            "mart_build_id": build.mart_build_id,
            "source_revision_ids": list(build.source_revision_ids),
            "analysis_run_ids": list(build.analysis_run_ids),
        },
        "lineage": {
            "mart_build_id": build.mart_build_id,
            "source_revision_ids": build.source_revision_ids,
            "metric_definition_id": lineage.get("metric_definition_id") or concept,
            "metric_definition_version": lineage.get("metric_definition_version"),
            "metric_config_hash": lineage.get("metric_config_hash"),
            "rule_version": lineage.get("rule_version"),
        },
        "source_evidence": {
            "status": "DERIVED_FROM_PRODUCT_STORE_FACTS",
            "source_revision_id": lineage.get("source_revision_id"),
            "analysis_run_id": lineage.get("analysis_run_id"),
        },
        "quality": {
            "quality_statuses": ["VALID"],
            "result_limitations": [],
        },
        "guardrails": {
            "fo2_exposed": False,
            "territory_exposed": False,
            "distribution_exposed": False,
        },
    }


def _dimension_columns(grouping: str) -> tuple[str, ...]:
    if grouping == "region":
        return ("region",)
    if grouping == "store_format":
        return ("store_format",)
    if grouping == "region_store_format":
        return ("region", "store_format")
    raise ValueError(f"Unsupported geography grouping: {grouping}")


def _entity_id(grouping: str, dims: tuple[str, ...]) -> str:
    if grouping == "region_store_format":
        return " | ".join(dims)
    return dims[0]


def _entity_label(grouping: str, dims: tuple[str, ...]) -> str:
    if grouping == "region_store_format":
        return " · ".join(dims)
    return dims[0]


def _lineage_payload(row: tuple[Any, ...], dimension_count: int) -> dict[str, Any]:
    base = dimension_count
    return {
        "metric_name": row[base + 5],
        "metric_definition_id": row[base + 6],
        "metric_definition_version": row[base + 7],
        "metric_config_hash": row[base + 8],
        "rule_version": row[base + 9],
        "semantic_family": row[base + 10],
        "semantic_compatibility_version": row[base + 11],
        "cross_retailer_comparable": row[base + 12],
        "source_revision_id": row[base + 13],
        "analysis_run_id": row[base + 14],
        "numerator_value": row[base + 2],
        "denominator_value": row[base + 3],
    }


def _add_scope_filters(clauses: list[str], params: list[Any], filters: dict[str, tuple[str, ...]]) -> None:
    for key, values in filters.items():
        column = _FILTER_COLUMNS.get(key)
        if column is None or not values:
            continue
        placeholders = ", ".join("?" for _ in values)
        if key == "volume":
            clauses.append(f"ROUND(CAST({column} AS DOUBLE), 6) IN ({placeholders})")
            params.extend(float(str(value)) for value in values)
        else:
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(values)


def _date_or_none(value: date | str | None) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _duckdb_path(path: Path | None) -> str:
    if path is None:
        return ""
    raw = path.as_posix()
    if path.is_dir():
        raw = f"{raw}/**/*.parquet"
    return raw
