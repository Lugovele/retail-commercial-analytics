from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from retail_analytics.mart import (
    ComparisonMode,
    MartBuildMetadata,
    MartBuildStatus,
    PeriodMode,
    PrivateLabelScope,
    SignalFeedRequest,
    SignalFeedService,
    SignalFeedStatus,
    SignalType,
)


def test_signal_feed_surfaces_only_confirmed_approved_events(tmp_path: Path) -> None:
    service = _service(tmp_path, _events())

    response = service.feed(_request())

    assert response.status == SignalFeedStatus.PARTIAL
    assert response.event_count == 3
    assert response.surfaced_event_count == 2
    assert [row.signal_type for row in response.signals] == [SignalType.COMMERCIAL_SIGNAL]
    assert [row.signal_type for row in response.deterministic_patterns] == [SignalType.DETERMINISTIC_PATTERN]
    assert "PROMO_LIKE_PATTERN" in response.excluded_event_counts
    assert any(item.code == "event_private_label_scope_not_materialized" for item in response.capability_limitations)


def test_signal_feed_keeps_capability_limitations_out_of_commercial_rows(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        _events(
            (
                _event("event_portfolio", "ABC_CLASS_CHANGE", "PORTFOLIO"),
                _event("event_benchmark", "PEER_OUTPERFORMANCE", "BENCHMARK"),
            )
        ),
    )

    response = service.feed(_request())

    assert response.signals == ()
    assert response.deterministic_patterns == ()
    assert response.status == SignalFeedStatus.NO_SURFACED_SIGNALS
    assert response.excluded_event_counts == {"ABC_CLASS_CHANGE": 1, "PEER_OUTPERFORMANCE": 1}
    assert {item.code for item in response.capability_limitations} >= {
        "event_type_not_surfaced:ABC_CLASS_CHANGE",
        "event_type_not_surfaced:PEER_OUTPERFORMANCE",
    }


def test_signal_feed_filters_scope_period_comparison_and_entity(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        _events(
            (
                _event("event_a", "MATERIAL_REVENUE_DECLINE", "GROWTH_DECLINE", entity_id="sku_a"),
                _event("event_b", "MATERIAL_REVENUE_DECLINE", "GROWTH_DECLINE", entity_id="sku_b"),
                _event(
                    "event_other_period",
                    "MATERIAL_REVENUE_DECLINE",
                    "GROWTH_DECLINE",
                    entity_id="sku_a",
                    period=date(2026, 2, 1),
                ),
            )
        ),
    )

    response = service.feed(
        _request(
            grain_id="sku",
            entity_ids=("sku_b",),
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert [row.signal_id for row in response.signals] == ["event_b"]
    assert response.signals[0].object_grain == "sku"
    assert response.signals[0].object_id == "sku_b"


def test_signal_feed_preserves_private_label_scope_when_materialized(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        _events(
            (
                _event("event_include", "MATERIAL_UNITS_GROWTH", "GROWTH_DECLINE", private_label_scope="INCLUDE"),
                _event("event_exclude", "MATERIAL_UNITS_GROWTH", "GROWTH_DECLINE", private_label_scope="EXCLUDE"),
            ),
            include_private_label_scope=True,
        ),
    )

    response = service.feed(_request(private_label_scope=PrivateLabelScope.EXCLUDE))

    assert [row.signal_id for row in response.signals] == ["event_exclude"]
    assert response.signals[0].private_label_scope == PrivateLabelScope.EXCLUDE
    assert "event_private_label_scope_not_materialized" not in response.limitations


def test_signal_feed_blocks_unmaterialized_non_include_private_label_scope(tmp_path: Path) -> None:
    service = _service(tmp_path, _events())

    response = service.feed(_request(private_label_scope=PrivateLabelScope.EXCLUDE))

    assert response.status == SignalFeedStatus.NO_SURFACED_SIGNALS
    assert response.signals == ()
    assert response.deterministic_patterns == ()
    assert response.limitations == ("event_private_label_scope_not_materialized",)


def test_signal_feed_blocks_filters_that_cannot_be_honored(tmp_path: Path) -> None:
    service = _service(tmp_path, _events())

    response = service.feed(
        SignalFeedRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_filters={"manufacturer": ("manufacturer_a",)},
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert response.status == SignalFeedStatus.NO_SURFACED_SIGNALS
    assert response.signals == ()
    assert response.deterministic_patterns == ()
    assert response.limitations == ("event_manufacturer_scope_not_materialized",)


def test_signal_feed_blocks_missing_category_scope_identity(tmp_path: Path) -> None:
    service = _service(tmp_path, _events().drop("category"))

    response = service.feed(
        SignalFeedRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="network",
            entity_filters={"category": ("category_a",)},
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert response.status == SignalFeedStatus.NO_SURFACED_SIGNALS
    assert response.signals == ()
    assert response.limitations == ("event_category_scope_not_materialized",)


def test_signal_feed_blocks_missing_grain_identity(tmp_path: Path) -> None:
    service = _service(tmp_path, _events().drop("entity_type"))

    response = service.feed(_request(grain_id="sku"))

    assert response.status == SignalFeedStatus.NO_SURFACED_SIGNALS
    assert response.signals == ()
    assert response.limitations == ("event_entity_scope_not_materialized",)


def test_signal_feed_blocks_entity_ids_without_entity_identity(tmp_path: Path) -> None:
    service = _service(tmp_path, _events().drop("entity_id"))

    response = service.feed(_request(entity_ids=("sku_a",)))

    assert response.status == SignalFeedStatus.NO_SURFACED_SIGNALS
    assert response.signals == ()
    assert response.limitations == ("event_entity_scope_not_materialized",)


def test_signal_feed_can_honor_filter_matching_requested_object_grain(tmp_path: Path) -> None:
    service = _service(tmp_path, _events())

    response = service.feed(
        SignalFeedRequest(
            retailer_id="retailer_a",
            source_id="source_a",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 1),
            period_mode=PeriodMode.SINGLE_PERIOD,
            period_grain="month",
            grain_id="sku",
            entity_filters={"sku": ("sku_a",)},
            comparison_mode=ComparisonMode.YOY,
        )
    )

    assert [row.object_id for row in response.signals] == ["sku_a"]
    assert "event_category_scope_not_materialized" not in response.limitations
    assert "event_sku_scope_not_materialized" not in response.limitations


def test_signal_feed_empty_confirmed_events_is_valid_state(tmp_path: Path) -> None:
    events_path = tmp_path / "empty_events.parquet"
    pl.DataFrame().write_parquet(events_path)
    rules_path = tmp_path / "event_rules.yaml"
    rules_path.write_text(
        """
event_rules:
  - event_rule_id: retailer_a.revenue.v1
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    service = SignalFeedService(events_path=events_path, event_rules_path=rules_path, mart_builds=(_build(),))

    response = service.feed(_request())

    assert response.status == SignalFeedStatus.NO_CONFIRMED_EVENTS
    assert response.signals == ()
    assert response.deterministic_patterns == ()
    assert response.limitations == ("no_confirmed_events",)
    assert response.capability_limitations[0].code == "no_confirmed_events"


def test_signal_feed_not_configured_is_separate_from_empty_feed() -> None:
    service = SignalFeedService(mart_builds=(_build(),))

    response = service.feed(_request())

    assert response.status == SignalFeedStatus.NOT_CONFIGURED
    assert response.signals == ()
    assert response.deterministic_patterns == ()
    assert response.limitations == ("signal_events_path_not_configured",)


def test_signal_provenance_carries_rule_trigger_and_lineage_without_recommendations(tmp_path: Path) -> None:
    service = _service(tmp_path, _events())

    response = service.feed(_request())
    provenance = response.signals[0].provenance

    assert provenance["business_rule"]["event_rule_id"] == "rule_a"
    assert provenance["business_rule"]["thresholds"] == {"delta_pct": {"operator": "lte", "value": -0.1}}
    assert provenance["business_rule"]["trigger_values"]["delta_pct"] == -0.2
    assert provenance["lineage"]["metric_lineage"]["metric_definition_id"] == "metric_a"
    assert provenance["source_evidence"]["status"] == "PARTIAL_AGGREGATED_FACT_NO_ROW_IDS"
    assert "recommendation" not in json.dumps(provenance).lower()
    assert "action" not in json.dumps(provenance).lower()


def _service(tmp_path: Path, events: pl.DataFrame) -> SignalFeedService:
    events_path = tmp_path / "events.parquet"
    events.write_parquet(events_path)
    return SignalFeedService(events_path=events_path, mart_builds=(_build(),))


def _request(
    *,
    grain_id: str = "network",
    entity_ids: tuple[str, ...] = (),
    comparison_mode: ComparisonMode = ComparisonMode.YOY,
    private_label_scope: PrivateLabelScope = PrivateLabelScope.INCLUDE,
) -> SignalFeedRequest:
    return SignalFeedRequest(
        retailer_id="retailer_a",
        source_id="source_a",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 1),
        period_mode=PeriodMode.SINGLE_PERIOD,
        period_grain="month",
        grain_id=grain_id,
        entity_ids=entity_ids,
        comparison_mode=comparison_mode,
        private_label_scope=private_label_scope,
    )


def _build() -> MartBuildMetadata:
    return MartBuildMetadata(
        mart_build_id="build_a",
        built_at=datetime(2026, 1, 15, tzinfo=UTC),
        build_version="mart.v1",
        code_version="test",
        retailer_id="retailer_a",
        source_ids=("source_a",),
        source_revision_ids=("revision_a",),
        analysis_run_ids=("analysis_a",),
        metric_config_hashes=("hash_a",),
        rule_versions=("rules_v1",),
        status=MartBuildStatus.APPROVED,
        period_grain="month",
        period_start=date(2025, 1, 1),
        period_end=date(2026, 1, 31),
    )


def _events(
    rows: tuple[dict[str, object], ...] | None = None,
    *,
    include_private_label_scope: bool = False,
) -> pl.DataFrame:
    raw_rows = rows or (
        _event("event_a", "MATERIAL_REVENUE_DECLINE", "GROWTH_DECLINE"),
        _event("event_b", "PRICE_PRESSURE_PATTERN", "PATTERN_CANDIDATE"),
        _event("event_promo", "PROMO_LIKE_PATTERN", "PATTERN_CANDIDATE"),
    )
    if not include_private_label_scope:
        raw_rows = tuple({key: value for key, value in row.items() if key != "private_label_scope"} for row in raw_rows)
    return pl.DataFrame(raw_rows)


def _event(
    event_id: str,
    event_type: str,
    event_family: str,
    *,
    entity_id: str = "sku_a",
    period: date = date(2026, 1, 1),
    private_label_scope: str = "INCLUDE",
) -> dict[str, object]:
    return {
        "analysis_run_id": "analysis_a",
        "retailer_id": "retailer_a",
        "source_id": "source_a",
        "rule_version": "rules_v1",
        "event_id": event_id,
        "event_rule_id": "rule_a",
        "event_rule_version": "v1",
        "event_config_hash": "event_hash_a",
        "event_type": event_type,
        "event_family": event_family,
        "entity_type": "sku",
        "entity_id": entity_id,
        "category": "category_a",
        "period": period,
        "reference_period": date(2025, 1, 1),
        "comparison_type": "YOY",
        "input_source": "comparison",
        "feature_name": "revenue",
        "observed_value": 80.0,
        "reference_value": 100.0,
        "delta_abs": -20.0,
        "delta_pct": -0.2,
        "delta_pp": None,
        "thresholds": json.dumps({"delta_pct": {"operator": "lte", "value": -0.1}}, sort_keys=True),
        "trigger_values": json.dumps({"delta_pct": -0.2}, sort_keys=True),
        "severity": "HIGH",
        "confidence": "HIGH",
        "observed_drivers": json.dumps(["revenue_delta_pct"]),
        "hypothesis_candidates": json.dumps([]),
        "missing_evidence": json.dumps([]),
        "metric_lineage": json.dumps({"metric_definition_id": "metric_a"}, sort_keys=True),
        "benchmark_lineage": json.dumps({}, sort_keys=True),
        "private_label_scope": private_label_scope,
    }
