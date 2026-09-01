"""Package and exact-volume mix projections for Portfolio and Market."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from retail_analytics.history import SourceLedgerEntry
from retail_analytics.mart import MartBuildMetadata, PrivateLabelScope

SUPPORTED_GROUPINGS = frozenset({"package", "volume", "package_volume"})
VOLUME_FILTER_DECIMALS = 6
SUPPORTED_METRICS = ("revenue", "revenue_vat", "units", "retailer_margin_abs", "retailer_margin_pct")
SUPPORTED_BASIS_METRICS = frozenset({"revenue", "units", "retailer_margin_abs"})
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
class PackageVolumeQueryRequest:
    """UI request for approved package/exact-volume portfolio mix analytics."""

    retailer_id: str
    source_id: str
    period_mode: str
    period_grain: str
    grouping: str
    basis_metric: str
    metric_concepts: tuple[str, ...]
    date_from: date | None = None
    date_to: date | None = None
    entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: str = "NONE"
    comparison_period_start: date | None = None
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None


class PackageVolumeQueryService:
    """Aggregate existing product-store facts by canonical package and exact volume."""

    def __init__(
        self,
        source_like_rows_path: str | Path | None,
        product_store_facts_path: str | Path | None,
        *,
        mart_builds: tuple[MartBuildMetadata, ...] = (),
        source_ledger: tuple[SourceLedgerEntry, ...] = (),
    ) -> None:
        self.source_like_rows_path = Path(source_like_rows_path) if source_like_rows_path is not None else None
        self.product_store_facts_path = Path(product_store_facts_path) if product_store_facts_path is not None else None
        self.mart_builds = mart_builds
        self.source_ledger = source_ledger

    def query(self, request: PackageVolumeQueryRequest) -> dict[str, Any]:
        """Return package/volume mix rows with backend-computed shares and provenance."""

        if request.grouping not in SUPPORTED_GROUPINGS:
            raise ValueError(f"Unsupported package/volume grouping: {request.grouping}")
        if request.basis_metric not in SUPPORTED_BASIS_METRICS:
            raise ValueError(f"Unsupported package/volume basis metric: {request.basis_metric}")
        unsupported_filters = sorted(set(request.entity_filters or ()) - set(_FILTER_COLUMNS))
        if unsupported_filters:
            raise ValueError(f"Unsupported package/volume filter column: {', '.join(unsupported_filters)}")
        build = self._resolve_build(request)
        limitations: list[dict[str, Any]] = []
        if self.product_store_facts_path is None or not self.product_store_facts_path.exists():
            return self._empty_response(request, build, "package_volume_product_store_facts_missing")
        if self.source_like_rows_path is None or not self.source_like_rows_path.exists():
            return self._empty_response(request, build, "package_volume_source_attributes_missing")

        requested = tuple(concept for concept in request.metric_concepts if concept in SUPPORTED_METRICS)
        limitations.extend(
            {
                "issue_code": "package_volume_metric_unsupported",
                "message": "Package/volume mix supports only approved additive metrics and margin ratio-of-sums.",
                "metric_concept": concept,
            }
            for concept in request.metric_concepts
            if concept not in SUPPORTED_METRICS
        )
        if not requested:
            return self._empty_response(request, build, "package_volume_no_supported_metrics", limitations=tuple(limitations))

        current_periods = self._current_periods(request, build)
        reference_periods = self._reference_periods(request, build, current_periods)
        current_rows = self._aggregate(request, build, current_periods, requested)
        reference_rows = self._aggregate(request, build, reference_periods, requested) if reference_periods else {}
        rows = _mix_rows(request, build, current_rows, reference_rows, current_periods, reference_periods, requested)
        rows.sort(key=lambda row: _sort_key(request, row))
        return {
            "request_scope": {
                "retailer_id": request.retailer_id,
                "source_id": request.source_id,
                "period_mode": request.period_mode,
                "period_grain": request.period_grain,
                "grouping": request.grouping,
                "basis_metric": request.basis_metric,
                "metric_concepts": requested,
                "entity_filters": request.entity_filters or {},
                "comparison_mode": request.comparison_mode,
                "comparison_period_start": request.comparison_period_start.isoformat() if request.comparison_period_start else None,
                "private_label_scope": request.private_label_scope.value,
                "mart_build_id": build.mart_build_id,
            },
            "grouping": request.grouping,
            "basis_metric": request.basis_metric,
            "available_periods": [period.isoformat() for period in current_periods],
            "reference_periods": [period.isoformat() for period in reference_periods],
            "rows": rows,
            "limitations": limitations,
            "mart_build_id": build.mart_build_id,
            "source_revision_ids": list(build.source_revision_ids),
            "private_label_scope": request.private_label_scope.value,
        }

    def _resolve_build(self, request: PackageVolumeQueryRequest) -> MartBuildMetadata:
        candidates = [
            build
            for build in self.mart_builds
            if build.retailer_id == request.retailer_id
            and request.source_id in build.source_ids
            and (request.mart_build_id is None or build.mart_build_id == request.mart_build_id)
        ]
        if not candidates:
            raise ValueError("No mart build matches package/volume request")
        approved = [build for build in candidates if build.status == "approved"]
        selected = approved or candidates
        if request.mart_build_id:
            return selected[0]
        return max(selected, key=lambda build: build.built_at)

    def _current_periods(self, request: PackageVolumeQueryRequest, build: MartBuildMetadata) -> tuple[date, ...]:
        periods = self._available_periods(request, build, request.date_from, request.date_to)
        if request.period_mode == "SINGLE_PERIOD":
            return tuple(period for period in periods if request.date_from is None or period == request.date_from)
        if request.period_mode in {"DATE_RANGE", "AVAILABLE_MONTH_SET"}:
            if request.period_mode == "AVAILABLE_MONTH_SET" and request.comparison_mode in {"YOY", "CUSTOM"}:
                matched_months = self._matched_month_numbers(request, build)
                return tuple(period for period in periods if period.month in matched_months)
            return periods
        if request.period_mode == "COMPARE":
            return tuple(period for period in periods if request.date_from is None or period == request.date_from)
        return ()

    def _reference_periods(
        self,
        request: PackageVolumeQueryRequest,
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
        request: PackageVolumeQueryRequest,
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
        _add_scope_filters(clauses, params, request.entity_filters or {}, "f")
        rows = duckdb.sql(
            f"""
                SELECT DISTINCT period_start
                FROM read_parquet(?) AS f
                WHERE {" AND ".join(clauses)}
                ORDER BY period_start
            """,
            params=[_duckdb_path(self.product_store_facts_path), *params],
        ).fetchall()
        return tuple(row[0] for row in rows)

    def _matched_month_numbers(self, request: PackageVolumeQueryRequest, build: MartBuildMetadata) -> tuple[int, ...]:
        current = self._available_periods(request, build, request.date_from, request.date_to)
        if request.date_from is None:
            return ()
        reference_year = request.comparison_period_start.year if request.comparison_period_start is not None else request.date_from.year - 1
        reference = self._available_periods(request, build, date(reference_year, 1, 1), date(reference_year, 12, 31))
        return tuple(sorted({period.month for period in current} & {period.month for period in reference}))

    def _aggregate(
        self,
        request: PackageVolumeQueryRequest,
        build: MartBuildMetadata,
        periods: tuple[date, ...],
        metric_concepts: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        if not periods:
            return {}
        dimension_columns = _dimension_columns(request.grouping)
        clauses = [
            "f.retailer_id = ?",
            "f.source_id = ?",
            "f.mart_build_id = ?",
            "f.period_grain = ?",
            "f.private_label_scope = ?",
        ]
        params: list[Any] = [
            request.retailer_id,
            request.source_id,
            build.mart_build_id,
            request.period_grain,
            request.private_label_scope.value,
        ]
        placeholders = ", ".join("?" for _ in periods)
        clauses.append(f"f.period_start IN ({placeholders})")
        params.extend(period.isoformat() for period in periods)
        _add_scope_filters(clauses, params, request.entity_filters or {}, "f")
        requested_base_metrics = [concept for concept in metric_concepts if concept != "retailer_margin_pct"]
        if "retailer_margin_pct" in metric_concepts:
            requested_base_metrics.extend(["revenue", "retailer_margin_abs"])
        requested_base_metrics = sorted(set(requested_base_metrics) & {"revenue", "revenue_vat", "units", "retailer_margin_abs"})
        metric_placeholders = ", ".join("?" for _ in requested_base_metrics)
        not_null_clause = " AND ".join(_attribute_presence_clause(column) for column in dimension_columns)
        attribute_filters = ["retailer_id = ?", "source_id = ?"]
        if "package" in dimension_columns:
            attribute_filters.extend(["package IS NOT NULL", "CAST(package AS VARCHAR) <> ''"])
        if "volume_l" in dimension_columns:
            attribute_filters.append("volume_l IS NOT NULL")
        attribute_having = _attribute_having_clause(dimension_columns)
        sql = f"""
            WITH attrs AS (
                SELECT
                    canonical_product_id,
                    MIN(CAST(package AS VARCHAR)) AS package,
                    MIN(CAST(volume_l AS DOUBLE)) AS volume_l,
                    COUNT(DISTINCT CAST(package AS VARCHAR)) AS package_count,
                    COUNT(DISTINCT CAST(volume_l AS DOUBLE)) AS volume_count
                FROM read_parquet(?)
                WHERE {" AND ".join(attribute_filters)}
                GROUP BY canonical_product_id
                HAVING {attribute_having}
            )
            SELECT
                {", ".join(f"attrs.{column}" for column in dimension_columns)},
                f.metric_concept,
                SUM(f.value) AS value,
                SUM(f.numerator_value) AS numerator_value,
                SUM(f.denominator_value) AS denominator_value,
                COUNT(DISTINCT f.canonical_product_id) AS sku_count,
                MIN(f.metric_name) AS metric_name,
                MIN(f.metric_definition_id) AS metric_definition_id,
                MIN(f.metric_definition_version) AS metric_definition_version,
                MIN(f.metric_config_hash) AS metric_config_hash,
                MIN(f.rule_version) AS rule_version,
                MIN(f.semantic_family) AS semantic_family,
                MIN(f.semantic_compatibility_version) AS semantic_compatibility_version,
                MIN(f.cross_retailer_comparable) AS cross_retailer_comparable,
                MIN(f.source_revision_id) AS source_revision_id,
                MIN(f.analysis_run_id) AS analysis_run_id
            FROM read_parquet(?) AS f
            JOIN attrs ON attrs.canonical_product_id = f.canonical_product_id
            WHERE {" AND ".join(clauses)}
              AND f.metric_concept IN ({metric_placeholders})
              AND {not_null_clause}
            GROUP BY {", ".join(f"attrs.{column}" for column in dimension_columns)}, f.metric_concept
            ORDER BY {", ".join(f"attrs.{column}" for column in dimension_columns)}, f.metric_concept
        """
        rows = duckdb.sql(
            sql,
            params=[
                _duckdb_path(self.source_like_rows_path),
                request.retailer_id,
                request.source_id,
                _duckdb_path(self.product_store_facts_path),
                *params,
                *requested_base_metrics,
            ],
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            dims = tuple(row[index] for index in range(len(dimension_columns)))
            entity_id = _entity_id(request.grouping, dims)
            bucket = result.setdefault(
                entity_id,
                {
                    "entity_id": entity_id,
                    "label": _entity_label(request.grouping, dims),
                    "dimension_values": _dimension_values(request.grouping, dims),
                    "sku_count": int(row[len(dimension_columns) + 4] or 0),
                    "metrics": {},
                    "lineage": {},
                },
            )
            metric = str(row[len(dimension_columns)])
            value = float(row[len(dimension_columns) + 1] or 0.0)
            bucket["metrics"][metric] = value
            bucket["sku_count"] = max(bucket["sku_count"], int(row[len(dimension_columns) + 4] or 0))
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
        request: PackageVolumeQueryRequest,
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
                "basis_metric": request.basis_metric,
                "entity_filters": request.entity_filters or {},
                "comparison_mode": request.comparison_mode,
                "private_label_scope": request.private_label_scope.value,
                "mart_build_id": build.mart_build_id,
            },
            "grouping": request.grouping,
            "basis_metric": request.basis_metric,
            "available_periods": [],
            "reference_periods": [],
            "rows": [],
            "limitations": [
                {
                    "issue_code": code,
                    "message": "Package/volume mix is unavailable for the selected runtime scope.",
                },
                *limitations,
            ],
            "mart_build_id": build.mart_build_id,
            "source_revision_ids": list(build.source_revision_ids),
            "private_label_scope": request.private_label_scope.value,
        }


def build_package_volume_request(payload: PackageVolumeQueryRequest | dict[str, Any]) -> PackageVolumeQueryRequest:
    """Build a package/volume query request from UI payload."""

    if isinstance(payload, PackageVolumeQueryRequest):
        return payload
    raw_filters = payload.get("entity_filters")
    filters = (
        {str(key): tuple(str(item) for item in values) for key, values in raw_filters.items()}
        if isinstance(raw_filters, dict)
        else None
    )
    return PackageVolumeQueryRequest(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        date_from=_date_or_none(payload.get("date_from")),
        date_to=_date_or_none(payload.get("date_to")),
        period_mode=str(payload.get("period_mode", "SINGLE_PERIOD")),
        period_grain=str(payload.get("period_grain", "month")),
        grouping=str(payload.get("grouping", "package")),
        basis_metric=str(payload.get("basis_metric", "revenue")),
        metric_concepts=tuple(str(item) for item in payload.get("metric_concepts", SUPPORTED_METRICS)),
        entity_filters=filters,
        comparison_mode=str(payload.get("comparison_mode", "NONE")),
        comparison_period_start=_date_or_none(payload.get("comparison_period_start")),
        private_label_scope=PrivateLabelScope(payload.get("private_label_scope", PrivateLabelScope.INCLUDE)),
        mart_build_id=payload.get("mart_build_id"),
    )


def _mix_rows(
    request: PackageVolumeQueryRequest,
    build: MartBuildMetadata,
    current_rows: dict[str, dict[str, Any]],
    reference_rows: dict[str, dict[str, Any]],
    current_periods: tuple[date, ...],
    reference_periods: tuple[date, ...],
    requested: tuple[str, ...],
) -> list[dict[str, Any]]:
    denominator = sum(float(row["metrics"].get(request.basis_metric) or 0.0) for row in current_rows.values())
    reference_denominator = sum(float(row["metrics"].get(request.basis_metric) or 0.0) for row in reference_rows.values())
    rows: list[dict[str, Any]] = []
    for entity_id, row in current_rows.items():
        raw_basis_value = row["metrics"].get(request.basis_metric)
        basis_value = None if raw_basis_value is None else float(raw_basis_value)
        reference = reference_rows.get(entity_id)
        raw_reference_value = reference["metrics"].get(request.basis_metric) if reference else None
        reference_value = None if raw_reference_value is None else float(raw_reference_value)
        share = None if denominator <= 0 or basis_value is None else float(basis_value) / denominator
        reference_share = None if reference_denominator <= 0 or reference_value is None else float(reference_value) / reference_denominator
        share_delta_pp = None if share is None or reference_share is None else share - reference_share
        delta = None if reference_value is None or basis_value is None else basis_value - reference_value
        pct_delta = (
            None
            if basis_value is None or reference_value is None or reference_value == 0
            else (basis_value - reference_value) / abs(reference_value)
        )
        lineage = row["lineage"].get(request.basis_metric) or {}
        rows.append(
            {
                "entity_id": entity_id,
                "label": row["label"],
                "dimension_values": row["dimension_values"],
                "basis_metric_id": request.basis_metric,
                "metric_value": basis_value,
                "reference_metric_value": reference_value,
                "delta": delta,
                "pct_delta": pct_delta,
                "share": share,
                "reference_share": reference_share,
                "share_delta_pp": share_delta_pp,
                "share_denominator_value": denominator,
                "reference_share_denominator_value": reference_denominator,
                "metrics": {concept: row["metrics"].get(concept) for concept in requested if concept in row["metrics"]},
                "reference_metrics": {concept: reference["metrics"].get(concept) for concept in requested if reference and concept in reference["metrics"]},
                "sku_count": row["sku_count"],
                "reference_sku_count": reference["sku_count"] if reference else None,
                "lineage": lineage,
                "provenance": _provenance(request, build, row, lineage, current_periods, reference_periods, denominator),
            }
        )
    return rows


def _provenance(
    request: PackageVolumeQueryRequest,
    build: MartBuildMetadata,
    row: dict[str, Any],
    lineage: dict[str, Any],
    current_periods: tuple[date, ...],
    reference_periods: tuple[date, ...],
    denominator: float,
) -> dict[str, Any]:
    basis = request.basis_metric
    return {
        "metric": {
            "metric_concept": f"portfolio_{request.grouping}_mix",
            "metric_definition_id": lineage.get("metric_definition_id") or basis,
            "metric_definition_version": lineage.get("metric_definition_version"),
            "metric_config_hash": lineage.get("metric_config_hash"),
            "basis_metric": basis,
        },
        "value": {
            "value": row["metrics"].get(basis),
            "share": None if denominator <= 0 else (row["metrics"].get(basis) or 0.0) / denominator,
            "share_denominator_value": denominator,
            "range_aggregation_strategy": "sum_available_periods",
            "available_month_aggregation_method": "sum_available_periods"
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
            "comparison_periods": [period.isoformat() for period in reference_periods],
            "missing_periods": [],
            "period_set": {
                "scope_type": request.period_mode,
                "included_periods": [period.isoformat() for period in current_periods],
                "coverage_count": len(current_periods),
                "comparison_policy": "MATCHED_AVAILABLE_MONTHS",
            }
            if request.period_mode == "AVAILABLE_MONTH_SET"
            else {},
            "period_mode": request.period_mode,
            "comparison_mode": request.comparison_mode,
            "private_label_scope": request.private_label_scope.value,
        },
        "calculation": {
            "metric_concept": f"portfolio_{request.grouping}_mix",
            "basis_metric": basis,
            "aggregation_method": "sum_available_periods",
            "share_method": "basis metric divided by scoped package/volume mix universe total",
            "formula_summary": "group additive totals are read from product-store serving; share is recomputed over the selected attribute universe",
        },
        "run_lineage": {
            "mart_build_id": build.mart_build_id,
            "source_revision_ids": list(build.source_revision_ids),
            "analysis_run_ids": list(build.analysis_run_ids),
        },
        "lineage": {
            "mart_build_id": build.mart_build_id,
            "source_revision_ids": build.source_revision_ids,
            "metric_definition_id": lineage.get("metric_definition_id") or basis,
            "metric_definition_version": lineage.get("metric_definition_version"),
            "metric_config_hash": lineage.get("metric_config_hash"),
            "rule_version": lineage.get("rule_version"),
        },
        "source_evidence": {
            "status": "JOINED_CANONICAL_PRODUCT_ATTRIBUTES_TO_PRODUCT_STORE_FACTS",
            "attribute_source": "source_like_rows",
            "metric_source": "product_store_metric_facts",
            "source_revision_id": lineage.get("source_revision_id"),
            "analysis_run_id": lineage.get("analysis_run_id"),
        },
        "quality": {
            "quality_statuses": ["VALID"],
            "result_limitations": [],
        },
        "guardrails": {
            "package_abc_exposed": False,
            "volume_abc_exposed": False,
            "volume_band_exposed": False,
            "flavor_inferred": False,
            "fo2_exposed": False,
            "territory_exposed": False,
        },
    }


def _dimension_columns(grouping: str) -> tuple[str, ...]:
    if grouping == "package":
        return ("package",)
    if grouping == "volume":
        return ("volume_l",)
    if grouping == "package_volume":
        return ("package", "volume_l")
    raise ValueError(f"Unsupported package/volume grouping: {grouping}")


def _attribute_presence_clause(column: str) -> str:
    if column == "volume_l":
        return "attrs.volume_l IS NOT NULL"
    return f"attrs.{column} IS NOT NULL AND attrs.{column} <> ''"


def _attribute_having_clause(columns: tuple[str, ...]) -> str:
    clauses: list[str] = []
    if "package" in columns:
        clauses.append("package_count = 1")
    if "volume_l" in columns:
        clauses.append("volume_count = 1")
    return " AND ".join(clauses) or "TRUE"


def _dimension_values(grouping: str, dims: tuple[Any, ...]) -> dict[str, Any]:
    if grouping == "package":
        return {"package": str(dims[0])}
    if grouping == "volume":
        return {"volume_l": float(dims[0])}
    return {"package": str(dims[0]), "volume_l": float(dims[1])}


def _entity_id(grouping: str, dims: tuple[Any, ...]) -> str:
    if grouping == "volume":
        return _volume_label(float(dims[0]))
    if grouping == "package_volume":
        return f"{dims[0]} | {_volume_label(float(dims[1]))}"
    return str(dims[0])


def _entity_label(grouping: str, dims: tuple[Any, ...]) -> str:
    if grouping == "volume":
        return _volume_label(float(dims[0]))
    if grouping == "package_volume":
        return f"{dims[0]} · {_volume_label(float(dims[1]))}"
    return str(dims[0])


def _volume_label(value: float) -> str:
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{formatted} L"


def _sort_key(request: PackageVolumeQueryRequest, row: dict[str, Any]) -> tuple[Any, ...]:
    if request.grouping == "volume":
        return (row["dimension_values"].get("volume_l") is None, row["dimension_values"].get("volume_l"))
    return (-abs(float(row.get("metric_value") or 0.0)), row["label"])


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


def _add_scope_filters(
    clauses: list[str],
    params: list[Any],
    filters: dict[str, tuple[str, ...]],
    alias: str,
) -> None:
    for key, values in filters.items():
        column = _FILTER_COLUMNS.get(key)
        if column is None or not values:
            continue
        placeholders = ", ".join("?" for _ in values)
        if key == "volume":
            clauses.append(f"ROUND(CAST({alias}.{column} AS DOUBLE), {VOLUME_FILTER_DECIMALS}) IN ({placeholders})")
            params.extend(_volume_filter_values(values))
        else:
            clauses.append(f"{alias}.{column} IN ({placeholders})")
            params.extend(values)


def _date_or_none(value: date | str | None) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _volume_filter_values(values: tuple[str, ...]) -> tuple[float, ...]:
    return tuple(round(float(value), VOLUME_FILTER_DECIMALS) for value in values)


def _duckdb_path(path: Path | None) -> str:
    if path is None:
        return ""
    raw = path.as_posix()
    if path.is_dir():
        raw = f"{raw}/**/*.parquet"
    return raw
