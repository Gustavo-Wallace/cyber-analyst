"""Consultas analíticas fora da thread da GUI."""

from PySide6.QtCore import QObject, Signal, Slot

from cyber_analyst.analysis.exploratory import AnalysisError, get_column_distribution, profile_dataset
from cyber_analyst.data.dataset import Dataset


class AnalysisWorker(QObject):
    result = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, dataset: Dataset, column: str | None = None) -> None:
        super().__init__()
        self.dataset = dataset
        self.column = column

    @Slot()
    def run(self) -> None:
        try:
            result = (profile_dataset(self.dataset) if self.column is None else
                      get_column_distribution(self.dataset, self.column))
            self.result.emit(result)
        except AnalysisError as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
