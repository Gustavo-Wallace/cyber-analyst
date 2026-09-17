"""Coleção em memória, ordenada pelo momento de inserção."""

from pathlib import Path

from cyber_analyst.data.dataset import Dataset


class DatasetCollection:
    def __init__(self) -> None:
        self._datasets: dict[Path, Dataset] = {}

    def __len__(self) -> int:
        return len(self._datasets)

    def contains(self, path: str | Path) -> bool:
        return Path(path).resolve() in self._datasets

    def add(self, dataset: Dataset) -> bool:
        key = dataset.path.resolve()
        if key in self._datasets:
            return False
        self._datasets[key] = dataset
        return True

    def get(self, path: str | Path) -> Dataset:
        return self._datasets[Path(path).resolve()]

    def remove(self, path: str | Path) -> Dataset:
        return self._datasets.pop(Path(path).resolve())

    def values(self) -> tuple[Dataset, ...]:
        return tuple(self._datasets.values())
