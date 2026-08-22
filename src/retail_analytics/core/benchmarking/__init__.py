"""Competitor benchmarking foundation."""

from retail_analytics.core.benchmarking.contracts import (
    BenchmarkFeatureResult,
    BenchmarkRequest,
    PeerGroupResult,
    PeerRule,
    PriceSegmentResult,
    PriceSegmentRule,
    Slice3BenchmarkingResult,
)
from retail_analytics.core.benchmarking.features import calculate_benchmark_features
from retail_analytics.core.benchmarking.peer_groups import build_peer_groups
from retail_analytics.core.benchmarking.price_segments import build_price_segments
from retail_analytics.core.benchmarking.registry import (
    load_peer_rule_config,
    load_price_segment_rule_config,
)

__all__ = [
    "BenchmarkFeatureResult",
    "BenchmarkRequest",
    "PeerGroupResult",
    "PeerRule",
    "PriceSegmentResult",
    "PriceSegmentRule",
    "Slice3BenchmarkingResult",
    "build_peer_groups",
    "build_price_segments",
    "calculate_benchmark_features",
    "load_peer_rule_config",
    "load_price_segment_rule_config",
]
