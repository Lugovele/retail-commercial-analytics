"""Benchmarking contracts for peer groups, price segments, and features."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import polars as pl

from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityReport

PeerLevel = Literal["BROAD_CATEGORY", "DIRECT_COMPARABLE"]
DirectPeerMode = Literal["RULE_POOL_ONLY", "DIRECT_ONLY", "DIRECT_PLUS_RULE_POOL"]
SelfInclusion = Literal["EXCLUDE_SELF", "INCLUDE_SELF"]
PeriodSelectionMode = Literal["LATEST_AVAILABLE", "EXPLICIT"]


@dataclass(frozen=True)
class PriceSegmentRule:
    rule_id: str
    rule_version: str
    retailer_id: str
    segments: tuple[str, ...]
    price_metric_name: str = "weighted_shelf_price_vat"
    min_segment_population: int = 3
    source_id: str | None = None


@dataclass(frozen=True)
class PeerRule:
    rule_id: str
    rule_version: str
    retailer_id: str
    peer_level: PeerLevel
    required_dimensions: tuple[str, ...]
    optional_dimensions: tuple[str, ...] = ()
    filters: dict[str, str] | None = None
    fallback_behavior: str = "REPORT_EMPTY"
    direct_peer_mode: DirectPeerMode = "DIRECT_ONLY"
    self_inclusion: SelfInclusion = "EXCLUDE_SELF"
    top_n: int = 10
    ranking_metrics: tuple[str, ...] = ("revenue_net", "units", "units_per_selling_store")
    source_id: str | None = None


@dataclass(frozen=True)
class BenchmarkRequest:
    benchmark_period: date | None = None
    period_selection_mode: PeriodSelectionMode = "LATEST_AVAILABLE"


@dataclass(frozen=True)
class PriceSegmentResult:
    price_segments: pl.DataFrame
    quality_report: QualityReport
    price_segment_config_hash: str


@dataclass(frozen=True)
class PeerGroupResult:
    peer_groups: pl.DataFrame
    quality_report: QualityReport
    peer_config_hash: str


@dataclass(frozen=True)
class BenchmarkFeatureResult:
    benchmark_features: pl.DataFrame
    quality_report: QualityReport


@dataclass(frozen=True)
class Slice3BenchmarkingResult:
    context: AnalysisContext
    price_segments: pl.DataFrame
    peer_groups: pl.DataFrame
    benchmark_features: pl.DataFrame
    quality_report: QualityReport
    peer_config_hash: str
    price_segment_config_hash: str
