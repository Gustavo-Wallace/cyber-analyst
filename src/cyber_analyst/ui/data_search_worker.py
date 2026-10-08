"""Local raw-data search worker; independent of Analyst/runtime lifecycle."""

from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import QApplication

from cyber_analyst.data.value_search import search_values, DataSearchCancelled


class DataSearchWorker(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, token, datasets, query, cancel):
        super().__init__()
        self.token, self.datasets, self.query, self.cancel = token, datasets, query, cancel

    @Slot()
    def run(self):
        try:
            result = search_values(self.datasets, self.query, self.cancel)
            if not self.cancel.is_set():
                self.completed.emit(self.token, result)
        except DataSearchCancelled:
            pass
        except Exception as exc:
            if not self.cancel.is_set():
                self.failed.emit(self.token, str(exc))
        finally:
            self.finished.emit()


class DataSearchRunner(QObject):
    """One worker at a time; the most recent request replaces pending work.

    Application ownership protects QThread lifetime even on direct page deletion.
    Cancellation cannot interrupt an active Polars collect; shutdown joins it.
    """
    completed = Signal(int, object)
    failed = Signal(int, str)
    idle = Signal()

    def __init__(self):
        super().__init__(QApplication.instance())
        self.thread = self.worker = self.cancel_event = self.pending = None
        self.closing = False
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def submit(self, token, datasets, query):
        if self.closing:
            return
        self.cancel()
        self.pending = (token, datasets, query)
        if self.thread is None:
            self._start_pending()

    def cancel(self):
        self.pending = None
        if self.cancel_event is not None:
            self.cancel_event.set()

    def _start_pending(self):
        token, datasets, query = self.pending
        self.pending = None
        self.cancel_event = Event()
        self.thread = QThread(self)
        self.worker = DataSearchWorker(token, datasets, query, self.cancel_event)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._finished)
        self.thread.start()

    @Slot()
    def _finished(self):
        if self.thread is None:
            return
        self.thread.wait()
        self.thread.deleteLater()
        self.thread = self.worker = self.cancel_event = None
        if self.pending is not None and not self.closing:
            self._start_pending()
        else:
            self.idle.emit()

    @Slot()
    def shutdown(self):
        self.closing = True
        self.cancel()
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
