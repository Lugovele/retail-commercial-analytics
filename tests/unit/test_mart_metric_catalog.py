from __future__ import annotations

from pathlib import Path

import pytest

from retail_analytics.mart import (
    CatalogIssueSeverity,
    DashboardGroup,
    MetricAvailabilityStatus,
    MetricFormat,
    PrivateLabelScope,
    PrivateMetricCatalogOverride,
    PublicMetricCatalogEntry,
    RangeAggregationStrategy,
    load_private_metric_catalog_overrides,
    load_public_metric_catalog,
    merge_metric_catalog,
    validate_metric_catalog,
)


def test_public_catalog_loads_generic_metadata() -> None:
    catalog = load_public_metric_catalog("config/public/dashboard_metric_catalog.yaml")

    concepts = {entry.metric_concept for entry in catalog}
    assert {"revenue", "units", "retailer_margin_pct", "distribution", "velocity"} <= concepts
    assert all("retailer_a" not in entry.default_display_label for entry in catalog)


def test_private_override_merges_with_public_defaults() -> None:
    merged = merge_metric_catalog(
        (_public("revenue"),),
        (
            PrivateMetricCatalogOverride(
                retailer_id="retailer_a",
                source_id="source_a",
                metric_definition_id="retailer_a.network.revenue.v1",
                metric_definition_version="v1",
                metric_concept="revenue",
                display_label="Net revenue",
                grain_support=("network",),
                period_support=("month",),
                metric_config_hash="hash_a",
                rule_version="rules_v1",
            ),
        ),
        retailer_id="retailer_a",
        source_id="source_a",
    )

    assert len(merged) == 1
    assert merged[0].display_label == "Net revenue"
    assert merged[0].format == MetricFormat.CURRENCY
    assert merged[0].range_aggregation_strategy == RangeAggregationStrategy.SUM_AVAILABLE_PERIODS
    assert merged[0].cross_retailer_comparable is False


def test_private_override_for_unknown_concept_is_invalid() -> None:
    issues = validate_metric_catalog(
        (_public("revenue"),),
        (
            PrivateMetricCatalogOverride(
                retailer_id="retailer_a",
                source_id="source_a",
                metric_definition_id="retailer_a.unknown.v1",
                metric_definition_version="v1",
                metric_concept="unknown_metric",
            ),
        ),
    )

    assert [issue.issue_code for issue in issues] == ["private_override_unknown_concept"]
    assert issues[0].severity == CatalogIssueSeverity.ERROR


def test_duplicate_private_identity_is_invalid() -> None:
    override = PrivateMetricCatalogOverride(
        retailer_id="retailer_a",
        source_id="source_a",
        metric_definition_id="retailer_a.revenue.v1",
        metric_definition_version="v1",
        metric_concept="revenue",
        metric_config_hash="hash_a",
        rule_version="rules_v1",
    )

    issues = validate_metric_catalog((_public("revenue"),), (override, override))

    assert "duplicate_private_metric_identity" in {issue.issue_code for issue in issues}


def test_invalid_grain_and_comparison_are_reported() -> None:
    issues = validate_metric_catalog(
        (_public("revenue"),),
        (
            PrivateMetricCatalogOverride(
                retailer_id="retailer_a",
                source_id="source_a",
                metric_definition_id="retailer_a.revenue.v1",
                metric_definition_version="v1",
                metric_concept="revenue",
                grain_support=("unsupported_grain",),
                period_support=("month",),
                comparison_support=("BAD_MODE",),
            ),
        ),
    )

    assert {"unknown_grain", "unsupported_comparison_mode"} <= {issue.issue_code for issue in issues}


def test_private_override_cannot_expand_period_only_strategy() -> None:
    issues = validate_metric_catalog(
        (
            PublicMetricCatalogEntry(
                metric_concept="distribution",
                default_display_label="Distribution",
                description="Period-level distribution.",
                format=MetricFormat.PERCENT,
                dashboard_group=DashboardGroup.DISTRIBUTION,
                default_range_aggregation_strategy=RangeAggregationStrategy.PERIOD_ONLY,
            ),
        ),
        (
            PrivateMetricCatalogOverride(
                retailer_id="retailer_a",
                source_id="source_a",
                metric_definition_id="retailer_a.distribution.v1",
                metric_definition_version="v1",
                metric_concept="distribution",
                range_aggregation_strategy=RangeAggregationStrategy.RATIO_OF_SUMS,
            ),
        ),
    )

    assert "private_override_claims_unsupported_range_capability" in {
        issue.issue_code for issue in issues
    }


def test_partial_status_is_preserved() -> None:
    merged = merge_metric_catalog(
        (_public("velocity"),),
        (
            PrivateMetricCatalogOverride(
                retailer_id="retailer_a",
                source_id=None,
                metric_definition_id="retailer_a.velocity.v1",
                metric_definition_version="v1",
                metric_concept="velocity",
                availability_status=MetricAvailabilityStatus.PARTIAL,
                limitations=("period_only",),
                grain_support=("sku",),
                period_support=("month",),
            ),
        ),
        retailer_id="retailer_a",
    )

    assert merged[0].availability_status == MetricAvailabilityStatus.PARTIAL
    assert "period_only" in merged[0].limitations


def test_catalog_loader_reads_private_override_yaml(tmp_path: Path) -> None:
    path = tmp_path / "metric_catalog.yaml"
    path.write_text(
        """
overrides:
  - retailer_id: retailer_a
    source_id: source_a
    metric_definition_id: retailer_a.revenue.v1
    metric_definition_version: v1
    metric_concept: revenue
    grain_support: [network]
    period_support: [month]
    availability_status: READY
""",
        encoding="utf-8",
    )

    overrides = load_private_metric_catalog_overrides(path)

    assert overrides[0].retailer_id == "retailer_a"
    assert overrides[0].availability_status == MetricAvailabilityStatus.READY
    assert overrides[0].private_label_scope_support == ()


def test_private_override_without_scope_support_does_not_expand_public_restriction(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metric_catalog.yaml"
    path.write_text(
        """
overrides:
  - retailer_id: retailer_a
    source_id: source_a
    metric_definition_id: retailer_a.revenue.v1
    metric_definition_version: v1
    metric_concept: revenue
    grain_support: [network]
    period_support: [month]
    availability_status: READY
""",
        encoding="utf-8",
    )
    public = (
        PublicMetricCatalogEntry(
            metric_concept="revenue",
            default_display_label="Revenue",
            description="Synthetic catalog entry.",
            format=MetricFormat.CURRENCY,
            dashboard_group=DashboardGroup.SALES,
            default_range_aggregation_strategy=RangeAggregationStrategy.SUM_AVAILABLE_PERIODS,
            private_label_scope_support=(PrivateLabelScope.INCLUDE,),
        ),
    )

    merged = merge_metric_catalog(
        public,
        load_private_metric_catalog_overrides(path),
        retailer_id="retailer_a",
        source_id="source_a",
    )

    assert merged[0].private_label_scope_support == (PrivateLabelScope.INCLUDE,)


def test_merge_raises_on_invalid_catalog() -> None:
    with pytest.raises(ValueError, match="unknown metric_concept"):
        merge_metric_catalog(
            (_public("revenue"),),
            (
                PrivateMetricCatalogOverride(
                    retailer_id="retailer_a",
                    source_id="source_a",
                    metric_definition_id="retailer_a.unknown.v1",
                    metric_definition_version="v1",
                    metric_concept="unknown_metric",
                ),
            ),
            retailer_id="retailer_a",
        )


def test_retailer_and_source_isolation() -> None:
    public = (_public("revenue"),)
    overrides = (
        PrivateMetricCatalogOverride(
            retailer_id="retailer_a",
            source_id="source_a",
            metric_definition_id="retailer_a.source_a.revenue.v1",
            metric_definition_version="v1",
            metric_concept="revenue",
        ),
        PrivateMetricCatalogOverride(
            retailer_id="retailer_a",
            source_id="source_b",
            metric_definition_id="retailer_a.source_b.revenue.v1",
            metric_definition_version="v1",
            metric_concept="revenue",
        ),
        PrivateMetricCatalogOverride(
            retailer_id="retailer_b",
            source_id="source_a",
            metric_definition_id="retailer_b.source_a.revenue.v1",
            metric_definition_version="v1",
            metric_concept="revenue",
        ),
    )

    merged = merge_metric_catalog(public, overrides, retailer_id="retailer_a", source_id="source_a")

    assert [entry.metric_definition_id for entry in merged] == ["retailer_a.source_a.revenue.v1"]


def _public(
    concept: str,
    strategy: RangeAggregationStrategy = RangeAggregationStrategy.SUM_AVAILABLE_PERIODS,
) -> PublicMetricCatalogEntry:
    return PublicMetricCatalogEntry(
        metric_concept=concept,
        default_display_label=concept,
        description="Synthetic catalog entry.",
        format=MetricFormat.CURRENCY,
        dashboard_group=DashboardGroup.SALES,
        default_range_aggregation_strategy=strategy,
        default_comparison_support=("NONE", "YOY", "MOM", "PREVIOUS_AVAILABLE"),
    )
