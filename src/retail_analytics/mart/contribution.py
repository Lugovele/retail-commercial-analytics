"""Additive contribution-to-delta analysis over mart metric facts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from retail_analytics.mart.builds import MartBuildMetadata, MartBuildStatus
from retail_analytics.mart.scopes import PrivateLabelScope, scope_identity_hash

ADDITIVE_CONTRIBUTION_METRICS = frozenset(
    {"revenue_vat", "revenue", "units", "retailer_margin_abs"}
)
SUPPORTED_PARENT_CHILD_SCOPES = frozenset(
    {
        ("network", "category"),
        ("category", "manufacturer"),
        ("category", "brand"),
        ("category", "sku"),
    }
)
MAX_CONTRIBUTION_LIMIT = 200


class ContributionStatus(StrEnum):
    """Overall contribution response status."""

    READY = "READY"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_APPLICABLE_PARENT_CHILD_SCOPE = "NOT_APPLICABLE_PARENT_CHILD_SCOPE"
    TOTAL_DELTA_ZERO = "TOTAL_DELTA_ZERO"
    INSUFFICIENT_COMPARISON = "INSUFFICIENT_COMPARISON"
    AMBIGUOUS_METRIC_DEFINITION = "AMBIGUOUS_METRIC_DEFINITION"
    NO_DATA = "NO_DATA"


class ContributionRowStatus(StrEnum):
    """Per-row contribution status."""

    READY = "READY"
    TOTAL_DELTA_ZERO = "TOTAL_DELTA_ZERO"


@dataclass(frozen=True)
class MetricDefinitionIdentity:
    """One metric definition identity used by contribution rows."""

    metric_definition_id: str
    metric_definition_version: str
    metric_config_hash: str
    rule_version: str
    semantic_family: str | None
    semantic_compatibility_version: str | None
    aggregation: str
    range_aggregation_strategy: str


@dataclass(frozen=True)
class ContributionQueryRequest:
    """Request for additive child contribution to parent period delta."""

    retailer_id: str
    source_id: str
    current_period: date
    reference_period: date
    period_grain: str
    parent_grain_id: str
    parent_entity_id: str | None
    child_grain_id: str
    metric_concept: str
    comparison_mode: str
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None
    quality_policy: str = "INCLUDE_ALL"
    limit: int = 40
    parent_metric_definition_id: str | None = None
    child_metric_definition_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "private_label_scope", PrivateLabelScope(self.private_label_scope))
        object.__setattr__(self, "limit", max(1, min(int(self.limit), MAX_CONTRIBUTION_LIMIT)))


@dataclass(frozen=True)
class ContributionRow:
    """One child entity contribution to parent additive delta."""

    child_entity_id: str
    current_value: float
    reference_value: float
    delta: float
    absolute_delta: float
    parent_current_value: float
    parent_reference_value: float
    parent_delta: float
    contribution_share: float | None
    status: ContributionRowStatus
    provenance: dict[str, Any]


@dataclass(frozen=True)
class ContributionQueryResponse:
    """Structured contribution response for dashboard tables."""

    status: ContributionStatus
    request_scope: dict[str, Any]
    metric_concept: str
    parent_metric_definition: MetricDefinitionIdentity | None
    child_metric_definition: MetricDefinitionIdentity | None
    parent_current_value: float | None
    parent_reference_value: float | None
    parent_delta: float | None
    rows: tuple[ContributionRow, ...]
    limitations: tuple[str, ...]
    quality_flags: tuple[str, ...]
    mart_build_id: str | None
    analysis_run_ids: tuple[str, ...]
    source_revision_ids: tuple[str, ...]


class AdditiveContributionService:
    """Calculate additive contribution-to-delta from persisted mart facts."""

    def __init__(
        self,
        metric_facts_path: str | Path,
        *,
        mart_builds: tuple[MartBuildMetadata, ...] = (),
    ) -> None:
        self.metric_facts_path = Path(metric_facts_path)
        self.mart_builds = mart_builds

    def contribution(self, request: ContributionQueryRequest) -> ContributionQueryResponse:
        """Return child contribution rows or a structured not-applicable status."""

        mart_build_id = self._resolve_build_id(request)
        scope = _request_scope(request)
        if request.metric_concept not in ADDITIVE_CONTRIBUTION_METRICS:
            return _empty_response(
                request,
                mart_build_id,
                ContributionStatus.NOT_APPLICABLE,
                ("contribution_supported_for_additive_metrics_only",),
            )
        if (request.parent_grain_id, request.child_grain_id) not in SUPPORTED_PARENT_CHILD_SCOPES:
            return _empty_response(
                request,
                mart_build_id,
                ContributionStatus.NOT_APPLICABLE_PARENT_CHILD_SCOPE,
                ("parent_child_scope_not_available_in_mart_facts",),
            )

        parent = self._read_parent_facts(request, mart_build_id)
        child = self._read_child_facts(request, mart_build_id)
        if parent.is_empty() or child.is_empty():
            return _empty_response(request, mart_build_id, ContributionStatus.NO_DATA, ("contribution_no_data",))

        parent_identity_result = _resolve_identity(parent, request.parent_metric_definition_id)
        child_identity_result = _resolve_identity(child, request.child_metric_definition_id)
        if isinstance(parent_identity_result, str) or isinstance(child_identity_result, str):
            return _empty_response(
                request,
                mart_build_id,
                ContributionStatus.AMBIGUOUS_METRIC_DEFINITION,
                tuple(
                    item
                    for item in (parent_identity_result, child_identity_result)
                    if isinstance(item, str)
                ),
            )
        parent_identity = parent_identity_result
        child_identity = child_identity_result
        compatibility_issue = _definition_compatibility_issue(request, parent_identity, child_identity)
        if compatibility_issue is not None:
            return _empty_response(
                request,
                mart_build_id,
                ContributionStatus.AMBIGUOUS_METRIC_DEFINITION,
                (compatibility_issue,),
            )

        parent_values = _period_values(parent)
        if request.current_period not in parent_values or request.reference_period not in parent_values:
            return _empty_response(
                request,
                mart_build_id,
                ContributionStatus.INSUFFICIENT_COMPARISON,
                ("parent_current_or_reference_period_missing",),
            )
        parent_current = parent_values[request.current_period]
        parent_reference = parent_values[request.reference_period]
        parent_delta = parent_current - parent_reference
        analysis_run_ids = _unique(parent, child, "analysis_run_id")
        source_revision_ids = _unique(parent, child, "source_revision_id")
        child_rows = _child_rows(
            child,
            request,
            parent_current,
            parent_reference,
            parent_delta,
            parent_identity=parent_identity,
            child_identity=child_identity,
            mart_build_id=mart_build_id,
            analysis_run_ids=analysis_run_ids,
            source_revision_ids=source_revision_ids,
        )
        quality_flags = list(_quality_flags(parent, child))
        quality_flags.extend(_reconciliation_flags(child_rows, parent_current, parent_reference, parent_delta))
        status = ContributionStatus.TOTAL_DELTA_ZERO if parent_delta == 0 else ContributionStatus.READY
        sorted_rows = tuple(
            sorted(
                child_rows,
                key=lambda row: (-row.absolute_delta, -row.current_value, row.child_entity_id),
            )[: request.limit]
        )
        return ContributionQueryResponse(
            status=status,
            request_scope=scope,
            metric_concept=request.metric_concept,
            parent_metric_definition=parent_identity,
            child_metric_definition=child_identity,
            parent_current_value=parent_current,
            parent_reference_value=parent_reference,
            parent_delta=parent_delta,
            rows=sorted_rows,
            limitations=(),
            quality_flags=tuple(dict.fromkeys(quality_flags)),
            mart_build_id=mart_build_id,
            analysis_run_ids=analysis_run_ids,
            source_revision_ids=source_revision_ids,
        )

    def _resolve_build_id(self, request: ContributionQueryRequest) -> str:
        if request.mart_build_id:
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
        distinct = duckdb.sql(
            """
                SELECT DISTINCT mart_build_id
                FROM read_parquet(?)
                WHERE retailer_id = ?
                  AND source_id = ?
                  AND period_grain = ?
            """,
            params=[
                _duckdb_path(self.metric_facts_path),
                request.retailer_id,
                request.source_id,
                request.period_grain,
            ],
        ).fetchall()
        builds = tuple(sorted(str(row[0]) for row in distinct))
        if len(builds) == 1:
            return builds[0]
        raise ValueError("Contribution request requires one approved mart_build_id")

    def _read_parent_facts(self, request: ContributionQueryRequest, mart_build_id: str) -> pl.DataFrame:
        clauses, params = _base_clauses(request, mart_build_id)
        clauses.append("grain_id = ?")
        params.append(request.parent_grain_id)
        if request.parent_entity_id:
            clauses.append("entity_id = ?")
            params.append(request.parent_entity_id)
        return _read_facts(self.metric_facts_path, clauses, params)

    def _read_child_facts(self, request: ContributionQueryRequest, mart_build_id: str) -> pl.DataFrame:
        clauses, params = _base_clauses(request, mart_build_id)
        clauses.append("grain_id = ?")
        params.append(request.child_grain_id)
        if request.parent_grain_id == "category":
            clauses.append("json_extract_string(parent_entity_ids, '$.category') = ?")
            params.append(request.parent_entity_id or "")
        return _read_facts(self.metric_facts_path, clauses, params)


def _base_clauses(request: ContributionQueryRequest, mart_build_id: str) -> tuple[list[str], list[Any]]:
    clauses = [
        "retailer_id = ?",
        "source_id = ?",
        "period_grain = ?",
        "mart_build_id = ?",
        "private_label_scope = ?",
        "metric_concept = ?",
        "period_start IN (CAST(? AS DATE), CAST(? AS DATE))",
    ]
    params: list[Any] = [
        request.retailer_id,
        request.source_id,
        request.period_grain,
        mart_build_id,
        request.private_label_scope.value,
        request.metric_concept,
        request.current_period.isoformat(),
        request.reference_period.isoformat(),
    ]
    if request.quality_policy == "VALID_ONLY":
        clauses.append("quality_status = ?")
        params.append("valid")
    return clauses, params


def _read_facts(path: Path, clauses: list[str], params: list[Any]) -> pl.DataFrame:
    sql = f"""
        SELECT *
        FROM read_parquet(?)
        WHERE {" AND ".join(clauses)}
    """
    return duckdb.sql(sql, params=[_duckdb_path(path), *params]).pl()


def _resolve_identity(frame: pl.DataFrame, metric_definition_id: str | None) -> MetricDefinitionIdentity | str:
    result = frame
    if metric_definition_id:
        result = result.filter(pl.col("metric_definition_id") == metric_definition_id)
        if result.is_empty():
            return "metric_definition_not_found"
    identities = result.select(
        [
            "metric_definition_id",
            "metric_definition_version",
            "metric_config_hash",
            "rule_version",
            "semantic_family",
            "semantic_compatibility_version",
            "aggregation",
            "range_aggregation_strategy",
        ]
    ).unique()
    if identities.height != 1:
        return "ambiguous_metric_definition"
    row = identities.row(0, named=True)
    return MetricDefinitionIdentity(
        metric_definition_id=str(row["metric_definition_id"]),
        metric_definition_version=str(row["metric_definition_version"]),
        metric_config_hash=str(row["metric_config_hash"]),
        rule_version=str(row["rule_version"]),
        semantic_family=str(row["semantic_family"]) if row["semantic_family"] is not None else None,
        semantic_compatibility_version=str(row["semantic_compatibility_version"])
        if row["semantic_compatibility_version"] is not None
        else None,
        aggregation=str(row["aggregation"]),
        range_aggregation_strategy=str(row["range_aggregation_strategy"]),
    )


def _definition_compatibility_issue(
    request: ContributionQueryRequest,
    parent: MetricDefinitionIdentity,
    child: MetricDefinitionIdentity,
) -> str | None:
    if parent.aggregation != "sum" or child.aggregation != "sum":
        return "contribution_requires_sum_aggregation"
    if (
        parent.range_aggregation_strategy != "sum_available_periods"
        or child.range_aggregation_strategy != "sum_available_periods"
    ):
        return "contribution_requires_sum_available_periods"
    compatible_pairs = (
        ("metric_config_hash", parent.metric_config_hash, child.metric_config_hash),
        ("rule_version", parent.rule_version, child.rule_version),
        ("semantic_family", parent.semantic_family, child.semantic_family),
        (
            "semantic_compatibility_version",
            parent.semantic_compatibility_version,
            child.semantic_compatibility_version,
        ),
    )
    for name, left, right in compatible_pairs:
        if left is not None and right is not None and left != right:
            return f"incompatible_{name}"
    del request
    return None


def _period_values(frame: pl.DataFrame) -> dict[date, float]:
    grouped = frame.group_by("period_start").agg(pl.col("value").sum().alias("value"))
    return {row["period_start"]: float(row["value"] or 0.0) for row in grouped.to_dicts()}


def _child_rows(
    frame: pl.DataFrame,
    request: ContributionQueryRequest,
    parent_current: float,
    parent_reference: float,
    parent_delta: float,
    *,
    parent_identity: MetricDefinitionIdentity,
    child_identity: MetricDefinitionIdentity,
    mart_build_id: str,
    analysis_run_ids: tuple[str, ...],
    source_revision_ids: tuple[str, ...],
) -> tuple[ContributionRow, ...]:
    grouped = frame.group_by(["entity_id", "period_start"]).agg(pl.col("value").sum().alias("value"))
    per_entity: dict[str, dict[date, float]] = {}
    for row in grouped.to_dicts():
        per_entity.setdefault(str(row["entity_id"]), {})[row["period_start"]] = float(row["value"] or 0.0)
    rows: list[ContributionRow] = []
    for entity_id, values in per_entity.items():
        current = values.get(request.current_period, 0.0)
        reference = values.get(request.reference_period, 0.0)
        delta = current - reference
        share = None if parent_delta == 0 else delta / parent_delta
        status = ContributionRowStatus.TOTAL_DELTA_ZERO if parent_delta == 0 else ContributionRowStatus.READY
        rows.append(
            ContributionRow(
                child_entity_id=entity_id,
                current_value=current,
                reference_value=reference,
                delta=delta,
                absolute_delta=abs(delta),
                parent_current_value=parent_current,
                parent_reference_value=parent_reference,
                parent_delta=parent_delta,
                contribution_share=share,
                status=status,
                provenance=_row_provenance(
                    request,
                    entity_id,
                    current,
                    reference,
                    delta,
                    parent_delta,
                    share,
                    status,
                    parent_identity=parent_identity,
                    child_identity=child_identity,
                    mart_build_id=mart_build_id,
                    analysis_run_ids=analysis_run_ids,
                    source_revision_ids=source_revision_ids,
                ),
            )
        )
    return tuple(rows)


def _row_provenance(
    request: ContributionQueryRequest,
    child_entity_id: str,
    current: float,
    reference: float,
    delta: float,
    parent_delta: float,
    share: float | None,
    status: ContributionRowStatus,
    *,
    parent_identity: MetricDefinitionIdentity,
    child_identity: MetricDefinitionIdentity,
    mart_build_id: str,
    analysis_run_ids: tuple[str, ...],
    source_revision_ids: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "scope": _request_scope(request),
        "parent": {"grain_id": request.parent_grain_id, "entity_id": request.parent_entity_id},
        "child": {"grain_id": request.child_grain_id, "entity_id": child_entity_id},
        "metric": {
            "metric_concept": request.metric_concept,
            "parent_definition": _identity_dict(parent_identity),
            "child_definition": _identity_dict(child_identity),
        },
        "calculation": {
            "current_value": current,
            "reference_value": reference,
            "child_delta": delta,
            "parent_delta": parent_delta,
            "formula": "child_delta / parent_delta",
            "contribution_share": share,
            "status": status.value,
        },
        "run_lineage": {
            "mart_build_id": mart_build_id,
            "analysis_run_ids": analysis_run_ids,
            "source_revision_ids": source_revision_ids,
        },
        "source_evidence": {
            "status": "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS",
            "source_row_ids": (),
        },
        "missing_fields": ("source_row_ids",),
    }


def _identity_dict(identity: MetricDefinitionIdentity) -> dict[str, Any]:
    return {
        "metric_definition_id": identity.metric_definition_id,
        "metric_definition_version": identity.metric_definition_version,
        "metric_config_hash": identity.metric_config_hash,
        "rule_version": identity.rule_version,
        "semantic_family": identity.semantic_family,
        "semantic_compatibility_version": identity.semantic_compatibility_version,
        "aggregation": identity.aggregation,
        "range_aggregation_strategy": identity.range_aggregation_strategy,
    }


def _request_scope(request: ContributionQueryRequest) -> dict[str, Any]:
    return {
        "retailer_id": request.retailer_id,
        "source_id": request.source_id,
        "period_grain": request.period_grain,
        "current_period": request.current_period.isoformat(),
        "reference_period": request.reference_period.isoformat(),
        "comparison_mode": request.comparison_mode,
        "parent_grain_id": request.parent_grain_id,
        "parent_entity_id": request.parent_entity_id,
        "child_grain_id": request.child_grain_id,
        "private_label_scope": request.private_label_scope.value,
        "scope_identity_hash": scope_identity_hash(private_label_scope=request.private_label_scope),
    }


def _empty_response(
    request: ContributionQueryRequest,
    mart_build_id: str | None,
    status: ContributionStatus,
    limitations: tuple[str, ...],
) -> ContributionQueryResponse:
    return ContributionQueryResponse(
        status=status,
        request_scope=_request_scope(request),
        metric_concept=request.metric_concept,
        parent_metric_definition=None,
        child_metric_definition=None,
        parent_current_value=None,
        parent_reference_value=None,
        parent_delta=None,
        rows=(),
        limitations=limitations,
        quality_flags=(),
        mart_build_id=mart_build_id,
        analysis_run_ids=(),
        source_revision_ids=(),
    )


def _quality_flags(parent: pl.DataFrame, child: pl.DataFrame) -> tuple[str, ...]:
    flags: set[str] = set()
    for frame in (parent, child):
        if "quality_flags" not in frame.columns:
            continue
        flags.update(str(item) for item in frame["quality_flags"].drop_nulls().to_list() if item)
    return tuple(sorted(flags))


def _reconciliation_flags(
    rows: tuple[ContributionRow, ...],
    parent_current: float,
    parent_reference: float,
    parent_delta: float,
) -> tuple[str, ...]:
    current = math.fsum(row.current_value for row in rows)
    reference = math.fsum(row.reference_value for row in rows)
    delta = math.fsum(row.delta for row in rows)
    flags: list[str] = []
    tolerance = 1e-6
    if abs(current - parent_current) > tolerance:
        flags.append("RECONCILIATION_CURRENT_WARNING")
    if abs(reference - parent_reference) > tolerance:
        flags.append("RECONCILIATION_REFERENCE_WARNING")
    if abs(delta - parent_delta) > tolerance:
        flags.append("RECONCILIATION_DELTA_WARNING")
    return tuple(flags)


def _unique(parent: pl.DataFrame, child: pl.DataFrame, column: str) -> tuple[str, ...]:
    values: list[str] = []
    for frame in (parent, child):
        if column in frame.columns:
            values.extend(str(item) for item in frame[column].drop_nulls().unique().to_list())
    return tuple(sorted(set(values)))


def _duckdb_path(path: Path) -> str:
    raw = path.as_posix()
    if path.is_dir():
        raw = f"{raw}/**/*.parquet"
    return raw
