"""Resultados explícitos das consultas exploratórias."""

from dataclasses import dataclass
from typing import Any

import polars as pl


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    dtype: pl.DataType
    null_count: int
    null_percentage: float
    unique_count: int
    minimum: Any = None
    maximum: Any = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None


@dataclass(frozen=True)
class DatasetProfile:
    name: str
    row_count: int
    column_count: int
    null_count: int
    columns: tuple[ColumnProfile, ...]


@dataclass(frozen=True)
class ValueFrequency:
    value: Any
    count: int
    percentage: float


@dataclass(frozen=True)
class ColumnDistribution:
    column_name: str
    values: tuple[ValueFrequency, ...]
