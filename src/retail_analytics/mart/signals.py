"""Product-safe deterministic signal feed over persisted event outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import yaml  # type: ignore[import-untyped]

from retail_analytics.mart.builds import MartBuildMetadata, MartBuildStatus
from retail_analytics.mart.query import ComparisonMode, PeriodMode
from retail_analytics.mart.scopes import PrivateLabelScope, scope_identity_hash

COMMERCIAL_SIGNAL_FAMILIES = frozenset(
    {
        "GROWTH_DECLINE",
        "DISTRIBUTION",
        "VELOCITY",
        "SHARE",
        "PRICE",
        "MARGIN_PCT",
    }
)
DETERMINISTIC_PATTERN_FAMILIES = frozenset({"PATTERN_CANDIDATE"})
NON_SURFACED_EVENT_TYPES = frozenset(
    {
        "PROMO_LIKE_PATTERN",
        "ABC_CLASS_CHANGE",
        "PERSISTENT_C_CLASS",
    }
)
NON_SURFACED_EVENT_FAMILIES = frozenset({"PORTFOLIO", "BENCHMARK"})


class SignalFeedStatus(StrEnum):
    """Overall signal feed status."""

    READY = "READY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NO_CONFIRMED_EVENTS = "NO_CONFIRMED_EVENTS"
    NO_SURFACED_SIGNALS = "NO_SURFACED_SIGNALS"
    PARTIAL = "PARTIAL"


class SignalType(StrEnum):
    """Product-facing signal buckets."""

    COMMERCIAL_SIGNAL = "COMMERCIAL_SIGNAL"
    DETERMINISTIC_PATTERN = "DETERMINISTIC_PATTERN"
    DATA_QUALITY_ALERT = "DATA_QUALITY_ALERT"
    CAPABILITY_LIMITATION = "CAPABILITY_LIMITATION"


class SignalRowStatus(StrEnum):
    """Per-row signal evidence status."""

    READY = "READY"
    PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"


@dataclass(frozen=True)
class SignalFeedRequest:
    """Scope-aware deterministic signal feed request."""

    retailer_id: str
    source_id: str
    period_mode: PeriodMode
    period_grain: str
    date_from: date | None
    date_to: date | None
    grain_id: str = "network"
    entity_ids: tuple[str, ...] = ()
    entity_filters: dict[str, tuple[str, ...]] | None = None
    comparison_mode: ComparisonMode = ComparisonMode.NONE
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE
    mart_build_id: str | None = None
    signal_types: tuple[SignalType, ...] = (
        SignalType.COMMERCIAL_SIGNAL,
        SignalType.DETERMINISTIC_PATTERN,
        SignalType.DATA_QUALITY_ALERT,
    )
    limit: int = 50
    include_capability_limitations: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "period_mode", PeriodMode(self.period_mode))
        object.__setattr__(self, "comparison_mode", ComparisonMode(self.comparison_mode))
        object.__setattr__(self, "private_label_scope", PrivateLabelScope(self.private_label_scope))
        object.__setattr__(
            self,
            "signal_types",
            tuple(SignalType(item) for item in self.signal_types),
        )
        object.__setattr__(self, "limit", max(1, min(int(self.limit), 200)))


@dataclass(frozen=True)
class SignalFeedRow:
    """One surfaced deterministic signal or pattern."""

    signal_id: str
    signal_type: SignalType
    event_type: str
    event_family: str
    object_grain: str | None
    object_id: str | None
    category_id: str | None
    period: date | None
    reference_period: date | None
    comparison_type: str | None
    current_value: float | None
    reference_value: float | None
    delta_abs: float | None
    delta_pct: float | None
    delta_pp: float | None
    rule_id: str | None
    rule_version: str | None
    event_config_hash: str | None
    severity: str | None
    priority: int | None
    confidence: str | None
    comparison_quality: str | None
    private_label_scope: PrivateLabelScope
    status: SignalRowStatus
    provenance: dict[str, Any]


@dataclass(frozen=True)
class CapabilityLimitation:
    """A non-commercial limitation that must not appear in the signal list."""

    code: str
    message: str
    status: str = "LIMITATION"
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class SignalFeedResponse:
    """Product-safe signal feed response."""

    status: SignalFeedStatus
    request_scope: dict[str, Any]
    signals: tuple[SignalFeedRow, ...]
    deterministic_patterns: tuple[SignalFeedRow, ...]
    data_quality_alerts: tuple[SignalFeedRow, ...]
    capability_limitations: tuple[CapabilityLimitation, ...]
    limitations: tuple[str, ...]
    event_count: int
    surfaced_event_count: int
    excluded_event_counts: dict[str, int]
    mart_build_id: str | None
    analysis_run_ids: tuple[str, ...]
    source_revision_ids: tuple[str, ...]
    private_label_scope: PrivateLabelScope


class SignalFeedService:
    """Read confirmed event outputs and expose only product-approved signals."""

    def __init__(
        self,
        *,
        events_path: str | Path | None = None,
        event_rules_path: str | Path | None = None,
        mart_builds: tuple[MartBuildMetadata, ...] = (),
    ) -> None:
        self.events_path = Path(events_path) if events_path is not None else None
        self.event_rules_path = Path(event_rules_path) if event_rules_path is not None else None
        self.mart_builds = mart_builds

    def feed(self, request: SignalFeedRequest) -> SignalFeedResponse:
        """Return confirmed signals, separate quality alerts, and limitations."""

        mart_build_id = self._resolve_build_id(request)
        if self.events_path is None:
            return self._empty(
                request,
                mart_build_id,
                SignalFeedStatus.NOT_CONFIGURED,
                ("signal_events_path_not_configured",),
            )

        frame = _read_events(self.events_path)
        enabled_rule_count = _enabled_rule_count(self.event_rules_path)
        if frame.is_empty() or not frame.columns:
            reason = "no_enabled_event_rules" if enabled_rule_count == 0 else "no_confirmed_events"
            return self._empty(
                request,
                mart_build_id,
                SignalFeedStatus.NO_CONFIRMED_EVENTS,
                (reason,),
            )

        scoped = self._scope_frame(frame, request)
        limitations = list(_scope_limitations(frame, request))
        source_revision_ids = _source_revision_ids_for_build(mart_build_id, self.mart_builds)
        blocking_scope_limitations = _blocking_scope_limitations(frame, request)
        if blocking_scope_limitations:
            return self._empty(
                request,
                mart_build_id,
                SignalFeedStatus.NO_SURFACED_SIGNALS,
                blocking_scope_limitations,
            )
        rows: list[SignalFeedRow] = []
        excluded: dict[str, int] = {}
        for event in scoped.sort(_sort_columns(scoped)).to_dicts():
            classification = _classify_event(event)
            if classification is None:
                key = str(event.get("event_type") or event.get("event_family") or "UNKNOWN")
                excluded[key] = excluded.get(key, 0) + 1
                continue
            if classification not in request.signal_types:
                continue
            rows.append(_row(event, request, classification, mart_build_id, limitations, source_revision_ids))

        signals = tuple(row for row in rows if row.signal_type == SignalType.COMMERCIAL_SIGNAL)[: request.limit]
        patterns = tuple(row for row in rows if row.signal_type == SignalType.DETERMINISTIC_PATTERN)[: request.limit]
        quality = tuple(row for row in rows if row.signal_type == SignalType.DATA_QUALITY_ALERT)[: request.limit]
        capability_limitations = (
            tuple(_capability_limitations(request, limitations, excluded)) if request.include_capability_limitations else ()
        )
        status = SignalFeedStatus.READY if signals or patterns or quality else SignalFeedStatus.NO_CONFIRMED_EVENTS
        if scoped.height and not (signals or patterns or quality):
            status = SignalFeedStatus.NO_SURFACED_SIGNALS
        if limitations and status == SignalFeedStatus.READY:
            status = SignalFeedStatus.PARTIAL
        no_rows_limitation = (
            "no_surfaced_signals_in_scope"
            if scoped.height
            else "no_confirmed_events_in_scope"
        )
        return SignalFeedResponse(
            status=status,
            request_scope=_request_scope(request),
            signals=signals,
            deterministic_patterns=patterns,
            data_quality_alerts=quality,
            capability_limitations=capability_limitations,
            limitations=tuple(dict.fromkeys((*limitations, *(() if rows else (no_rows_limitation,))))),
            event_count=scoped.height,
            surfaced_event_count=len(signals) + len(patterns) + len(quality),
            excluded_event_counts=excluded,
            mart_build_id=mart_build_id,
            analysis_run_ids=_unique(scoped, "analysis_run_id") or _analysis_run_ids_for_build(
                mart_build_id,
                self.mart_builds,
            ),
            source_revision_ids=source_revision_ids,
            private_label_scope=request.private_label_scope,
        )

    def _resolve_build_id(self, request: SignalFeedRequest) -> str | None:
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
        return approved[0].mart_build_id if len(approved) == 1 else None

    def _scope_frame(self, frame: pl.DataFrame, request: SignalFeedRequest) -> pl.DataFrame:
        scoped = frame
        for column, value in (
            ("retailer_id", request.retailer_id),
            ("source_id", request.source_id),
        ):
            if column in scoped.columns:
                scoped = scoped.filter(pl.col(column) == value)
        if "period" in scoped.columns and request.date_from is not None:
            scoped = scoped.filter(pl.col("period") >= request.date_from)
        if "period" in scoped.columns and request.date_to is not None:
            scoped = scoped.filter(pl.col("period") <= request.date_to)
        if (
            request.comparison_mode != ComparisonMode.NONE
            and "comparison_type" in scoped.columns
        ):
            scoped = scoped.filter(pl.col("comparison_type") == request.comparison_mode.value)
        if "private_label_scope" in scoped.columns:
            scoped = scoped.filter(pl.col("private_label_scope") == request.private_label_scope.value)
        if request.entity_filters and "category" in scoped.columns:
            categories = request.entity_filters.get("category") or ()
            if categories:
                scoped = scoped.filter(pl.col("category").is_in(list(categories)))
        if request.entity_filters:
            for filter_key in ("manufacturer", "brand", "sku", "store"):
                values = request.entity_filters.get(filter_key) or ()
                if not values:
                    continue
                if filter_key in scoped.columns:
                    scoped = scoped.filter(pl.col(filter_key).is_in(list(values)))
                elif request.grain_id == filter_key and {"entity_type", "entity_id"} <= set(scoped.columns):
                    scoped = scoped.filter(
                        (pl.col("entity_type") == filter_key)
                        & pl.col("entity_id").is_in(list(values))
                    )
        if request.grain_id != "network" and "entity_type" in scoped.columns:
            scoped = scoped.filter(pl.col("entity_type") == request.grain_id)
        if request.entity_ids and "entity_id" in scoped.columns:
            scoped = scoped.filter(pl.col("entity_id").is_in(list(request.entity_ids)))
        return scoped

    def _empty(
        self,
        request: SignalFeedRequest,
        mart_build_id: str | None,
        status: SignalFeedStatus,
        limitations: tuple[str, ...],
    ) -> SignalFeedResponse:
        capability_limitations = (
            tuple(_capability_limitations(request, limitations, {})) if request.include_capability_limitations else ()
        )
        return SignalFeedResponse(
            status=status,
            request_scope=_request_scope(request),
            signals=(),
            deterministic_patterns=(),
            data_quality_alerts=(),
            capability_limitations=capability_limitations,
            limitations=limitations,
            event_count=0,
            surfaced_event_count=0,
            excluded_event_counts={},
            mart_build_id=mart_build_id,
            analysis_run_ids=_analysis_run_ids_for_build(mart_build_id, self.mart_builds),
            source_revision_ids=_source_revision_ids_for_build(mart_build_id, self.mart_builds),
            private_label_scope=request.private_label_scope,
        )


def _read_events(path: Path) -> pl.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Signal events path does not exist: {path}")
    if path.is_dir():
        return duckdb.sql("SELECT * FROM read_parquet(?)", params=[_duckdb_path(path)]).pl()
    return pl.read_parquet(path)


def _enabled_rule_count(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    rules = payload.get("event_rules") or payload.get("rules") or ()
    if not isinstance(rules, list):
        return None
    return sum(1 for rule in rules if isinstance(rule, dict) and rule.get("enabled", True))


def _classify_event(event: dict[str, Any]) -> SignalType | None:
    event_type = str(event.get("event_type") or "")
    family = str(event.get("event_family") or "")
    input_source = str(event.get("input_source") or "")
    if input_source == "quality" or family == "DATA_QUALITY":
        return SignalType.DATA_QUALITY_ALERT
    if event_type in NON_SURFACED_EVENT_TYPES or family in NON_SURFACED_EVENT_FAMILIES:
        return None
    if family in DETERMINISTIC_PATTERN_FAMILIES:
        return SignalType.DETERMINISTIC_PATTERN
    if family in COMMERCIAL_SIGNAL_FAMILIES:
        return SignalType.COMMERCIAL_SIGNAL
    return None


def _row(
    event: dict[str, Any],
    request: SignalFeedRequest,
    signal_type: SignalType,
    mart_build_id: str | None,
    limitations: list[str],
    source_revision_ids: tuple[str, ...],
) -> SignalFeedRow:
    missing_evidence = _json_field(event.get("missing_evidence"), [])
    status = SignalRowStatus.PARTIAL_EVIDENCE if missing_evidence or limitations else SignalRowStatus.READY
    comparison_quality = _optional_text(event.get("comparison_quality"))
    return SignalFeedRow(
        signal_id=str(event.get("event_id") or ""),
        signal_type=signal_type,
        event_type=str(event.get("event_type") or ""),
        event_family=str(event.get("event_family") or ""),
        object_grain=_optional_text(event.get("entity_type")),
        object_id=_optional_text(event.get("entity_id")),
        category_id=_optional_text(event.get("category")),
        period=_optional_date(event.get("period")),
        reference_period=_optional_date(event.get("reference_period")),
        comparison_type=_optional_text(event.get("comparison_type")),
        current_value=_optional_float(event.get("observed_value")),
        reference_value=_optional_float(event.get("reference_value")),
        delta_abs=_optional_float(event.get("delta_abs")),
        delta_pct=_optional_float(event.get("delta_pct")),
        delta_pp=_optional_float(event.get("delta_pp")),
        rule_id=_optional_text(event.get("event_rule_id")),
        rule_version=_optional_text(event.get("event_rule_version")),
        event_config_hash=_optional_text(event.get("event_config_hash")),
        severity=_optional_text(event.get("severity")),
        priority=_priority(event.get("severity")),
        confidence=_optional_text(event.get("confidence")),
        comparison_quality=comparison_quality,
        private_label_scope=request.private_label_scope,
        status=status,
        provenance=_provenance(event, request, mart_build_id, status, limitations, source_revision_ids),
    )


def _provenance(
    event: dict[str, Any],
    request: SignalFeedRequest,
    mart_build_id: str | None,
    status: SignalRowStatus,
    limitations: list[str],
    source_revision_ids: tuple[str, ...],
) -> dict[str, Any]:
    signal_type = _classify_event(event)
    return {
        "current_analytical_scope": _request_scope(request),
        "signal": {
            "signal_id": event.get("event_id"),
            "signal_type": signal_type.value if signal_type is not None else None,
            "event_type": event.get("event_type"),
            "event_family": event.get("event_family"),
            "status": status.value,
        },
        "object": {
            "grain_id": event.get("entity_type"),
            "entity_id": event.get("entity_id"),
            "category": event.get("category"),
        },
        "comparison": {
            "period": _date_text(event.get("period")),
            "reference_period": _date_text(event.get("reference_period")),
            "comparison_type": event.get("comparison_type"),
            "comparison_quality": event.get("comparison_quality"),
            "current_value": event.get("observed_value"),
            "reference_value": event.get("reference_value"),
            "delta_abs": event.get("delta_abs"),
            "delta_pct": event.get("delta_pct"),
            "delta_pp": event.get("delta_pp"),
        },
        "business_rule": {
            "event_rule_id": event.get("event_rule_id"),
            "event_rule_version": event.get("event_rule_version"),
            "event_config_hash": event.get("event_config_hash"),
            "thresholds": _json_field(event.get("thresholds"), {}),
            "trigger_values": _json_field(event.get("trigger_values"), {}),
            "observed_drivers": _json_field(event.get("observed_drivers"), []),
            "hypothesis_candidates": _json_field(event.get("hypothesis_candidates"), []),
            "missing_evidence": _json_field(event.get("missing_evidence"), []),
        },
        "lineage": {
            "analysis_run_id": event.get("analysis_run_id"),
            "mart_build_id": mart_build_id,
            "source_revision_ids": source_revision_ids,
            "rule_version": event.get("rule_version"),
            "metric_lineage": _json_field(event.get("metric_lineage"), {}),
            "benchmark_lineage": _json_field(event.get("benchmark_lineage"), {}),
        },
        "source_evidence": {
            "status": "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS",
            "source_row_ids": (),
        },
        "quality": {
            "severity": event.get("severity"),
            "confidence": event.get("confidence"),
            "comparison_quality": event.get("comparison_quality"),
            "limitations": tuple(limitations),
        },
        "missing_fields": ("source_row_ids",),
    }


def _scope_limitations(frame: pl.DataFrame, request: SignalFeedRequest) -> tuple[str, ...]:
    limitations: list[str] = []
    if "private_label_scope" not in frame.columns:
        limitations.append("event_private_label_scope_not_materialized")
    if request.grain_id != "network" and "entity_type" not in frame.columns:
        limitations.append("event_entity_scope_not_materialized")
    if (request.entity_filters or {}).get("category") and "category" not in frame.columns:
        limitations.append("event_category_scope_not_materialized")
    return tuple(limitations)


def _blocking_scope_limitations(frame: pl.DataFrame, request: SignalFeedRequest) -> tuple[str, ...]:
    limitations: list[str] = []
    columns = set(frame.columns)
    if "private_label_scope" not in columns and request.private_label_scope != PrivateLabelScope.INCLUDE:
        limitations.append("event_private_label_scope_not_materialized")
    filters = request.entity_filters or {}
    if filters.get("category") and "category" not in columns:
        limitations.append("event_category_scope_not_materialized")
    if request.grain_id != "network" and "entity_type" not in columns:
        limitations.append("event_entity_scope_not_materialized")
    if request.entity_ids and not {"entity_type", "entity_id"} <= columns:
        limitations.append("event_entity_scope_not_materialized")
    for filter_key in ("manufacturer", "brand", "sku", "store"):
        if not filters.get(filter_key):
            continue
        can_filter_named_column = filter_key in columns
        can_filter_entity_identity = request.grain_id == filter_key and {"entity_type", "entity_id"} <= columns
        if not can_filter_named_column and not can_filter_entity_identity:
            limitations.append(f"event_{filter_key}_scope_not_materialized")
    return tuple(limitations)


def _capability_limitations(
    request: SignalFeedRequest,
    limitations: tuple[str, ...] | list[str],
    excluded: dict[str, int],
) -> tuple[CapabilityLimitation, ...]:
    rows = [
        CapabilityLimitation(
            code=code,
            message=_limitation_message(code),
            provenance={"request_scope": _request_scope(request)},
        )
        for code in limitations
    ]
    for key, count in sorted(excluded.items()):
        code = f"event_type_not_surfaced:{key}"
        rows.append(
            CapabilityLimitation(
                code=code,
                message="Часть событий не выводится как пользовательский сигнал без отдельного бизнес-контракта.",
                provenance={"request_scope": _request_scope(request), "excluded_count": count},
            )
        )
    return tuple(rows)


def _limitation_message(code: str) -> str:
    return {
        "signal_events_path_not_configured": "Лента сигналов не подключена к подтверждённым событиям.",
        "no_enabled_event_rules": "Для выбранного источника нет включённых правил сигналов.",
        "no_confirmed_events": "Для выбранного среза нет подтверждённых событий.",
        "no_surfaced_signals_in_scope": "Для выбранного среза нет событий, разрешённых к показу как сигналы.",
        "no_confirmed_events_in_scope": "Для выбранного среза нет подтверждённых сигналов.",
        "event_private_label_scope_not_materialized": (
            "Материализованные события не содержат отдельного признака учёта ассортимента."
        ),
        "event_entity_scope_not_materialized": "Материализованные события не содержат подтверждённой детализации объекта.",
        "event_category_scope_not_materialized": "Материализованные события не содержат подтверждённого среза категории.",
        "event_manufacturer_scope_not_materialized": (
            "Материализованные события не содержат подтверждённого среза производителя."
        ),
        "event_brand_scope_not_materialized": "Материализованные события не содержат подтверждённого среза бренда.",
        "event_sku_scope_not_materialized": "Материализованные события не содержат подтверждённого среза SKU.",
        "event_store_scope_not_materialized": "Материализованные события не содержат подтверждённого среза ТТ.",
    }.get(code, code)


def _request_scope(request: SignalFeedRequest) -> dict[str, Any]:
    return {
        "retailer_id": request.retailer_id,
        "source_id": request.source_id,
        "period_mode": request.period_mode.value,
        "period_grain": request.period_grain,
        "date_from": request.date_from.isoformat() if request.date_from else None,
        "date_to": request.date_to.isoformat() if request.date_to else None,
        "comparison_mode": request.comparison_mode.value,
        "grain_id": request.grain_id,
        "entity_ids": request.entity_ids,
        "entity_filters": request.entity_filters or {},
        "private_label_scope": request.private_label_scope.value,
        "scope_identity_hash": scope_identity_hash(
            private_label_scope=request.private_label_scope,
            entity_filters=request.entity_filters,
        ),
    }


def _unique(frame: pl.DataFrame, column: str) -> tuple[str, ...]:
    if column not in frame.columns:
        return ()
    return tuple(sorted(str(item) for item in frame[column].drop_nulls().unique().to_list()))


def _analysis_run_ids_for_build(
    mart_build_id: str | None,
    mart_builds: tuple[MartBuildMetadata, ...],
) -> tuple[str, ...]:
    build = _build_for_id(mart_build_id, mart_builds)
    return build.analysis_run_ids if build is not None else ()


def _source_revision_ids_for_build(
    mart_build_id: str | None,
    mart_builds: tuple[MartBuildMetadata, ...],
) -> tuple[str, ...]:
    build = _build_for_id(mart_build_id, mart_builds)
    return build.source_revision_ids if build is not None else ()


def _build_for_id(
    mart_build_id: str | None,
    mart_builds: tuple[MartBuildMetadata, ...],
) -> MartBuildMetadata | None:
    if mart_build_id is None:
        return None
    for build in mart_builds:
        if build.mart_build_id == mart_build_id:
            return build
    return None


def _sort_columns(frame: pl.DataFrame) -> list[str]:
    return [
        column
        for column in ("severity", "event_type", "entity_type", "entity_id", "period")
        if column in frame.columns
    ]


def _json_field(value: object, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _optional_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value))


def _date_text(value: object) -> str | None:
    parsed = _optional_date(value)
    return parsed.isoformat() if parsed is not None else None


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, int | float | str):
        return float(value)
    raise TypeError(f"Expected numeric signal value, got {type(value).__name__}")


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _priority(value: object) -> int | None:
    return {
        "CRITICAL": 1,
        "HIGH": 2,
        "MEDIUM": 3,
        "LOW": 4,
        "INFO": 5,
    }.get(str(value or ""))


def _duckdb_path(path: Path) -> str:
    raw = path.as_posix()
    if path.is_dir():
        raw = f"{raw}/**/*.parquet"
    return raw
