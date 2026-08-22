"""Generic retailer economics calculations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from retail_analytics.pipeline.context import AnalysisContext
from retail_analytics.quality.report import QualityIssue, QualityReport


@dataclass(frozen=True)
class RetailerEconomicsResult:
    frame: pl.DataFrame
    quality_report: QualityReport
    economics_rule_version: str


def calculate_retailer_economics(frame: pl.DataFrame, context: AnalysisContext) -> RetailerEconomicsResult:
    """Append row-level economics without aggregating or mutating source gross values."""
    required = {"revenue_net", "input_price_net", "shelf_price_net", "units"}
    missing_columns = required.difference(frame.columns)
    if missing_columns:
        issues = tuple(
            QualityIssue("missing_economics_column", "FATAL", frame.height, (), f"Missing column: {column}", column)
            for column in sorted(missing_columns)
        )
        return RetailerEconomicsResult(frame.clone(), QualityReport(issues), context.rule_version)

    input_cost_net: list[float | None] = []
    margin_abs: list[float | None] = []
    margin_pct: list[float | None] = []
    markup_pct: list[float | None] = []
    quality_classes: list[str] = []
    realized_price_vat: list[float | None] = []
    shelf_price_delta_vat: list[float | None] = []
    issues: list[QualityIssue] = []

    for row_number, row in enumerate(frame.to_dicts()):
        trace = _trace(row, row_number)
        units = row.get("units")
        revenue_vat = row.get("revenue_vat")
        revenue_net = row.get("revenue_net")
        input_net = row.get("input_price_net")
        shelf_net = row.get("shelf_price_net")
        shelf_vat = row.get("shelf_price_vat")

        quality_classes.append(_classify_signs(units, revenue_vat))
        realized = revenue_vat / units if units is not None and revenue_vat is not None and units > 0 else None
        realized_price_vat.append(realized)
        shelf_price_delta_vat.append((realized - shelf_vat) if realized is not None and shelf_vat is not None else None)

        cost = input_net * units if input_net is not None and units is not None else None
        margin = revenue_net - cost if revenue_net is not None and cost is not None else None
        input_cost_net.append(cost)
        margin_abs.append(margin)

        if revenue_net == 0 and margin is not None:
            issues.append(QualityIssue("zero_revenue_denominator", "WARNING", 1, (trace,), "Margin percent denominator is zero.", "revenue_net"))
            margin_pct.append(None)
        else:
            margin_pct.append(margin / revenue_net if margin is not None and revenue_net is not None else None)

        if input_net == 0 and shelf_net is not None:
            issues.append(QualityIssue("zero_input_price_denominator", "WARNING", 1, (trace,), "Markup percent denominator is zero.", "input_price_net"))
            markup_pct.append(None)
        else:
            markup_pct.append((shelf_net - input_net) / input_net if shelf_net is not None and input_net is not None else None)

    enriched = frame.with_columns(
        pl.Series("input_cost_net", input_cost_net, dtype=pl.Float64),
        pl.Series("retailer_margin_abs", margin_abs, dtype=pl.Float64),
        pl.Series("retailer_margin_pct", margin_pct, dtype=pl.Float64),
        pl.Series("retailer_markup_pct", markup_pct, dtype=pl.Float64),
        pl.Series("business_quality_class", quality_classes, dtype=pl.String),
        pl.Series("realized_price_vat", realized_price_vat, dtype=pl.Float64),
        pl.Series("shelf_price_delta_vat", shelf_price_delta_vat, dtype=pl.Float64),
    )
    return RetailerEconomicsResult(enriched, QualityReport(tuple(issues)), context.rule_version)


def aggregate_margin_pct(frame: pl.DataFrame) -> float | None:
    """Aggregate margin percent as ratio of sums, never mean of row percentages."""
    revenue = frame.get_column("revenue_net").sum()
    margin = frame.get_column("retailer_margin_abs").sum()
    if revenue == 0:
        return None
    return margin / revenue


def _classify_signs(units: Any, revenue_vat: Any) -> str:
    if units is None or revenue_vat is None:
        return "SUSPICIOUS"
    if units >= 0 and revenue_vat >= 0:
        return "SALE"
    if units < 0 and revenue_vat < 0:
        return "RETURN_OR_CORRECTION"
    return "SUSPICIOUS"


def _trace(row: dict[str, Any], fallback: int) -> int:
    value = row.get("source_row_number")
    return int(value) if isinstance(value, int) else fallback
