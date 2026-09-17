"""Agregações lazy; nulo conta como valor único e como grupo na distribuição."""

import polars as pl

from cyber_analyst.data.dataset import Dataset
from cyber_analyst.analysis.models import (
    ColumnDistribution, ColumnProfile, DatasetProfile, ValueFrequency,
)


class AnalysisError(Exception):
    """Falha esperada ao consultar um dataset."""


def profile_dataset(dataset: Dataset) -> DatasetProfile:
    """Desvio padrão amostral (ddof=1); percentuais vazios são zero.

    Usa os metadados da ingestão: o arquivo não deve mudar entre consultas.
    Únicos exatos e mediana podem requerer memória proporcional aos dados.
    """
    expressions = []
    for index, (name, dtype) in enumerate(dataset.schema.items()):
        column = pl.col(name)
        expressions.extend([
            column.null_count().alias(f"{index}_null"),
            column.n_unique().alias(f"{index}_unique"),
        ])
        if dtype.is_numeric():
            for metric in ("min", "max", "mean", "median", "std"):
                expressions.append(getattr(column, metric)().alias(f"{index}_{metric}"))
    try:
        values = dataset.lazy_frame.select(expressions).collect(engine="streaming").row(0, named=True)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise AnalysisError("Não foi possível analisar o dataset. Verifique o arquivo original.") from exc
    columns = []
    for index, (name, dtype) in enumerate(dataset.schema.items()):
        nulls = values[f"{index}_null"]
        columns.append(ColumnProfile(
            name, dtype, nulls,
            100 * nulls / dataset.row_count if dataset.row_count else 0.0,
            values[f"{index}_unique"],
            *(values.get(f"{index}_{metric}") for metric in ("min", "max", "mean", "median", "std")),
        ))
    return DatasetProfile(dataset.name, dataset.row_count, dataset.column_count,
                          sum(column.null_count for column in columns), tuple(columns))


def get_column_distribution(dataset: Dataset, column_name: str, limit: int = 20) -> ColumnDistribution:
    """Top valores, incluindo nulos; empates ordenados pelo valor, nulos ao final."""
    if column_name not in dataset.schema:
        raise AnalysisError(f"Coluna inexistente: {column_name}")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise AnalysisError("O limite deve ser um inteiro positivo.")
    try:
        result = (
            dataset.lazy_frame.select(pl.col(column_name).alias("value"))
            .group_by("value").agg(pl.len().alias("count"))
            .sort(["count", "value"], descending=[True, False], nulls_last=True)
            .head(limit).collect(engine="streaming")
        )
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise AnalysisError("Não foi possível consultar a distribuição. Verifique o arquivo original.") from exc
    return ColumnDistribution(column_name, tuple(
        ValueFrequency(value, count, 100 * count / dataset.row_count if dataset.row_count else 0.0)
        for value, count in result.iter_rows()
    ))
