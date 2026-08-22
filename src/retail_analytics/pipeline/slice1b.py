"""Thin Slice 1B tax, economics, quality, and reconciliation orchestrator."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from retail_analytics.economics.retailer_margin import (
    RetailerEconomicsResult,
    calculate_retailer_economics,
)
from retail_analytics.economics.tax import (
    TaxNormalizationResult,
    TaxRule,
    TaxRuleConfigResult,
    load_tax_rule_config,
    normalize_tax,
)
from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.checks import (
    ReconciliationResult,
    reconcile_economics,
    run_quality_checks,
)
from retail_analytics.quality.report import QualityReport


@dataclass(frozen=True)
class Slice1BResult:
    context: AnalysisContext
    enriched_frame: pl.DataFrame
    tax_result: TaxNormalizationResult
    economics_result: RetailerEconomicsResult
    quality_report: QualityReport
    reconciliation_result: ReconciliationResult
    tax_config_hash: str
    economics_rule_version: str


def run_slice1b_normalization(
    *,
    canonical_frame: pl.DataFrame,
    tax_rules: Sequence[TaxRule] | str | Path,
    context: AnalysisContext,
    reconciliation_tolerance: float = 1e-9,
) -> Slice1BResult:
    """Enrich canonical rows without aggregation, repair, or source mutation."""
    tax_config_result = _resolve_tax_rules(tax_rules)
    resolved_rules = tax_config_result.rules
    tax_result = normalize_tax(canonical_frame, resolved_rules, context)
    economics_result = calculate_retailer_economics(tax_result.frame, context)
    quality_report = tax_config_result.quality_report.extend(tax_result.quality_report).extend(
        economics_result.quality_report
    ).extend(
        run_quality_checks(economics_result.frame, context)
    )
    reconciliation_result = reconcile_economics(
        canonical_frame,
        economics_result.frame,
        context,
        tolerance=reconciliation_tolerance,
    )
    quality_report = quality_report.extend(reconciliation_result.quality_report)
    return Slice1BResult(
        context=context,
        enriched_frame=economics_result.frame,
        tax_result=tax_result,
        economics_result=economics_result,
        quality_report=quality_report,
        reconciliation_result=reconciliation_result,
        tax_config_hash=tax_result.tax_config_hash,
        economics_rule_version=economics_result.economics_rule_version,
    )


def _resolve_tax_rules(tax_rules: Sequence[TaxRule] | str | Path) -> TaxRuleConfigResult:
    if isinstance(tax_rules, (str, Path)):
        return load_tax_rule_config(tax_rules)
    return TaxRuleConfigResult(tuple(tax_rules), QualityReport())
