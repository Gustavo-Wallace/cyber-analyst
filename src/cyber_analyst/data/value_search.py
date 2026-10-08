"""Bounded, literal, read-only searches through already loaded datasets."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event

import polars as pl

from .dataset import Dataset

MAX_SEARCH_RESULTS = 200


@dataclass(frozen=True)
class DataSearchRow:
    dataset_path: Path
    dataset_name: str
    row_index: int  # Zero-based source record, excluding the CSV header.
    columns: tuple[str, ...]
    values: tuple


@dataclass(frozen=True)
class DataSearchHit:
    row: DataSearchRow
    column_name: str
    value: object


@dataclass(frozen=True)
class DataSearchResult:
    hits: tuple[DataSearchHit, ...]
    truncated: bool = False

    @property
    def rows(self) -> tuple[DataSearchRow, ...]:
        seen, rows = set(), []
        for hit in self.hits:
            key = (hit.row.dataset_path, hit.row.row_index)
            if key not in seen:
                rows.append(hit.row)
                seen.add(key)
        return tuple(rows)


class DataSearchCancelled(Exception):
    """Cooperative cancellation between bounded dataset queries."""


def search_values(datasets: tuple[Dataset, ...], query: str,
                  cancel: Event | None = None) -> DataSearchResult:
    """Search complete lazy data, collect at most 201 matching rows per dataset.

    Polars checks the cells. Python visits only bounded matching results, never
    scans the source row by row. Original values/order remain in the returned
    row snapshots. One extra hit establishes truncation without counting all hits.
    """
    query = query.strip().lower()
    if not query:
        return DataSearchResult(())
    hits = []
    for dataset in datasets:
        if cancel is not None and cancel.is_set():
            raise DataSearchCancelled()
        columns = tuple(dataset.columns)
        if not columns:
            continue
        index, matches = '_search_row', '_search_columns'
        while index in columns:
            index += '_'
        while matches in (*columns, index):
            matches += '_'
        checks = [pl.when(pl.col(name).cast(pl.String, strict=False).str.to_lowercase()
                          .str.contains(query, literal=True).fill_null(False))
                  .then(pl.lit(name)).otherwise(None) for name in columns]
        frame = (dataset.lazy_frame.with_row_index(index)
                 .with_columns(pl.concat_list(checks).list.drop_nulls().alias(matches))
                 .filter(pl.col(matches).list.len() > 0)
                 .head(MAX_SEARCH_RESULTS + 1 - len(hits)).collect(engine='streaming'))
        if cancel is not None and cancel.is_set():
            raise DataSearchCancelled()
        positions = {name: frame.columns.index(name) for name in columns}
        index_position, match_position = frame.columns.index(index), frame.columns.index(matches)
        for values in frame.iter_rows():
            row = DataSearchRow(dataset.path.resolve(), dataset.name, values[index_position],
                                columns, tuple(values[positions[c]] for c in columns))
            for name in values[match_position]:
                hits.append(DataSearchHit(row, name, values[positions[name]]))
                if len(hits) > MAX_SEARCH_RESULTS:
                    return DataSearchResult(tuple(hits[:MAX_SEARCH_RESULTS]), truncated=True)
    return DataSearchResult(tuple(hits))
