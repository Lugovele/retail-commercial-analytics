from retail_analytics.mart import RangeAggregationStrategy, range_strategy_for_metric


def test_distribution_and_velocity_are_period_only_without_components() -> None:
    assert range_strategy_for_metric(aggregation="ratio_of_sums", metric_concept="numeric_distribution") == RangeAggregationStrategy.PERIOD_ONLY
    assert range_strategy_for_metric(aggregation="ratio_of_sums", metric_concept="units_per_selling_store") == RangeAggregationStrategy.PERIOD_ONLY


def test_shares_are_period_only_without_components() -> None:
    assert range_strategy_for_metric(aggregation="share", metric_concept="category_units_share") == RangeAggregationStrategy.PERIOD_ONLY


def test_abc_defaults_to_period_only() -> None:
    assert range_strategy_for_metric(aggregation="classification", metric_concept="abc_class") == RangeAggregationStrategy.PERIOD_ONLY


def test_distribution_and_velocity_without_components_are_period_only() -> None:
    assert range_strategy_for_metric(aggregation="ratio_of_sums", metric_concept="numeric_distribution") == RangeAggregationStrategy.PERIOD_ONLY
    assert range_strategy_for_metric(aggregation="ratio_of_sums", metric_concept="units_per_selling_store") == RangeAggregationStrategy.PERIOD_ONLY


def test_share_without_component_context_is_period_only() -> None:
    assert range_strategy_for_metric(aggregation="share", metric_concept="category_revenue_share") == RangeAggregationStrategy.PERIOD_ONLY

