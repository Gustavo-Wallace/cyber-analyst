"""Request-local cooperative cancellation, independent of Qt and AI output."""
from datetime import datetime, timezone
from threading import Event, Lock
from uuid import uuid4


class AnalystCancelled(Exception):
    def __init__(self, request_id):
        super().__init__('Analyst request cancelled')
        self.request_id = request_id


class CancellationToken:
    def __init__(self):
        self.request_id = 'analyst_' + uuid4().hex
        self.event = Event()
        self._lock = Lock()
        self._interrupt = None
        self._completed = False
        self.requested_at = self.completed_at = None
        self.worker_completed_at = None
        self.runtime_shutdown = None
        self.stage = 'preparing'

    @property
    def requested(self):
        return self.event.is_set()

    def cancel(self):
        with self._lock:
            if self._completed or self.requested:
                return False
            self.requested_at = datetime.now(timezone.utc).isoformat()
            self.event.set()
            interrupt = self._interrupt
        if interrupt is not None:
            interrupt()
        return True

    def set_interrupt(self, interrupt):
        with self._lock:
            self._interrupt = interrupt
            requested = self.requested
        if requested and interrupt is not None:
            interrupt()

    def check(self, stage=None):
        with self._lock:
            if self.requested:
                raise AnalystCancelled(self.request_id)
            if stage is not None:
                self.stage = stage

    def finish(self):
        """Seal the finish/cancel race when the controller accepts completion."""
        with self._lock:
            self._completed = True
            self.completed_at = datetime.now(timezone.utc).isoformat()
            return self.requested
