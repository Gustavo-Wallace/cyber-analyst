"""Worker Qt; não acessa widgets nem a coleção da sessão."""

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from cyber_analyst.data.csv_loader import DatasetLoadError, load_csv


class CsvWorker(QObject):
    loaded = Signal(object)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self.paths = paths

    @Slot()
    def run(self) -> None:
        try:
            for path in self.paths:
                if QThread.currentThread().isInterruptionRequested():
                    break
                try:
                    dataset = load_csv(path)
                except DatasetLoadError as exc:
                    self.failed.emit(str(path), str(exc))
                else:
                    self.loaded.emit(dataset)
        finally:
            # Exceções inesperadas continuam chegando ao excepthook do Python.
            self.finished.emit()
