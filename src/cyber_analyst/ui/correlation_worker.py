from PySide6.QtCore import QObject, Signal, Slot

from cyber_analyst.correlation.engine import CorrelationError, correlate


class CorrelationWorker(QObject):
    result = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, dataset_a, dataset_b, column_a, column_b):
        super().__init__()
        self.arguments = dataset_a, dataset_b, column_a, column_b

    @Slot()
    def run(self):
        try:
            self.result.emit(correlate(*self.arguments))
        except CorrelationError as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
