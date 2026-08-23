"""Analytical universe scope contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

import polars as pl


class PrivateLabelScope(StrEnum):
    """Private-label analytical universe selection."""

    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"
    ONLY = "ONLY"


@dataclass(frozen=True)
class PrivateLabelScopeResult:
    """Scoped frame plus quality counts for analytical-universe filtering."""

    frame: pl.DataFrame
    private_label_scope: PrivateLabelScope
    input_row_count: int
    output_row_count: int
    unknown_private_label_count: int


def scope_identity_hash(*, private_label_scope: PrivateLabelScope | str) -> str:
    """Return deterministic analytical scope identity."""

    scope = PrivateLabelScope(private_label_scope)
    payload = {"private_label_scope": scope.value}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def apply_private_label_scope(
    frame: pl.DataFrame,
    private_label_scope: PrivateLabelScope | str = PrivateLabelScope.INCLUDE,
) -> PrivateLabelScopeResult:
    """Filter canonical/enriched rows before analytical calculation."""

    scope = PrivateLabelScope(private_label_scope)
    if "private_label_flag" not in frame.columns:
        if scope == PrivateLabelScope.INCLUDE:
            return PrivateLabelScopeResult(frame.clone(), scope, frame.height, frame.height, 0)
        raise ValueError("private_label_flag is required for non-INCLUDE private_label_scope")

    unknown_count = frame.filter(pl.col("private_label_flag").is_null()).height
    if scope == PrivateLabelScope.INCLUDE:
        result = frame.clone()
    elif scope == PrivateLabelScope.EXCLUDE:
        result = frame.filter(pl.col("private_label_flag") == False)
    else:
        result = frame.filter(pl.col("private_label_flag") == True)
    return PrivateLabelScopeResult(result, scope, frame.height, result.height, unknown_count)
