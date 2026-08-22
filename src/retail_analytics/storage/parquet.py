"""Parquet storage primitives for canonical data."""
from __future__ import annotations

from pathlib import Path

import polars as pl


def write_canonical_parquet(frame: pl.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(output_path)
    return output_path

def read_canonical_parquet(path: str | Path) -> pl.DataFrame:
    return pl.read_parquet(Path(path))