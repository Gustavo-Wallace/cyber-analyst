"""One independent Analyst request on a Qt worker, without widget access."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from cyber_analyst.analyst import AnalystRequest
from cyber_analyst.context.models import InvestigationContext
from cyber_analyst.context.state import InvestigationState
from cyber_analyst.context.view import InvestigationView
from cyber_analyst.app.analyst import AnalystRunResult
from cyber_analyst.analyst.cancellation import CancellationToken, AnalystCancelled

SHUTDOWN_WAIT_MS = 1500


@dataclass(frozen=True)
class AnalystSnapshot:
    request: AnalystRequest
    context: InvestigationContext
    state: InvestigationState
    view: InvestigationView
    investigation_number: int
    cancellation: CancellationToken = field(default_factory=CancellationToken, compare=False)


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
            s.cancellation.check()
            result = self.pipeline.answer(s.request, s.context, s.state, s.view, cancellation=s.cancellation)
            s.cancellation.check()
            self.result = result if isinstance(result, AnalystRunResult) else AnalystRunResult(result)
        except Exception as exc:
            if self.snapshot.cancellation.requested and not isinstance(exc, AnalystCancelled):
                self.error = AnalystCancelled(self.snapshot.cancellation.request_id)
                self.error.__cause__ = exc
            else:
                self.error = exc
        finally:
            self.snapshot.cancellation.worker_completed_at = datetime.now(timezone.utc).isoformat()
            self.finished.emit()


class AnalystRunner(QObject):
    changed = Signal()
    succeeded = Signal(object, object)
    failed = Signal(object, object)
    cancelled = Signal(object, object)
    _worker_done = Signal(object)

    def __init__(self, pipeline=None, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.thread = self.worker = None
        self._disposed = False
        self._worker_done.connect(self._complete)

    @property
    def cancellation(self):
        return self.worker.snapshot.cancellation if self.worker is not None else None

    @property
    def running(self):
        return self.thread is not None

    def start(self, snapshot):
        if self._disposed:
            raise ValueError('The Analyst runner is closed')
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
        identity = snapshot.cancellation
        # The relay only emits a signal; all controller work runs in its Qt slot.
        self.thread.finished.connect(lambda: self._worker_done.emit(identity))
        self.changed.emit()
        self.thread.start()

    @Slot(object)
    def _complete(self, identity):
        if self.worker is None or self.cancellation is not identity:
            return
        snapshot, result, error = self.worker.snapshot, self.worker.result, self.worker.error
        if self.thread.isRunning():
            # finished can be delivered while Qt is still releasing thread-local
            # resources. Keep identity protection without blocking the GUI.
            QTimer.singleShot(10, self, lambda: self._complete(identity))
            return
        was_cancelled = identity.finish()
        self.thread.deleteLater()
        self.thread = self.worker = None
        if self._disposed:
            self.deleteLater()
            return
        if was_cancelled or isinstance(error, AnalystCancelled):
            self.cancelled.emit(snapshot, error if isinstance(error, AnalystCancelled) else AnalystCancelled(identity.request_id))
        elif error is None:
            self.succeeded.emit(snapshot, result)
        else:
            self.failed.emit(snapshot, error)
        self.changed.emit()

    @Slot()
    def cancel(self):
        token = self.cancellation
        if token is not None and token.cancel():
            self.changed.emit()
            return True
        return False

    @Slot()
    def shutdown(self):
        """Bounded fallback; normal window close waits asynchronously via changed."""
        if self.thread is not None:
            token = self.cancellation
            self.cancel()
            if not self.thread.wait(SHUTDOWN_WAIT_MS):
                return False
            self._complete(token)
        return True

    @Slot()
    def dispose(self):
        # Application ownership keeps the runner/thread alive until unwinding,
        # even if the window is destroyed directly rather than closed normally.
        self._disposed = True
        if self.shutdown() and self.thread is None:
            self.deleteLater()
