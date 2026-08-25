"""Product-safe Data screen backend contract."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from retail_analytics.history import SourceLedgerEntry, active_revisions
from retail_analytics.mart import MartBuildMetadata, PrivateLabelScope


@dataclass(frozen=True)
class DashboardDataRequest:
    """Data screen request over the current analytical scope."""

    retailer_id: str
    source_id: str
    period_mode: str
    period_grain: str
    date_from: date | None = None
    date_to: date | None = None
    grain_id: str = "network"
    entity_ids: tuple[str, ...] = ()
    entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: str = "NONE"
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class DashboardDataResponse:
    """Coherent payload for the Data screen."""

    request_scope: dict[str, Any]
    coverage_grid: dict[str, Any]
    quality_summary: dict[str, Any]
    source_like_rows: dict[str, Any]
    audit: dict[str, Any]
    limitations: tuple[str, ...]
    private_label_scope: PrivateLabelScope


class DashboardDataService:
    """Read current dataset coverage, quality, source-like rows, and audit metadata."""

    def __init__(
        self,
        metric_facts_path: str | Path,
        *,
        mart_builds: tuple[MartBuildMetadata, ...] = (),
        source_ledger: tuple[SourceLedgerEntry, ...] = (),
        source_like_rows_path: str | Path | None = None,
    ) -> None:
        self.metric_facts_path = Path(metric_facts_path)
        self.mart_builds = mart_builds
        self.source_ledger = source_ledger
        self.source_like_rows_path = Path(source_like_rows_path) if source_like_rows_path is not None else None

    def query(self, request: DashboardDataRequest) -> DashboardDataResponse:
        """Return data-screen metadata without exposing private filesystem details."""

        build = self._resolve_build(request)
        ledger_entries = _current_build_ledger(self.source_ledger, request, build)
        fact_periods = _fact_periods(self.metric_facts_path, request, build.mart_build_id)
        ledger_periods = tuple(sorted({period for entry in ledger_entries for period in entry.observed_periods}))
        active_periods = tuple(
            sorted(
                {
                    date.fromisoformat(period_id)
                    for entry in ledger_entries
                    for period_id in (entry.active_business_period_ids or entry.business_period_ids)
                    if _is_iso_date(period_id)
                }
            )
        )
        available_periods = tuple(sorted(set(fact_periods) | set(active_periods) | set(ledger_periods)))
        coverage_grid = _coverage_grid(available_periods)
        quality_summary = self._quality_summary(request, build, ledger_entries)
        source_like_rows, row_limitations = self._source_like_rows(request, build)
        audit = _audit_payload(request, build, ledger_entries, available_periods)
        limitations = tuple(
            dict.fromkeys(
                (
                    *row_limitations,
                    *quality_summary.get("limitations", ()),
                    *(() if available_periods else ("no_period_coverage",)),
                )
            )
        )
        return DashboardDataResponse(
            request_scope={
                "retailer_id": request.retailer_id,
                "source_id": request.source_id,
                "period_mode": request.period_mode,
                "period_grain": request.period_grain,
                "grain_id": request.grain_id,
                "entity_ids": request.entity_ids,
                "entity_filters": request.entity_filters or {},
                "comparison_mode": request.comparison_mode,
                "private_label_scope": request.private_label_scope.value,
                "mart_build_id": build.mart_build_id,
            },
            coverage_grid=coverage_grid,
            quality_summary=quality_summary,
            source_like_rows=source_like_rows,
            audit=audit,
            limitations=limitations,
            private_label_scope=request.private_label_scope,
        )

    def _resolve_build(self, request: DashboardDataRequest) -> MartBuildMetadata:
        candidates = [
            build
            for build in self.mart_builds
            if build.retailer_id == request.retailer_id
            and request.source_id in build.source_ids
            and (request.mart_build_id is None or build.mart_build_id == request.mart_build_id)
        ]
        if not candidates:
            raise ValueError("No mart build matches Data screen request")
        approved = [build for build in candidates if build.status == "approved"]
        selected = approved or candidates
        if request.mart_build_id:
            return selected[0]
        selected = sorted(selected, key=lambda build: build.built_at, reverse=True)
        return selected[0]

    def _quality_summary(
        self,
        request: DashboardDataRequest,
        build: MartBuildMetadata,
        ledger_entries: tuple[SourceLedgerEntry, ...],
    ) -> dict[str, Any]:
        fact_quality = duckdb.sql(
            """
                SELECT
                    quality_status,
                    quality_flags,
                    COUNT(*) AS row_count
                FROM read_parquet(?)
                WHERE retailer_id = ?
                  AND source_id = ?
                  AND mart_build_id = ?
                  AND period_grain = ?
                  AND private_label_scope = ?
                GROUP BY quality_status, quality_flags
                ORDER BY quality_status, quality_flags
            """,
            params=[
                _duckdb_path(self.metric_facts_path),
                request.retailer_id,
                request.source_id,
                build.mart_build_id,
                request.period_grain,
                request.private_label_scope.value,
            ],
        ).fetchall()
        quality_rows = [
            {
                "status": str(status),
                "flags": str(flags) if flags is not None else None,
                "row_count": int(row_count),
            }
            for status, flags, row_count in fact_quality
        ]
        warnings = [
            row
            for row in quality_rows
            if row["status"] != "valid" or row["flags"] not in (None, "")
        ]
        source_rows = sum((entry.row_count or 0) for entry in ledger_entries)
        return {
            "status": "HAS_WARNINGS" if warnings else "CHECKS_PASSED",
            "summary": "deterministic_checks",
            "mart_build_status": build.status,
            "active_revision_count": len(active_revisions(ledger_entries)),
            "source_row_count": source_rows or build.input_row_count,
            "fact_row_count": build.fact_row_count,
            "fact_quality": quality_rows,
            "warnings": warnings,
            "limitations": () if quality_rows else ("quality_fact_rows_unavailable",),
        }

    def _source_like_rows(
        self,
        request: DashboardDataRequest,
        build: MartBuildMetadata,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        if self.source_like_rows_path is None:
            return (
                {
                    "status": "NOT_CONFIGURED",
                    "columns": (),
                    "rows": (),
                    "limit": min(max(request.limit, 1), 100),
                    "offset": max(request.offset, 0),
                    "total_count": 0,
                },
                ("source_like_rows_not_configured",),
            )
        if not self.source_like_rows_path.exists():
            return (
                {
                    "status": "NOT_AVAILABLE",
                    "columns": (),
                    "rows": (),
                    "limit": min(max(request.limit, 1), 100),
                    "offset": max(request.offset, 0),
                    "total_count": 0,
                },
                ("source_like_rows_path_missing",),
            )
        columns = _source_like_columns(self.source_like_rows_path)
        selected_columns = [column for column in _SOURCE_LIKE_COLUMN_ORDER if column in columns]
        if not selected_columns:
            return (
                {
                    "status": "NOT_AVAILABLE",
                    "columns": (),
                    "rows": (),
                    "limit": min(max(request.limit, 1), 100),
                    "offset": max(request.offset, 0),
                    "total_count": 0,
                },
                ("source_like_rows_no_approved_columns",),
            )
        clauses, params = _source_like_scope_clauses(columns, request, build)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = min(max(request.limit, 1), 100)
        offset = max(request.offset, 0)
        total_row = duckdb.sql(
            f"SELECT COUNT(*) FROM read_parquet(?) {where}",
            params=[_duckdb_path(self.source_like_rows_path), *params],
        ).fetchone()
        total = int(total_row[0]) if total_row is not None else 0
        order_columns: list[str] = [
            column for column in ("period", "category", "manufacturer", "brand", "sku_name") if column in selected_columns
        ]
        if not order_columns:
            order_columns = selected_columns[:1]
        rows = duckdb.sql(
            f"""
                SELECT {', '.join(selected_columns)}
                FROM read_parquet(?)
                {where}
                ORDER BY {', '.join(order_columns)}
                LIMIT ? OFFSET ?
            """,
            params=[_duckdb_path(self.source_like_rows_path), *params, limit, offset],
        ).fetchall()
        return (
            {
                "status": "READY",
                "columns": tuple(selected_columns),
                "rows": tuple(dict(zip(selected_columns, row, strict=True)) for row in rows),
                "limit": limit,
                "offset": offset,
                "total_count": total,
            },
            (),
        )


_SOURCE_LIKE_COLUMN_ORDER = (
    "period",
    "category",
    "manufacturer",
    "brand",
    "sku_name",
    "units",
    "revenue_vat",
    "private_label_flag",
)


def _scope_ledger(
    ledger: tuple[SourceLedgerEntry, ...],
    request: DashboardDataRequest,
) -> tuple[SourceLedgerEntry, ...]:
    return tuple(
        entry
        for entry in ledger
        if entry.retailer_id == request.retailer_id and entry.source_id == request.source_id
    )


def _current_build_ledger(
    ledger: tuple[SourceLedgerEntry, ...],
    request: DashboardDataRequest,
    build: MartBuildMetadata,
) -> tuple[SourceLedgerEntry, ...]:
    scoped = _scope_ledger(ledger, request)
    build_revision_ids = set(build.source_revision_ids)
    if build_revision_ids:
        matching = tuple(entry for entry in scoped if entry.source_revision_id in build_revision_ids)
        if matching:
            return matching
    return active_revisions(scoped)


def _fact_periods(path: Path, request: DashboardDataRequest, mart_build_id: str) -> tuple[date, ...]:
    rows = duckdb.sql(
        """
            SELECT DISTINCT period_start
            FROM read_parquet(?)
            WHERE retailer_id = ?
              AND source_id = ?
              AND mart_build_id = ?
              AND period_grain = ?
              AND private_label_scope = ?
            ORDER BY period_start
        """,
        params=[
            _duckdb_path(path),
            request.retailer_id,
            request.source_id,
            mart_build_id,
            request.period_grain,
            request.private_label_scope.value,
        ],
    ).fetchall()
    return tuple(row[0] for row in rows)


def _coverage_grid(periods: tuple[date, ...]) -> dict[str, Any]:
    if not periods:
        return {"status": "NONE", "available_periods": (), "years": ()}
    available = set(periods)
    years = []
    for year in range(min(period.year for period in periods), max(period.year for period in periods) + 1):
        months = []
        first_month = 1
        last_month = 12
        if year == min(period.year for period in periods):
            first_month = min(period.month for period in periods if period.year == year)
        if year == max(period.year for period in periods):
            last_month = max(period.month for period in periods if period.year == year)
        for month in range(first_month, last_month + 1):
            period = date(year, month, 1)
            months.append(
                {
                    "period": period,
                    "month": month,
                    "label": calendar.month_abbr[month],
                    "available": period in available,
                }
            )
        years.append({"year": year, "months": tuple(months)})
    return {
        "status": "READY",
        "available_periods": periods,
        "years": tuple(years),
    }


def _audit_payload(
    request: DashboardDataRequest,
    build: MartBuildMetadata,
    ledger_entries: tuple[SourceLedgerEntry, ...],
    available_periods: tuple[date, ...],
) -> dict[str, Any]:
    active = active_revisions(ledger_entries)
    return {
        "source_revisions": tuple(
            {
                "source_revision_id": entry.source_revision_id,
                "revision_state": entry.revision_state,
                "processing_status": entry.processing_status,
                "period_start": entry.period_start,
                "period_end": entry.period_end,
                "observed_periods": entry.observed_periods,
                "row_count": entry.row_count,
                "source_hash": entry.source_hash,
                "schema_version": entry.source_schema_version,
            }
            for entry in active
        ),
        "mart_build": {
            "mart_build_id": build.mart_build_id,
            "status": build.status,
            "build_version": build.build_version,
            "built_at": build.built_at.isoformat(),
            "analysis_run_ids": build.analysis_run_ids,
            "source_revision_ids": build.source_revision_ids,
            "metric_config_hashes": build.metric_config_hashes,
            "rule_versions": build.rule_versions,
            "input_row_count": build.input_row_count,
            "fact_row_count": build.fact_row_count,
        },
        "coverage_periods": available_periods,
        "private_label_scope": request.private_label_scope.value,
    }


def _source_like_columns(path: Path) -> set[str]:
    return {
        str(row[0])
        for row in duckdb.sql(
            "DESCRIBE SELECT * FROM read_parquet(?) LIMIT 0",
            params=[_duckdb_path(path)],
        ).fetchall()
    }


def _source_like_scope_clauses(
    columns: set[str],
    request: DashboardDataRequest,
    build: MartBuildMetadata,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (("retailer_id", request.retailer_id), ("source_id", request.source_id)):
        if column in columns:
            clauses.append(f"{column} = ?")
            params.append(value)
    if "source_revision_id" in columns and build.source_revision_ids:
        placeholders = ", ".join("?" for _ in build.source_revision_ids)
        clauses.append(f"source_revision_id IN ({placeholders})")
        params.extend(build.source_revision_ids)
    if "period" in columns:
        if request.date_from is not None:
            clauses.append("CAST(period AS DATE) >= CAST(? AS DATE)")
            params.append(request.date_from.isoformat())
        if request.date_to is not None:
            clauses.append("CAST(period AS DATE) <= CAST(? AS DATE)")
            params.append(request.date_to.isoformat())
    for key, values in (request.entity_filters or {}).items():
        filter_column = _SOURCE_FILTER_COLUMNS.get(key)
        if filter_column is not None and filter_column in columns and values:
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"{filter_column} IN ({placeholders})")
            params.extend(values)
    if request.grain_id in _SOURCE_FILTER_COLUMNS and request.entity_ids:
        grain_column = _SOURCE_FILTER_COLUMNS[request.grain_id]
        if grain_column in columns:
            placeholders = ", ".join("?" for _ in request.entity_ids)
            clauses.append(f"{grain_column} IN ({placeholders})")
            params.extend(request.entity_ids)
    if "private_label_flag" in columns and request.private_label_scope != PrivateLabelScope.INCLUDE:
        clauses.append("private_label_flag = ?")
        params.append(request.private_label_scope == PrivateLabelScope.ONLY)
    return clauses, params


_SOURCE_FILTER_COLUMNS = {
    "category": "category",
    "manufacturer": "manufacturer",
    "brand": "brand",
    "sku": "canonical_product_id",
    "store": "canonical_store_id",
}


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _duckdb_path(path: Path) -> str:
    raw = path.as_posix()
    if path.is_dir():
        raw = f"{raw}/**/*.parquet"
    return raw


def build_data_request(payload: DashboardDataRequest | dict[str, Any]) -> DashboardDataRequest:
    """Build a Data screen request from browser payload."""

    if isinstance(payload, DashboardDataRequest):
        return payload
    raw_filters = payload.get("entity_filters")
    filters = (
        {str(key): tuple(str(item) for item in values) for key, values in raw_filters.items()}
        if isinstance(raw_filters, dict)
        else None
    )
    return DashboardDataRequest(
        retailer_id=str(payload["retailer_id"]),
        source_id=str(payload["source_id"]),
        period_mode=str(payload.get("period_mode", "SINGLE_PERIOD")),
        period_grain=str(payload.get("period_grain", "month")),
        date_from=_date_or_none(payload.get("date_from")),
        date_to=_date_or_none(payload.get("date_to")),
        grain_id=str(payload.get("grain_id", "network")),
        entity_ids=tuple(str(item) for item in payload.get("entity_ids", ())),
        entity_filters=filters,
        comparison_mode=str(payload.get("comparison_mode", "NONE")),
        private_label_scope=PrivateLabelScope(payload.get("private_label_scope", PrivateLabelScope.INCLUDE)),
        mart_build_id=payload.get("mart_build_id"),
        limit=int(payload.get("limit", 50)),
        offset=int(payload.get("offset", 0)),
    )


def _date_or_none(value: date | str | None) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def data_response_to_dict(response: DashboardDataResponse) -> dict[str, Any]:
    """Serialize Data screen response to JSON-compatible values."""

    return {
        "request_scope": _json_ready(response.request_scope),
        "coverage_grid": _json_ready(response.coverage_grid),
        "quality_summary": _json_ready(response.quality_summary),
        "source_like_rows": _json_ready(response.source_like_rows),
        "audit": _json_ready(response.audit),
        "limitations": list(response.limitations),
        "private_label_scope": response.private_label_scope.value,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value
