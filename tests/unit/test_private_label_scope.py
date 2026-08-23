from __future__ import annotations

import polars as pl
import pytest

from retail_analytics.mart import (
    PrivateLabelScope,
    apply_private_label_scope,
    scope_identity_hash,
)


def test_private_label_scope_default_include_keeps_all_rows() -> None:
    result = apply_private_label_scope(_frame())

    assert result.private_label_scope == PrivateLabelScope.INCLUDE
    assert result.output_row_count == 3


def test_private_label_scope_exclude_removes_private_label_rows() -> None:
    result = apply_private_label_scope(_frame(), PrivateLabelScope.EXCLUDE)

    assert result.frame["sku"].to_list() == ["SKU_A_001"]
    assert result.unknown_private_label_count == 1


def test_private_label_scope_only_keeps_private_label_rows() -> None:
    result = apply_private_label_scope(_frame(), PrivateLabelScope.ONLY)

    assert result.frame["sku"].to_list() == ["SKU_A_002"]


def test_invalid_private_label_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="INVALID"):
        apply_private_label_scope(_frame(), "INVALID")


def test_non_include_scope_requires_private_label_flag() -> None:
    with pytest.raises(ValueError, match="private_label_flag"):
        apply_private_label_scope(pl.DataFrame({"sku": ["SKU_A_001"]}), PrivateLabelScope.EXCLUDE)


def test_scope_identity_hash_distinguishes_universes() -> None:
    assert scope_identity_hash(private_label_scope=PrivateLabelScope.INCLUDE) != scope_identity_hash(
        private_label_scope=PrivateLabelScope.EXCLUDE
    )


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sku": ["SKU_A_001", "SKU_A_002", "SKU_A_003"],
            "private_label_flag": [False, True, None],
        }
    )
