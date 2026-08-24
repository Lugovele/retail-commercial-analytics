from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

CAPABILITY_MATRIX_PATH = Path("config/public/dashboard_capability_matrix.yaml")
PROVENANCE_MATRIX_PATH = Path("config/public/dashboard_provenance_coverage.yaml")


def test_provenance_coverage_loads_required_contract_fields() -> None:
    rows = _provenance_rows()
    required = {
        "concept_id",
        "fact_type",
        "coverage_status",
        "scope",
        "definition",
        "components",
        "comparison",
        "rule",
        "run",
        "source_evidence",
        "quality",
        "missing_fields",
        "UI_provenance_supported",
    }

    assert rows
    assert all(required <= set(row) for row in rows)
    assert len({row["concept_id"] for row in rows}) == len(rows)


def test_provenance_coverage_matches_dashboard_capabilities() -> None:
    capabilities = {row["concept_id"]: row for row in _capability_rows()}
    provenance = {row["concept_id"]: row for row in _provenance_rows()}

    assert set(provenance) == set(capabilities)
    for concept, capability in capabilities.items():
        row = provenance[concept]
        assert row["fact_type"] == capability["backend_fact_source"]
        if capability["availability_status"] in {"READY", "PARTIAL"}:
            assert row["coverage_status"] in {"COMPLETE", "PARTIAL"}
        if capability["availability_status"] == "NOT_AVAILABLE":
            assert row["coverage_status"] == "NOT_APPLICABLE"


def test_capability_matrix_provenance_flag_matches_audited_ui_support() -> None:
    capabilities = {row["concept_id"]: row for row in _capability_rows()}
    provenance = {row["concept_id"]: row for row in _provenance_rows()}

    for concept, capability in capabilities.items():
        assert capability["provenance_supported"] is provenance[concept]["UI_provenance_supported"]


def test_core_query_metrics_have_ui_drawer_ready_provenance_with_honest_source_limit() -> None:
    for row in _provenance_rows():
        if row["fact_type"] != "mart_metric_facts":
            continue
        assert row["UI_provenance_supported"] is True
        assert row["scope"] == "COMPLETE"
        assert row["definition"] == "COMPLETE"
        assert row["run"] == "COMPLETE"
        assert row["quality"] == "COMPLETE"
        assert row["source_evidence"] == "PARTIAL"
        assert "source_row_ids" in row["missing_fields"]


def test_non_numeric_or_projection_features_are_not_overstated_as_complete() -> None:
    matrix = {row["concept_id"]: row for row in _provenance_rows()}

    for concept in ("abc", "broad_competitors", "direct_peers", "events_signals", "recommendations"):
        assert matrix[concept]["coverage_status"] != "COMPLETE"
    assert matrix["recommendations"]["coverage_status"] == "NOT_APPLICABLE"


def _capability_rows() -> list[dict[str, Any]]:
    return list(yaml.safe_load(CAPABILITY_MATRIX_PATH.read_text(encoding="utf-8"))["capabilities"])


def _provenance_rows() -> list[dict[str, Any]]:
    return list(yaml.safe_load(PROVENANCE_MATRIX_PATH.read_text(encoding="utf-8"))["coverage"])
