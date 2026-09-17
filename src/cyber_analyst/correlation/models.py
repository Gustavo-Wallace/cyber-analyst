from dataclasses import dataclass
from typing import Any

from cyber_analyst.data.dataset import Dataset


@dataclass(frozen=True)
class CorrelationSummary:
    rows_a: int
    rows_b: int
    unique_a: int
    unique_b: int
    common: int
    only_a: int
    only_b: int
    matched_rows: int


@dataclass(frozen=True)
class CorrelationResult:
    dataset_a: Dataset
    dataset_b: Dataset
    column_a: str
    column_b: str
    summary: CorrelationSummary
    preview_columns: tuple[str, ...]
    preview_rows: tuple[tuple[Any, ...], ...]
