"""Immutable UI-facing outcomes and compact diagnostics; no transcript memory."""
from dataclasses import dataclass
from threading import Lock, Thread
from cyber_analyst.analyst import AnalystResponse


@dataclass(frozen=True)
class AnalystRunResult:
    response: AnalystResponse
    diagnostics: tuple[tuple[str, str | int | float | bool], ...] = ()


class AnalystRunError(Exception):
    def __init__(self, original, diagnostics):
        super().__init__(str(original))
        self.original = original
        self.diagnostics = diagnostics


class CountingProvider:
    """Delegate identical requests and count calls, without retaining prompts."""
    def __init__(self, provider, cancellation=None):
        self.provider = provider
        self.calls = 0
        self.cancellation = cancellation

    def _call(self, method, *args, **kwargs):
        if self.cancellation:
            self.cancellation.check()
        self.calls += 1
        try:
            return getattr(self.provider, method)(*args, **kwargs)
        finally:
            if self.cancellation:
                self.cancellation.check()

    def generate_structured(self, *args, **kwargs):
        return self._call('generate_structured', *args, **kwargs)

    def generate_text(self, *args, **kwargs):
        return self._call('generate_text', *args, **kwargs)


class AnalystRuntimeOwner:
    """Only this exclusive request lease may stop the adapter's local runtime."""
    def __init__(self, runtime, cancellation):
        self.runtime, self.cancellation = runtime, cancellation
        self._lock = Lock()
        self._interrupt_lock = Lock()
        self._stop_thread = None
        self._closed = False
        self._stopped = False
        self.stop_error = None
        cancellation.set_interrupt(self.interrupt)

    def interrupt(self):
        # stop() can wait for a process; never perform that wait on the UI thread.
        with self._interrupt_lock:
            if not self._closed and self._stop_thread is None:
                self._stop_thread = Thread(target=self._interrupt_stop, name='Analyst runtime cleanup')
                self._stop_thread.start()

    def _interrupt_stop(self):
        try:
            self.stop()
        except Exception as exc:
            self.stop_error = exc  # Retried/propagated by the request worker's finally.

    def stop(self):
        with self._lock:
            if not self._stopped:
                self.runtime.stop()
                self._stopped = True
                self.cancellation.runtime_shutdown = True
                self.stop_error = None

    def close(self):
        self.cancellation.set_interrupt(None)
        with self._interrupt_lock:
            self._closed = True
            thread = self._stop_thread
        try:
            self.stop()
        except Exception:
            self.cancellation.runtime_shutdown = False
            raise
        finally:
            if thread is not None:
                thread.join()


def diagnostics(service, provider, model, seconds):
    """Project public diagnostics only; never return arguments or raw evidence."""
    stages = [v for v in service.last_diagnostics.values()
              if isinstance(v, dict) and 'attempts' in v]
    attempts = sum(len(s['attempts']) for s in stages)
    tools = service.tool_diagnostics
    synthesis = service.last_diagnostics.get('synthesis', {}).get('attempts', ())
    answer_kind = synthesis[-1].get('response', {}).get('answer_kind', '') if synthesis else ''
    return (
        ('Provider', 'llama.cpp'), ('Model', str(model.name)),
        ('Tools used', tools.used_tools), ('Tool requests', len(tools.requests)),
        ('Tool executions', tools.actual_execution_count), ('Tool reuse', tools.reused_count),
        ('Stage A', tools.final_stage_a or 'Not completed'),
        ('Stage B', answer_kind or 'Not executed'),
        ('Provider calls', provider.calls), ('Structured retries', max(0, provider.calls - attempts)),
        ('Domain retries', sum(s.get('domain_retries', 0) for s in stages)),
        ('Latency (s)', round(seconds, 3)),
    )
