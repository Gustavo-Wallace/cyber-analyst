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


@dataclass(frozen=True)
class AnalystSnapshot:
    request: AnalystRequest
    context: InvestigationContext
    state: InvestigationState
    view: InvestigationView
    investigation_number: int
    cancellation: CancellationToken = field(default_factory=CancellationToken, compare=False)


@dataclass(frozen=True)
class _AnalystCompletion:
    """Python-only outcome, independent of the worker's native lifetime."""
    snapshot: AnalystSnapshot
    result: AnalystRunResult | None
    error: Exception | None


class AnalystWorker(QObject):
    completed = Signal(object)
    finished = Signal()

    def __init__(self, pipeline, snapshot):
        super().__init__()
        self.pipeline, self.snapshot = pipeline, snapshot

    @Slot()
    def run(self):
        result = error = None
        try:
            s = self.snapshot
            s.cancellation.check()
            result = self.pipeline.answer(s.request, s.context, s.state, s.view, cancellation=s.cancellation)
            s.cancellation.check()
            result = result if isinstance(result, AnalystRunResult) else AnalystRunResult(result)
        except Exception as exc:
            if self.snapshot.cancellation.requested and not isinstance(exc, AnalystCancelled):
                error = AnalystCancelled(self.snapshot.cancellation.request_id)
                error.__cause__ = exc
            else:
                error = exc
        finally:
            self.snapshot.cancellation.worker_completed_at = datetime.now(timezone.utc).isoformat()
            self.completed.emit(_AnalystCompletion(self.snapshot, result, error))
            self.finished.emit()


class AnalystRunner(QObject):
    changed = Signal()
    succeeded = Signal(object, object)
    failed = Signal(object, object)
    cancelled = Signal(object, object)

    def __init__(self, pipeline=None, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.thread = self.worker = None
        self._snapshot = self._completion = None
        self._thread_finished_received = False
        self._disposed = False

    @property
    def cancellation(self):
        return self._snapshot.cancellation if self._snapshot is not None else None

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
        self._snapshot = snapshot
        self._completion = None
        self._thread_finished_received = False
        self.thread = QThread(self)
        self.worker = AnalystWorker(self.pipeline, snapshot)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.completed.connect(self._receive_completion, Qt.ConnectionType.QueuedConnection)
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        # Qt processes this deferred deletion while finishing the worker thread.
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_finished, Qt.ConnectionType.QueuedConnection)
        self.changed.emit()
        self.thread.start()

    @Slot(object)
    def _receive_completion(self, completion):
        if completion.snapshot is not self._snapshot or self._completion is not None:
            return
        self._completion = completion
        self._complete(completion.snapshot.cancellation)

    @Slot()
    def _thread_finished(self):
        if self.thread is None or self.sender() is not self.thread:
            return
        self._thread_finished_received = True
        self._complete(self.cancellation)

    @Slot(object)
    def _complete(self, identity):
        if (self.thread is None or self.cancellation is not identity
                or self._completion is None or not self._thread_finished_received):
            return
        # finished precedes native thread cleanup. A zero-time check never waits
        # on the GUI; defer release until that cleanup has actually completed.
        if not self.thread.wait(0):
            QTimer.singleShot(0, self, lambda: self._complete(identity))
            return
        completion = self._completion
        snapshot, result, error = completion.snapshot, completion.result, completion.error
        was_cancelled = identity.finish()
        self.thread.deleteLater()
        self.thread = self.worker = None
        self._snapshot = self._completion = None
        self._thread_finished_received = False
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
        """Request cancellation; queued completion owns cleanup without GUI waits."""
        if self.thread is not None:
            token = self.cancellation
            self.cancel()
            self._complete(token)
        return not self.running

    @Slot()
    def dispose(self):
        # Application ownership keeps the runner/thread alive until unwinding,
        # even if the window is destroyed directly rather than closed normally.
        self._disposed = True
        if self.shutdown() and self.thread is None:
            self.deleteLater()
