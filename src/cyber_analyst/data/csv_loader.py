"""Inspeção read-only de arquivos CSV locais."""

from pathlib import Path

import polars as pl

from cyber_analyst.data.dataset import Dataset


class DatasetLoadError(Exception):
    """Falha ao acessar ou interpretar um dataset."""


def load_csv(path: str | Path) -> Dataset:
    """Leia CSV com os padrões do Polars e preview limitado a 100 registros.

    O schema é inferido por amostragem. Valores incompatíveis no restante do
    arquivo são rejeitados. O arquivo deve permanecer disponível e inalterado
    para futuras consultas ao LazyFrame.
    """
    try:
        source = Path(path).resolve()
        if not source.exists():
            raise DatasetLoadError(f"Caminho inexistente: {source}")
        if not source.is_file():
            raise DatasetLoadError(f"O caminho não é um arquivo: {source}")
        if source.suffix.lower() != ".csv":
            raise DatasetLoadError("Somente arquivos .csv são aceitos.")
        if source.stat().st_size == 0:
            raise DatasetLoadError("O arquivo CSV está vazio.")

        frame = pl.scan_csv(source, glob=False)
        schema = frame.collect_schema()
        # Contar apenas linhas pode dispensar o parsing dos valores. As
        # contagens por coluna garantem a leitura de todas elas em streaming.
        counts = frame.select(
            pl.len().alias("_row_count"),
            pl.all().count().name.prefix("_valid_"),
        ).collect(engine="streaming")
        preview = frame.head(100).collect(engine="streaming")
        return Dataset(
            path=source,
            row_count=counts.item(0, "_row_count"),
            schema=schema,
            preview=preview,
            lazy_frame=frame,
        )
    except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
        raise DatasetLoadError(
            "Não foi possível ler o CSV. Verifique acesso, estrutura e encoding UTF-8."
        ) from exc
