"""Shared Volume filter tokens, facets, and predicates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

VOLUME_FILTER_DECIMALS = 6
VOLUME_RANGE_PREFIX = "volume_range:"


@dataclass(frozen=True)
class VolumeRange:
    id: str
    min_exclusive: float | None
    max_inclusive: float | None
    label: str

    @property
    def token(self) -> str:
        return f"{VOLUME_RANGE_PREFIX}{self.id}"


VOLUME_RANGES: tuple[VolumeRange, ...] = (
    VolumeRange("le_0_25", 0.0, 0.25, "≤ 0,25 л"),
    VolumeRange("gt_0_25_le_0_50", 0.25, 0.50, "> 0,25–0,50 л"),
    VolumeRange("gt_0_50_le_0_75", 0.50, 0.75, "> 0,50–0,75 л"),
    VolumeRange("gt_0_75_le_1_00", 0.75, 1.00, "> 0,75–1,00 л"),
    VolumeRange("gt_1_00_le_1_50", 1.00, 1.50, "> 1,00–1,50 л"),
    VolumeRange("gt_1_50_le_2_00", 1.50, 2.00, "> 1,50–2,00 л"),
    VolumeRange("gt_2_00_le_5_00", 2.00, 5.00, "> 2,00–5,00 л"),
    VolumeRange("gt_5_00", 5.00, None, "> 5,00 л"),
)
VOLUME_RANGES_BY_ID = {item.id: item for item in VOLUME_RANGES}


def volume_option_value(value: object) -> str:
    numeric = float(str(value))
    return f"{numeric:.12g}"


def volume_option_label(value: object) -> str:
    text = volume_option_value(value).replace(".", ",")
    return f"{text} л"


def volume_exact_values(values: tuple[str, ...]) -> tuple[float, ...]:
    return tuple(round(float(value), VOLUME_FILTER_DECIMALS) for value in values if not is_volume_range_token(value))


def is_volume_range_token(value: object) -> bool:
    return isinstance(value, str) and value.startswith(VOLUME_RANGE_PREFIX)


def volume_range_for_token(token: str) -> VolumeRange:
    range_id = token.removeprefix(VOLUME_RANGE_PREFIX)
    try:
        return VOLUME_RANGES_BY_ID[range_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported volume range token: {token}") from exc


def split_volume_filter_values(values: tuple[str, ...]) -> tuple[tuple[float, ...], tuple[VolumeRange, ...]]:
    exact = volume_exact_values(values)
    ranges = tuple(volume_range_for_token(value) for value in values if is_volume_range_token(value))
    return exact, ranges


def volume_sql_predicate(column: str, values: tuple[str, ...]) -> tuple[str | None, list[Any]]:
    exact, ranges = split_volume_filter_values(values)
    predicates: list[str] = []
    params: list[Any] = []
    rounded_column = f"ROUND(CAST({column} AS DOUBLE), {VOLUME_FILTER_DECIMALS})"
    if exact:
        placeholders = ", ".join("?" for _ in exact)
        predicates.append(f"{rounded_column} IN ({placeholders})")
        params.extend(exact)
    for item in ranges:
        parts = [f"CAST({column} AS DOUBLE) > ?"]
        params.append(item.min_exclusive if item.min_exclusive is not None else 0.0)
        if item.max_inclusive is not None:
            parts.append(f"CAST({column} AS DOUBLE) <= ?")
            params.append(item.max_inclusive)
        predicates.append("(" + " AND ".join(parts) + ")")
    if not predicates:
        return None, []
    return "(" + " OR ".join(predicates) + ")", params


def volume_polars_filter(column: str, values: tuple[str, ...]) -> pl.Expr | None:
    exact, ranges = split_volume_filter_values(values)
    predicates: list[pl.Expr] = []
    volume = pl.col(column).cast(pl.Float64)
    if exact:
        predicates.append(volume.round(VOLUME_FILTER_DECIMALS).is_in(list(exact)))
    for item in ranges:
        predicate = volume > (item.min_exclusive if item.min_exclusive is not None else 0.0)
        if item.max_inclusive is not None:
            predicate = predicate & (volume <= item.max_inclusive)
        predicates.append(predicate)
    if not predicates:
        return None
    combined = predicates[0]
    for predicate in predicates[1:]:
        combined = combined | predicate
    return combined


def volume_range_for_value(value: float) -> VolumeRange | None:
    if value <= 0:
        return None
    for item in VOLUME_RANGES:
        if value > (item.min_exclusive if item.min_exclusive is not None else 0.0) and (
            item.max_inclusive is None or value <= item.max_inclusive
        ):
            return item
    return None
