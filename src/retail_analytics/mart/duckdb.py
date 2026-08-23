"""DuckDB smoke query helpers for Parquet mart facts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import polars as pl


def query_metric_facts(
    parquet_path: str | Path,
    *,
    retailer_id: str | None = None,
    source_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    grain_id: str | None = None,
    metric_concept: str | None = None,
    metric_definition_id: str | None = None,
    mart_build_id: str | None = None,
) -> pl.DataFrame:
    """Read mart facts through DuckDB with explicit scope filters.

    This helper proves Parquet queryability. It is not the dashboard query API.
    """

    clauses: list[str] = []
    params: list[Any] = []
    _add_eq(clauses, params, "retailer_id", retailer_id)
    _add_eq(clauses, params, "source_id", source_id)
    _add_eq(clauses, params, "grain_id", grain_id)
    _add_eq(clauses, params, "metric_concept", metric_concept)
    _add_eq(clauses, params, "metric_definition_id", metric_definition_id)
    _add_eq(clauses, params, "mart_build_id", mart_build_id)
    if period_start is not None:
        clauses.append("period_start >= CAST(? AS DATE)")
        params.append(period_start)
    if period_end is not None:
        clauses.append("period_end <= CAST(? AS DATE)")
        params.append(period_end)

    sql = "SELECT * FROM read_parquet(?)"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY retailer_id, source_id, period_start, grain_id, entity_id, metric_definition_id"
    return duckdb.sql(sql, params=[_duckdb_path(parquet_path), *params]).pl()


def _add_eq(clauses: list[str], params: list[Any], column: str, value: str | None) -> None:
    if value is not None:
        clauses.append(f"{column} = ?")
        params.append(value)


def _duckdb_path(path: str | Path) -> str:
    candidate = Path(path)
    raw = candidate.as_posix()
    if candidate.is_dir():
        raw = f"{raw}/**/*.parquet"
    return raw
