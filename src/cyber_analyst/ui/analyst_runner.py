"""One independent Analyst request on a Qt worker, without widget access."""
from dataclasses import dataclass
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from cyber_analyst.analyst import AnalystRequest
from cyber_analyst.context.models import InvestigationContext
from cyber_analyst.context.state import InvestigationState
from cyber_analyst.context.view import InvestigationView
from cyber_analyst.app.analyst import AnalystRunResult


@dataclass(frozen=True)
class AnalystSnapshot:
    request: AnalystRequest
    context: InvestigationContext
    state: InvestigationState
    view: InvestigationView
    investigation_number: int


class AnalystWorker(QObject):
    finished = Signal()

    def __init__(self, pipeline, snapshot):
        super().__init__()
        self.pipeline, self.snapshot = pipeline, snapshot
        self.result = self.error = None

    @Slot()
    def run(self):
        try:
            s = self.snapshot
            result = self.pipeline.answer(s.request, s.context, s.state, s.view)
            self.result = result if isinstance(result, AnalystRunResult) else AnalystRunResult(result)
        except Exception as exc:
            self.error = exc
        finally:
            self.finished.emit()


class AnalystRunner(QObject):
    changed = Signal()
    succeeded = Signal(object, object)
    failed = Signal(object, object)

    def __init__(self, pipeline=None, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.thread = self.worker = None

    @property
    def running(self):
        return self.thread is not None

    def start(self, snapshot):
        if self.running:
            raise ValueError('An Analyst request is already running')
        if self.pipeline is None or not callable(getattr(self.pipeline, 'answer', None)):
            raise ValueError('Configure the local AI runtime and model in Settings')
        self.thread = QThread(self)
        self.worker = AnalystWorker(self.pipeline, snapshot)
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
        snapshot, result, error = self.worker.snapshot, self.worker.result, self.worker.error
        self.thread.wait()
        self.thread.deleteLater()
        self.thread = self.worker = None
        if error is None:
            self.succeeded.emit(snapshot, result)
        else:
            self.failed.emit(snapshot, error)
        self.changed.emit()

    def shutdown(self):
        if self.thread is not None:
            self.thread.wait()
            self._finished()
