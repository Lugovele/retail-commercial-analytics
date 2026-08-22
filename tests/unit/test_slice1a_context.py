import pytest

from retail_analytics.pipeline.context import AnalysisContext


def test_analysis_context_requires_retailer_and_source():
    with pytest.raises(ValueError):
        AnalysisContext("run_a", "", "source_a", "v1", "rules_v1")

def test_analysis_context_preserves_rule_version():
    context = AnalysisContext("run_a", "retailer_a", "source_a", "v1", "rules_v1")
    assert context.rule_version == "rules_v1"