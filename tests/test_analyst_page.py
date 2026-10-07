import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import time
from threading import Event
from dataclasses import replace
import pytest
from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from cyber_analyst.analyst import AnalystResponse, AnalystObservation, AnalystReference
from cyber_analyst.app.analyst import AnalystRunResult
from cyber_analyst.ui.main_window import MainWindow
from cyber_analyst.ai.models import AIProviderError, AIStructuredOutputError
from test_investigation_context import synthetic


def wait(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


class Pipeline:
    def __init__(self):
        self.release = Event()
        self.calls = []
        self.error = None
        self.response = AnalystResponse('answered', 'Observed facts', (
            AnalystObservation('"ana" is represented as a "username" entity.',
                               (AnalystReference('entity', 'ana'),), ('fact_stable',)),),
            ('Correlation does not establish causation.',))

    def answer(self, request, context, state, view, *, cancellation=None):
        self.calls.append((request, context, state, view, QThread.currentThread()))
        deadline = time.monotonic() + 5
        while not self.release.wait(.005):
            if cancellation is not None:
                cancellation.check()
            if time.monotonic() >= deadline:
                raise RuntimeError('Test release timed out')
        if self.error:
            raise self.error
        return AnalystRunResult(self.response, (('Provider', 'Fake'), ('Provider calls', 2)))


@pytest.fixture
def setup(monkeypatch):
    from cyber_analyst.ai import AIService, LlamaRuntime
    import polars as pl
    import duckdb
    def forbidden(*a, **k): raise AssertionError('Unrequested computation/runtime')
    for obj, name in ((AIService, 'generate_structured'), (LlamaRuntime, 'start'),
                      (pl.LazyFrame, 'collect'), (duckdb, 'connect')):
        monkeypatch.setattr(obj, name, forbidden)
    app = QApplication.instance() or QApplication([])
    p = Pipeline()
    w = MainWindow(analyst_pipeline=p)
    w.show()
    w.navigation.button(6).click()
    yield app, p, w, w.analyst_page
    p.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    from shiboken6 import isValid
    if isValid(w):
        w.close()
    app.processEvents()


def send(w, page, question='What is recorded?'):
    if w.investigation_session.context is None:
        w.set_investigation(synthetic())
    page.question.setPlainText(question)
    page.send_button.click()


def test_navigation_empty_and_configuration(setup):
    app, p, w, page = setup
    assert w.pages.currentWidget() is page
    assert not page.send_button.isEnabled() and not page.question.isEnabled()
    assert page.empty.isVisible() and not p.calls
    w.set_investigation(synthetic())
    assert page.question.isEnabled() and not page.empty.isVisible()
    w.analyst_runner.pipeline = None
    page.refresh_controls()
    assert not page.question.isEnabled() and 'Settings' in page.status.text()


def test_investigation_run_blocks_analyst_submission(setup):
    app, p, w, page = setup
    w.set_investigation(synthetic())
    w.investigation_runner.thread = object()
    try:
        w._update_run_controls()
        page.question.setPlainText('What is recorded?')
        page.submit()
        assert not page.send_button.isEnabled() and not p.calls
        with pytest.raises(ValueError): w._apply_runtime_config(object())
    finally:
        w.investigation_runner.thread = None
        w._update_run_controls()
    assert page.send_button.isEnabled()


def test_whitespace_and_ctrl_enter_background_responsive(setup):
    app, p, w, page = setup
    w.set_investigation(synthetic())
    page.question.setPlainText(' \n ')
    page.submit()
    assert not p.calls and not page.exchanges
    page.question.setPlainText('Question\nsecond line')
    QTest.keyClick(page.question, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    wait(app, lambda: bool(p.calls))
    assert p.calls[0][0].question == 'Question\nsecond line'
    assert p.calls[0][-1] != app.thread()
    assert not page.send_button.isEnabled() and not page.question.isEnabled()
    page.submit()
    with pytest.raises(ValueError): w.analyst_runner.start(page.exchanges[0].snapshot)
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(True))
    wait(app, lambda: bool(ticks))
    w.navigation.button(2).click()
    assert w.pages.currentWidget() is w.findings_page and len(p.calls) == 1
    assert not w.settings_page.isEnabled() and not w.workspace.run_button.isEnabled()
    with pytest.raises(ValueError): w._apply_runtime_config(object())
    p.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    assert page.question.isEnabled() and w.analyst_runner.thread is None and w.analyst_runner.worker is None


def test_rendering_exact_plain_text_references_limitations(setup):
    app, p, w, page = setup
    p.response = replace(p.response, summary='Fatos observados <b>dados</b>',
                         observations=(replace(p.response.observations[0], text='ana é uma entidade.\nValor preservado.'),))
    page.language.setCurrentIndex(1)
    send(w, page)
    p.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    e = page.exchanges[0]
    assert e.answer.toPlainText() == 'Fatos observados <b>dados</b>\n\nana é uma entidade.\nValor preservado.'
    assert e.answer.isReadOnly()
    assert len(e.references.items) == 1
    item = e.references.items[0]
    assert item.reference == AnalystReference('entity', 'ana')
    assert item.label.text() == 'entity | ana | directory, remote_access'
    assert item.identity.text() == item.identity.toolTip() == 'ana'
    assert e.limitations.text() == 'Limitations\nCorrelation does not establish causation.'
    assert not e.diagnostics.isVisible()
    e.diagnostic_button.click()
    assert 'Provider calls: 2' in e.diagnostics.toPlainText()
    assert p.calls[0][0].response_language == 'pt-BR'


def test_input_stays_in_active_workspace_viewport(setup):
    app, p, w, page = setup
    p.release.set()
    send(w, page)
    wait(app, lambda: not w.analyst_runner.running)
    app.processEvents()
    viewport = w.pages.parentWidget()
    from PySide6.QtCore import QPoint
    bottom = page.send_button.mapTo(viewport, QPoint(0, page.send_button.height() - 1))
    assert 0 <= bottom.y() < viewport.height()
    assert page.conversation.height() > 0
    assert page.width() <= viewport.width()
    w.workspace.inspector_button.setChecked(False)
    w.resize(640, 400)
    app.processEvents()
    bottom = page.send_button.mapTo(viewport, QPoint(0, page.send_button.height() - 1))
    assert 0 <= bottom.y() < viewport.height()


def test_insufficient_is_normal_localized_answer(setup):
    app, p, w, page = setup
    p.response = AnalystResponse('insufficient_context', 'O contexto fornecido não sustenta uma resposta a esta pergunta.', (), ())
    send(w, page)
    p.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    e = page.exchanges[0]
    assert e.answer.toPlainText() == p.response.summary
    assert not e.references.items and not e.limitations.isVisible()
    assert e.outcome_status == 'insufficient_context' and e.result_status.text() == 'Insufficient context'
    assert page.status.text() == 'Ready'


@pytest.mark.parametrize('error', [AIProviderError('offline'), AIStructuredOutputError('schema_mismatch', 3),
                                 TimeoutError('timed out'), ValueError('missing runtime')])
def test_failure_preserves_transcript_and_restores_controls(setup, error):
    app, p, w, page = setup
    p.release.set()
    send(w, page)
    wait(app, lambda: not w.analyst_runner.running)
    first = page.exchanges[0].answer.toPlainText()
    p.error = error
    send(w, page, 'Second independent question')
    wait(app, lambda: not w.analyst_runner.running)
    assert len(page.exchanges) == 2 and page.exchanges[0].answer.toPlainText() == first
    assert page.exchanges[1].answer.toPlainText() != 'Running...'
    assert page.exchanges[0].result_status.text() == 'Answered'
    assert page.exchanges[1].result_status.text() == 'Execution failed'
    assert page.exchanges[1].outcome_status == 'error'
    assert page.question.isEnabled() and page.status.text() == 'Ready'
    assert p.calls[1][0].question == 'Second independent question'
    assert set(p.calls[1][0].__dataclass_fields__) == {'question', 'response_language', 'scope'}
    page.question.setPlainText('Try again')
    assert page.send_button.isEnabled()


def test_snapshot_filters_focus_and_replacement(setup):
    from cyber_analyst.context import StateService
    app, p, w, page = setup
    w.set_investigation(synthetic())
    session = w.investigation_session
    session.set_dataset_scope(['remote_access'])
    session.set_state(StateService().focus_entity(session.state, session.context, 'ana'))
    snapshot = (session.context, session.state, session.view)
    page.scope.setCurrentIndex(1)
    send(w, page)
    wait(app, lambda: bool(p.calls))
    assert all(actual is expected for actual, expected in zip(p.calls[0][1:4], snapshot))
    assert p.calls[0][0].scope == 'current_focus' and session.state is snapshot[1]
    w.set_investigation(synthetic())
    assert session.context is not snapshot[0]
    p.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    assert 'remote_access' in page.exchanges[0].snapshot_label.text()
    send(w, page, 'New investigation question')
    wait(app, lambda: not w.analyst_runner.running)
    assert p.calls[1][1] is session.context and p.calls[1][2] is session.state
    assert page.exchanges[1].snapshot.investigation_number == 2


def test_clear_transcript_and_session_cleanup(setup):
    app, p, w, page = setup
    p.release.set()
    send(w, page)
    wait(app, lambda: not w.analyst_runner.running)
    state = w.investigation_session.state
    page.clear_button.click()
    assert not page.exchanges and w.investigation_session.state is state
    send(w, page)
    wait(app, lambda: not w.analyst_runner.running)
    w.investigation_session.clear()
    assert len(page.exchanges) == 1 and not page.question.isEnabled()
    assert w.analyst_runner.thread is None


def test_close_waits_safely_then_cleans_thread(setup):
    app, p, w, page = setup
    send(w, page)
    wait(app, lambda: bool(p.calls))
    w.close()
    assert w.isVisible() and w.analyst_runner.running
    p.release.set()
    wait(app, lambda: not w.isVisible())
    assert w.analyst_runner.thread is None and w.analyst_runner.worker is None


def test_quit_shutdown_joins_worker(setup):
    app, p, w, page = setup
    p.release.set()
    send(w, page)
    w.analyst_runner.shutdown()
    assert w.analyst_runner.thread is None and w.analyst_runner.worker is None


def test_deleted_page_has_no_worker_callbacks(setup):
    from PySide6.QtCore import QCoreApplication, QEvent
    app, p, w, page = setup
    send(w, page)
    wait(app, lambda: bool(p.calls))
    # The runner belongs to MainWindow, so deleting the receiver does not destroy its thread.
    w.analyst_page = type('ClosedPage', (), {'set_execution_blocked': lambda *a: None})()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    p.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    assert w.analyst_runner.worker is None
