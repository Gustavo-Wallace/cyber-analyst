"""Background orchestration of an injected pipeline, without widget access."""
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt


class InvestigationWorker(QObject):
    finished = Signal()

    def __init__(self, pipeline, datasets):
        super().__init__()
        self.pipeline, self.datasets = pipeline, datasets
        self.result = self.error = None

    @Slot()
    def run(self):
        try:
            self.result = self.pipeline.run(self.datasets)
        except Exception as exc:
            self.error = exc
        finally:
            self.finished.emit()


class InvestigationRunner(QObject):
    changed = Signal()
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, pipeline=None, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.thread = self.worker = None

    @property
    def running(self):
        return self.thread is not None

    def start(self, datasets):
        if self.running:
            raise ValueError('An investigation is already running')
        snapshot = tuple(datasets)
        if self.pipeline is None or not snapshot:
            raise ValueError('A configured pipeline and loaded datasets are required')
        self.thread = QThread(self)
        self.worker = InvestigationWorker(self.pipeline, snapshot)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._finished)
        self.changed.emit()
        self.thread.start()

    @Slot()
    def _finished(self):
        if self.thread is None:
            return
        result, error = self.worker.result, self.worker.error
        self.thread.wait()
        self.thread.deleteLater()
        self.thread = self.worker = None
        if error is None:
            self.succeeded.emit(result)
        else:
            self.failed.emit(error)
        self.changed.emit()

    def shutdown(self):
        # Application-wide quit must never destroy an active QThread.
        if self.thread is not None:
            self.thread.wait()
            self._finished()
