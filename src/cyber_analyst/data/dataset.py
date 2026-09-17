"""Representação de um CSV inspecionado."""

from dataclasses import dataclass
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class Dataset:
    """Metadados e preview em memória; consultas lazy releem o arquivo original."""

    path: Path
    row_count: int
    schema: pl.Schema
    preview: pl.DataFrame
    lazy_frame: pl.LazyFrame

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def column_count(self) -> int:
        return len(self.schema)

    @property
    def columns(self) -> list[str]:
        return self.schema.names()
