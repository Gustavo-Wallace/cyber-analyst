"""Cancellation races use controlled providers; no inference or runtime startup."""
import json
import time
from threading import Event, Thread
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from cyber_analyst.analyst import AnalystRequest, AnalystService, AnalystCancelled, CancellationToken
from cyber_analyst.analyst.context import AnalystContextBuilder
from cyber_analyst.analyst.composer import LIMITATIONS
from cyber_analyst.ai import AIService
from cyber_analyst.ai.models import AIProviderError
from cyber_analyst.app.analyst import CountingProvider, AnalystRuntimeOwner
from cyber_analyst.context import ContextService, InvestigationState, ViewService
from test_investigation_context import synthetic
from test_analyst_page import setup, send, wait


def service_run(provider, token):
    context = ContextService().build(synthetic())
    state = InvestigationState()
    view = ViewService().build(context, state)
    service = AnalystService(AIService(CountingProvider(provider, token)))
    return service.answer(AnalystRequest('What facts are recorded?'), AnalystContextBuilder().build(context, state, view),
                          investigation_context=context, state=state, view=view, cancellation=token)


class Provider:
    def __init__(self, token, stop_at=None, tools=False):
        self.token, self.stop_at, self.tools = token, stop_at, tools
        self.calls = []

    def generate_structured(self, messages, name, schema, config):
        self.calls.append(name)
        if name == self.stop_at:
            self.token.cancel()
        if name == 'analyst_selection':
            return json.dumps(dict(status='insufficient' if self.tools else 'supported', fact_aliases=[] if self.tools else ['F01']))
        if name.startswith('analyst_tool_planning'):
            if name.endswith('_2'):
                return json.dumps({'requests': []})
            return json.dumps({'requests': [{'tool_name': 'get_entity', 'arguments': {'entity_id': 'ana'}},
                                           {'tool_name': 'get_entity', 'arguments': {'entity_id': 'email'}}]})
        if name == 'analyst_post_tool_selection':
            return json.dumps(dict(status='supported', fact_aliases=['F01']))
        return json.dumps(dict(status='answered', answer_kind='factual_summary', sections=[['F01']],
                               limitations={code: False for code in LIMITATIONS}))


def test_cancel_before_stage_a_never_calls_provider():
    token = CancellationToken()
    token.cancel()
    provider = Provider(token)
    with pytest.raises(AnalystCancelled): service_run(provider, token)
    assert provider.calls == []


@pytest.mark.parametrize('stage,tools', [('analyst_selection', False), ('analyst_tool_planning_1', True),
                                       ('analyst_post_tool_selection', True), ('analyst_synthesis', False)])
def test_stage_boundary_cancellation_stops_later_stages(stage, tools):
    token = CancellationToken()
    provider = Provider(token, stage, tools)
    with pytest.raises(AnalystCancelled): service_run(provider, token)
    assert provider.calls[-1] == stage
    assert token.stage in ('selection', 'tool_planning_1', 'post_tool_selection', 'synthesis')


def test_cancel_during_first_tool_stops_second_tool_and_stage_b(monkeypatch):
    from cyber_analyst.analyst import retrieval
    token = CancellationToken()
    provider = Provider(token, tools=True)
    original = retrieval.execute_request
    executed = []
    def execute(*args):
        executed.append(args[0])
        result = original(*args)
        token.cancel()
        return result
    monkeypatch.setattr(retrieval, 'execute_request', execute)
    with pytest.raises(AnalystCancelled): service_run(provider, token)
    assert len(executed) == 1 and token.stage == 'tool_execution'
    assert 'analyst_post_tool_selection' not in provider.calls and 'analyst_synthesis' not in provider.calls


def test_blocking_provider_interrupted_by_its_owner_only():
    entered, stopped = Event(), Event()
    calls = []
    class Runtime:
        def stop(self): calls.append('stop'); stopped.set()
    token = CancellationToken()
    owner = AnalystRuntimeOwner(Runtime(), token)
    class Blocking:
        def generate_structured(self, *args):
            entered.set()
            assert stopped.wait(3)
            raise AIProviderError('socket closed') from ConnectionResetError('closed')
    errors = []
    def run():
        try: service_run(Blocking(), token)
        except Exception as error: errors.append(error)
        finally: owner.close()
    worker = Thread(target=run)
    worker.start()
    assert entered.wait(3)
    assert token.cancel() and not token.cancel()
    worker.join(3)
    assert not worker.is_alive() and isinstance(errors[0], AnalystCancelled)
    assert calls == ['stop']
    owner.close()
    assert calls == ['stop']


def test_provider_failure_without_cancel_is_not_cancelled():
    class Broken:
        def generate_structured(self, *args): raise AIProviderError('timeout') from TimeoutError()
    with pytest.raises(AIProviderError): service_run(Broken(), CancellationToken())


def test_immediate_cancel_and_ui_recovery(setup):
    app, p, w, page = setup
    assert not page.cancel_button.isVisible()
    send(w, page)
    snapshot = page.exchanges[-1].snapshot
    assert page.cancel_button.isVisible() and page.cancel_button.isEnabled()
    page.cancel_button.click()
    assert not page.cancel_button.isEnabled() and page.status.text() == 'Cancelling...'
    assert not page.send_button.isEnabled() and not page.clear_button.isEnabled()
    assert not w.analyst_runner.cancel()
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(True))
    wait(app, lambda: not w.analyst_runner.running and bool(ticks))
    e = page.exchanges[-1]
    assert e.question.text() == snapshot.request.question
    assert e.outcome_status == 'cancelled' and e.result_status.text() == 'Cancelled'
    assert e.answer.toPlainText() == '' and not e.references.items
    assert page.question.isEnabled() and not page.cancel_button.isVisible()
    page.question.setPlainText('New question')
    assert page.send_button.isEnabled()
    assert snapshot.cancellation.requested_at and snapshot.cancellation.completed_at


def test_cancel_preserves_success_and_next_request_succeeds(setup):
    app, p, w, page = setup
    p.release.set(); send(w, page)
    wait(app, lambda: not w.analyst_runner.running)
    first = page.exchanges[0].answer.toPlainText()
    p.release.clear(); send(w, page)
    wait(app, lambda: len(p.calls) == 2)
    page.cancel_button.click()
    wait(app, lambda: not w.analyst_runner.running)
    assert page.exchanges[0].answer.toPlainText() == first
    assert page.exchanges[1].outcome_status == 'cancelled'
    p.release.set(); send(w, page)
    wait(app, lambda: not w.analyst_runner.running)
    assert page.exchanges[2].outcome_status == 'answered'


def test_finish_queued_before_cancel_cannot_render_answer(setup):
    app, p, w, page = setup
    p.release.set(); send(w, page)
    thread = w.analyst_runner.thread
    assert thread.wait(2000)  # completion queued, not yet accepted by GUI
    assert w.analyst_runner.cancel()
    wait(app, lambda: not w.analyst_runner.running)
    assert page.exchanges[0].outcome_status == 'cancelled'
    assert not w.analyst_runner.cancel()


def test_cancel_after_accepted_completion_cannot_change_answer(setup):
    app, p, w, page = setup
    p.release.set(); send(w, page)
    wait(app, lambda: not w.analyst_runner.running)
    assert not w.analyst_runner.cancel()
    assert page.exchanges[0].outcome_status == 'answered'


def test_late_signal_and_old_identity_cannot_update_new_exchange(setup):
    from cyber_analyst.app.analyst import AnalystRunResult
    from cyber_analyst.ui.analyst_runner import _AnalystCompletion
    app, p, w, page = setup
    send(w, page); old = page.exchanges[-1].snapshot
    w.analyst_runner.cancel()
    wait(app, lambda: not w.analyst_runner.running)
    send(w, page); current = page.exchanges[-1]
    assert current.snapshot.cancellation.request_id != old.cancellation.request_id
    w.analyst_runner._complete(old.cancellation)
    w.analyst_runner._receive_completion(_AnalystCompletion(old, AnalystRunResult(p.response), None))
    w.analyst_runner.succeeded.emit(old, AnalystRunResult(p.response))
    w.analyst_runner.failed.emit(old, AIProviderError('late'))
    w.analyst_runner.cancelled.emit(old, AnalystCancelled(old.cancellation.request_id))
    assert current.outcome_status == 'running'
    w.analyst_runner.cancel()
    wait(app, lambda: not w.analyst_runner.running)


def test_replacement_cancels_without_affecting_new_context(setup):
    app, p, w, page = setup
    send(w, page); wait(app, lambda: bool(p.calls))
    w.set_investigation(synthetic())
    session = w.investigation_session
    context, state, view = session.context, session.state, session.view
    wait(app, lambda: not w.analyst_runner.running)
    assert page.exchanges[0].outcome_status == 'cancelled' and not page.exchanges[0].current
    assert session.context is context and session.state is state and session.view is view


def test_destroying_page_cancels_and_unwinds(setup):
    app, p, w, page = setup
    send(w, page); wait(app, lambda: bool(p.calls))
    snapshot = page.exchanges[0].snapshot
    w.analyst_page = type('ClosedPage', (), {'set_execution_blocked': lambda *a: None})()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    wait(app, lambda: not w.analyst_runner.running)
    assert snapshot.cancellation.requested and w.analyst_runner.worker is None


def test_close_requests_cancel_and_cleans_thread(setup):
    app, p, w, page = setup
    send(w, page); wait(app, lambda: bool(p.calls))
    token = w.analyst_runner.cancellation
    w.close()
    assert token.requested
    wait(app, lambda: not w.isVisible() and not w.analyst_runner.running)
    assert w.analyst_runner.thread is None and w.analyst_runner.worker is None


def test_direct_window_destruction_is_safe(setup):
    app, p, w, page = setup
    send(w, page); wait(app, lambda: bool(p.calls))
    runner, token = w.analyst_runner, w.analyst_runner.cancellation
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert token.requested
    wait(app, lambda: not runner.running)
    assert runner.thread is None and runner.worker is None


def test_quit_event_is_deferred_until_worker_unwinds(setup):
    app, p, w, page = setup
    send(w, page); wait(app, lambda: bool(p.calls))
    assert w.eventFilter(app, QEvent(QEvent.Type.Quit))
    assert w.analyst_runner.cancellation.requested
    # Avoid ending the shared test QApplication; native smoke covers actual exit.
    w._quit_pending = False
    wait(app, lambda: not w.analyst_runner.running)


def test_shutdown_is_nonblocking_without_unsafe_thread_termination(setup, monkeypatch):
    app, p, w, page = setup
    entered, release = Event(), Event()
    def uncooperative(*args, **kwargs):
        entered.set(); assert release.wait(3)
        return p.response
    monkeypatch.setattr(p, 'answer', uncooperative)
    send(w, page); wait(app, entered.is_set)
    start = time.monotonic()
    assert not w.analyst_runner.shutdown()
    assert time.monotonic() - start < .5
    assert w.analyst_runner.running
    release.set(); wait(app, lambda: not w.analyst_runner.running)
    assert page.exchanges[0].outcome_status == 'cancelled'


@pytest.mark.parametrize('cancel', [False, True])
def test_queued_completion_never_reads_destroyed_worker(setup, cancel):
    from PySide6.QtCore import QThread
    from shiboken6 import isValid
    app, p, w, page = setup
    delivered = []
    w.analyst_runner.succeeded.connect(
        lambda snapshot, result: delivered.append((snapshot, result, QThread.currentThread())))
    p.release.set(); send(w, page)
    runner = w.analyst_runner
    thread, worker = runner.thread, runner.worker
    snapshot = page.exchanges[-1].snapshot
    # Do not deliver queued GUI callbacks until native worker destruction is done.
    assert thread.wait(2000)
    assert not isValid(worker)
    del worker.snapshot  # Queued callbacks must use their Python payload, never this wrapper.
    assert runner.cancellation is snapshot.cancellation
    if cancel:
        assert runner.cancel()
    wait(app, lambda: not runner.running)
    assert page.exchanges[-1].outcome_status == ('cancelled' if cancel else 'answered')
    if cancel:
        assert delivered == []
    else:
        assert len(delivered) == 1
        assert delivered[0][0] is snapshot and delivered[0][1].response is p.response
        assert delivered[0][2] is app.thread()
    assert runner.worker is None and runner.thread is None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(thread)


def test_duplicate_completion_and_finished_callbacks_deliver_once(setup):
    from cyber_analyst.ui.analyst_runner import _AnalystCompletion
    from cyber_analyst.app.analyst import AnalystRunResult
    app, p, w, page = setup
    delivered = []
    w.analyst_runner.succeeded.connect(lambda *args: delivered.append(args))
    p.release.set(); send(w, page)
    snapshot = page.exchanges[-1].snapshot
    runner = w.analyst_runner
    wait(app, lambda: not runner.running)
    answer = page.exchanges[-1].answer.toPlainText()
    completion = _AnalystCompletion(snapshot, AnalystRunResult(p.response), None)
    runner._receive_completion(completion)
    runner._thread_finished()
    runner._complete(snapshot.cancellation)
    app.processEvents()
    assert len(delivered) == 1 and page.exchanges[-1].answer.toPlainText() == answer
    assert runner._snapshot is None and runner._completion is None
    assert not runner._thread_finished_received


def test_native_cleanup_readiness_does_not_block_or_complete_early(setup, monkeypatch):
    from PySide6.QtCore import QThread
    app, p, w, page = setup
    p.release.set(); send(w, page)
    runner = w.analyst_runner
    thread = runner.thread
    assert thread.wait(2000)
    original_wait = QThread.wait
    checks = []
    def ready(self, timeout):
        assert timeout == 0, 'GUI cleanup must never wait for a running thread'
        checks.append(timeout)
        if len(checks) == 1:
            assert runner.running and page.exchanges[-1].outcome_status == 'running'
            assert runner.cancellation.completed_at is None
            return False
        return original_wait(self, timeout)
    monkeypatch.setattr(QThread, 'wait', ready)
    wait(app, lambda: not runner.running)
    assert len(checks) >= 2 and page.exchanges[-1].outcome_status == 'answered'


def test_exception_payload_preserved_after_native_worker_destruction(setup):
    from shiboken6 import isValid
    app, p, w, page = setup
    cause = ConnectionResetError('closed')
    error = AIProviderError('provider failure')
    error.__cause__ = cause
    p.error = error
    delivered = []
    w.analyst_runner.failed.connect(lambda snapshot, result: delivered.append(result))
    p.release.set(); send(w, page)
    thread, worker = w.analyst_runner.thread, w.analyst_runner.worker
    assert thread.wait(2000) and not isValid(worker)
    del worker.snapshot
    wait(app, lambda: not w.analyst_runner.running)
    assert delivered == [error] and delivered[0].__cause__ is cause
    assert page.exchanges[-1].outcome_status == 'error'
