"""Relações CSV DuckDB com schema Polars explícito, sem cópia integral em Python.

Textos recebem apenas trim de espaços ASCII nas extremidades da chave.
Strings vazias após trim continuam sendo chaves válidas; nulos são excluídos.
O preview preserva valores originais e distingue as origens por A./B.
Os arquivos devem permanecer disponíveis e inalterados entre as consultas.
"""

import duckdb
import polars as pl

from cyber_analyst.data.dataset import Dataset
from cyber_analyst.correlation.models import CorrelationResult, CorrelationSummary


class CorrelationError(Exception):
    """Falha esperada de validação ou execução relacional."""


_TYPES = {
    pl.String: "VARCHAR", pl.Boolean: "BOOLEAN",
    pl.Int8: "TINYINT", pl.Int16: "SMALLINT", pl.Int32: "INTEGER", pl.Int64: "BIGINT",
    pl.UInt8: "UTINYINT", pl.UInt16: "USMALLINT", pl.UInt32: "UINTEGER", pl.UInt64: "UBIGINT",
    pl.Float32: "FLOAT", pl.Float64: "DOUBLE", pl.Date: "DATE",
}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _relation(connection, dataset: Dataset, name: str) -> None:
    columns = {}
    # Nomes internos posicionais evitam colisões case-insensitive do DuckDB.
    for index, dtype in enumerate(dataset.schema.values()):
        if dtype not in _TYPES:
            raise CorrelationError(f"Tipo ainda não suportado na correlação: {dtype}")
        columns[f"c{index}"] = _TYPES[dtype]
    # Escape dos metacaracteres do glob; o caminho representa um único arquivo.
    path = ''.join({'[': '[[]', ']': '[]]', '*': '[*]', '?': '[?]'}.get(c, c)
                   for c in str(dataset.path))
    connection.read_csv(
        path, columns=columns, header=True, auto_detect=False, delimiter=",",
        quotechar='"', escapechar='"', na_values="", allow_quoted_nulls=False,
    ).create_view(name)


def validate_compatibility(dataset_a: Dataset, dataset_b: Dataset, column_a: str, column_b: str) -> None:
    """Validação compartilhada, sem acesso a CSV ou execução de correlação."""
    if dataset_a.path.resolve() == dataset_b.path.resolve():
        raise CorrelationError("Selecione datasets diferentes.")
    if column_a not in dataset_a.schema or column_b not in dataset_b.schema:
        raise CorrelationError("Coluna inexistente em um dos datasets.")
    dtype_a, dtype_b = dataset_a.schema[column_a], dataset_b.schema[column_b]
    if (dataset_a.row_count and dataset_b.row_count and dtype_a != dtype_b
            and not (dtype_a.is_integer() and dtype_b.is_integer())):
        raise CorrelationError(f"Tipos incompatíveis: {dtype_a} e {dtype_b}. Não será feita coerção automática.")
    for dataset in (dataset_a, dataset_b):
        if any(dtype not in _TYPES for dtype in dataset.schema.values()):
            raise CorrelationError("Tipo ainda não suportado na correlação.")


def correlate(dataset_a: Dataset, dataset_b: Dataset, column_a: str, column_b: str,
              preview_limit: int = 100) -> CorrelationResult:
    validate_compatibility(dataset_a, dataset_b, column_a, column_b)
    if isinstance(preview_limit, bool) or not isinstance(preview_limit, int) or preview_limit < 1:
        raise CorrelationError("O limite do preview deve ser um inteiro positivo.")
    dtype_a, dtype_b = dataset_a.schema[column_a], dataset_b.schema[column_b]
    index_a, index_b = dataset_a.columns.index(column_a), dataset_b.columns.index(column_b)

    def key(index, dtype):
        expression = f"c{index}"
        if dtype == pl.String:
            return f"trim({expression})"
        if dtype.is_integer():
            return f"CAST({expression} AS HUGEINT)"
        return expression

    try:
        with duckdb.connect(":memory:") as connection:
            _relation(connection, dataset_a, "source_a")
            _relation(connection, dataset_b, "source_b")
            for side, index, dtype in (("a", index_a, dtype_a), ("b", index_b, dtype_b)):
                expression = key(index, dtype)
                connection.execute(f"CREATE VIEW keys_{side} AS SELECT *, {expression} AS k FROM source_{side}")
            # Frequências permitem contar o join exato sem expandir duplicatas.
            counts = connection.execute("""
                WITH a AS (SELECT k, count(*)::HUGEINT AS n FROM keys_a WHERE k IS NOT NULL GROUP BY k),
                     b AS (SELECT k, count(*)::HUGEINT AS n FROM keys_b WHERE k IS NOT NULL GROUP BY k)
                SELECT count(a.k), count(b.k),
                       count(*) FILTER (WHERE a.k IS NOT NULL AND b.k IS NOT NULL),
                       count(*) FILTER (WHERE b.k IS NULL),
                       count(*) FILTER (WHERE a.k IS NULL),
                       coalesce(sum(a.n * b.n), 0)
                FROM a FULL OUTER JOIN b ON a.k = b.k
            """).fetchone()
            projection = ', '.join(
                f"{side}.c{index} AS {_quote(side.upper() + '.' + column)}"
                for side, dataset in (("a", dataset_a), ("b", dataset_b))
                for index, column in enumerate(dataset.columns)
            )
            rows = connection.execute(
                f"SELECT {projection} FROM keys_a a INNER JOIN keys_b b ON a.k = b.k LIMIT ?",
                [preview_limit],
            ).fetchall()
    except (OSError, duckdb.Error) as exc:
        raise CorrelationError("Não foi possível correlacionar. Verifique acesso e estrutura dos arquivos originais.") from exc
    return CorrelationResult(
        dataset_a, dataset_b, column_a, column_b,
        CorrelationSummary(dataset_a.row_count, dataset_b.row_count, *(int(value) for value in counts)),
        tuple(f"{side}.{column}" for side, dataset in (("A", dataset_a), ("B", dataset_b))
              for column in dataset.columns), tuple(rows),
    )
