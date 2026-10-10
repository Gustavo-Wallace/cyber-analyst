import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import time
from threading import Event
import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from cyber_analyst.ui.main_window import MainWindow
from cyber_analyst.investigation.models import InvestigationPipelineError
from test_investigation_context import synthetic


def wait(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


class Pipeline:
    def __init__(self, result):
        self.result = result
        self.release = Event()
        self.calls = []
        self.error = None

    def run(self, datasets):
        self.calls.append((datasets, QThread.currentThread()))
        if not self.release.wait(5):
            raise RuntimeError('Test worker timed out')
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def setup(monkeypatch):
    from cyber_analyst.ai import AIService, LlamaRuntime
    def forbidden(*a, **k): raise AssertionError('UI-side AI call')
    monkeypatch.setattr(AIService, 'generate_structured', forbidden)
    monkeypatch.setattr(LlamaRuntime, 'start', forbidden)
    app = QApplication.instance() or QApplication([])
    pipeline = Pipeline(synthetic())
    w = MainWindow(investigation_pipeline=pipeline)
    w.show()
    yield app, pipeline, w
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    w.close()
    app.processEvents()


def load(w, pipeline):
    for entry in pipeline.result.datasets:
        w.collection.add(entry.dataset)
    w._collection_changed()


def test_success_snapshot_thread_and_controls(setup):
    app, pipeline, w = setup
    assert w.workspace.run_button.text() == 'Add datasets'
    assert w.workspace.run_button.isEnabled()
    w.workspace.run_button.click()
    assert w.pages.currentWidget() is w.datasets_page and not pipeline.calls
    load(w, pipeline)
    assert w.workspace.run_button.isEnabled()
    assert w.workspace.run_button.text() == 'Analyze'
    assert w.dashboard_page.primary_button.text() == 'Analyze'
    snapshot = w.collection.values()
    w.workspace.run_button.click()
    wait(app, lambda: bool(pipeline.calls))
    assert pipeline.calls[0][0] == snapshot
    assert all(a is b for a,b in zip(pipeline.calls[0][0], snapshot))
    assert pipeline.calls[0][1] != app.thread()
    assert w.workspace.run_status.text() == 'Running investigation...'
    assert not w.workspace.run_button.isEnabled() and not w.datasets_page.isEnabled()
    assert not w.workspace.search.isEnabled()
    with pytest.raises(ValueError): w.investigation_runner.start(snapshot)
    app.processEvents()
    assert w.investigation_runner.running and len(pipeline.calls) == 1
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert w.investigation_session.result is pipeline.result
    assert w.pages.currentWidget() is w.overview_page
    assert w.workspace.run_button.text() == 'Analyze again'
    assert w.workspace.search.isEnabled() and w.workspace.filters.datasets.isEnabled()
    assert w.findings_page.table.rowCount() == 2 and w.relations_page.table.rowCount() == 2
    assert w.workspace.run_status.text() == 'Completed'
    assert w.investigation_runner.worker is None and w.investigation_runner.thread is None
    assert w.datasets_page.isEnabled() and w.workspace.run_button.isEnabled()


def test_failed_replacement_preserves_previous(setup):
    app, pipeline, w = setup
    load(w, pipeline)
    previous = synthetic()
    w.set_investigation(previous)
    state = w.investigation_session.state
    pipeline.error = InvestigationPipelineError('findings', None, ValueError('controlled failure'))
    w.workspace.run_button.click()
    assert w.workspace.search.isEnabled()
    assert w.investigation_session.result is previous
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert w.investigation_session.result is previous and w.investigation_session.state is state
    assert w.workspace.run_status.text() == 'Failed'
    assert 'findings' in w.statusBar().currentMessage() and 'controlled failure' in w.statusBar().currentMessage()
    assert w.investigation_runner.worker is None and w.investigation_runner.thread is None
    assert w.workspace.run_button.isEnabled()


@pytest.mark.parametrize('failure', [False, True])
def test_close_defers_until_worker_finishes(setup, failure):
    app, pipeline, w = setup
    load(w, pipeline)
    if failure:
        pipeline.error = RuntimeError('controlled failure while closing')
    w.workspace.run_button.click()
    wait(app, lambda: bool(pipeline.calls))
    w.close()
    assert w.isVisible() and w.investigation_runner.running
    pipeline.release.set()
    wait(app, lambda: not w.isVisible())
    assert w.investigation_runner.thread is None
    assert w.investigation_runner.worker is None


def test_no_pipeline_still_loads_datasets(setup):
    app, pipeline, _ = setup
    w = MainWindow()
    try:
        load(w, pipeline)
        assert not w.workspace.run_button.isEnabled()
        assert 'No investigation pipeline' in w.workspace.run_button.toolTip()
        assert w.datasets_page.isEnabled()
    finally:
        w.close()


def test_successful_rerun_keeps_inspected_destination(setup):
    app, pipeline, w = setup
    load(w, pipeline)
    w.set_investigation(synthetic())
    w.navigation.button(2).click()
    w.workspace.run_button.click()
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert w.investigation_session.result is pipeline.result
    assert w.pages.currentWidget() is w.findings_page
    assert w.navigation.checkedId() == 0


def test_dashboard_action_reuses_data_and_runner(setup):
    app, pipeline, w = setup
    w.dashboard_page.primary_button.click()
    assert w.pages.currentWidget() is w.datasets_page
    load(w, pipeline)
    w.navigation.button(0).click()
    w.dashboard_page.primary_button.click()
    wait(app, lambda: bool(pipeline.calls))
    assert len(pipeline.calls) == 1
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert w.investigation_session.result is pipeline.result


@pytest.mark.parametrize('replacement', ['load', 'clear'])
@pytest.mark.parametrize('failure', [False, True])
def test_inflight_result_cannot_overwrite_newer_session(setup, replacement, failure):
    app, pipeline, w = setup
    load(w, pipeline)
    w.set_investigation(synthetic())
    w.workspace.run_button.click()
    wait(app, lambda: bool(pipeline.calls))
    session = w.investigation_session
    if replacement == 'load':
        w.set_investigation(synthetic())
        session.set_dataset_scope(('directory',))
        session.navigate(next(iter(session.search('ana'))))
    else:
        session.clear()
    before = (session.result, session.context, session.state, session.view)
    if failure:
        pipeline.error = RuntimeError('obsolete failure')
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert all(a is b for a, b in zip(before, (session.result, session.context, session.state, session.view)))
    assert w.workspace.run_status.text() != 'Completed'
    assert w.workspace.run_button.isEnabled()


def test_clear_during_first_run_discards_late_result(setup):
    app, pipeline, w = setup
    load(w, pipeline)
    w.workspace.run_button.click()
    wait(app, lambda: bool(pipeline.calls))
    w.investigation_session.clear()
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert w.investigation_session.result is None
    assert not w.workspace.search.isEnabled()
    assert w.workspace.run_status.text() == 'Investigation changed'


@pytest.mark.parametrize('previous', [False, True])
def test_failure_then_successful_retry_preserves_state_until_completion(setup, previous):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid
    app, pipeline, w = setup
    load(w, pipeline)
    session = w.investigation_session
    if previous:
        session.load(synthetic())
        session.set_dataset_scope(('directory',))
        session.set_entity_types(('username',))
        session.set_attention_levels(('high',))
        session.navigate(next(iter(session.search('ana'))))
    before = (session.result, session.context, session.state, session.view)
    pipeline.error = InvestigationPipelineError('analysis_execution', None, ValueError('controlled'))
    w.workspace.run_button.click()
    old_thread, old_worker = w.investigation_runner.thread, w.investigation_runner.worker
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert all(a is b for a, b in zip(before, (session.result, session.context, session.state, session.view)))
    assert w.workspace.run_status.text() == 'Failed'
    assert w.workspace.search.isEnabled() == previous
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(old_thread) and not isValid(old_worker)
    if previous:
        assert all(r.kind != 'finding' for r in session.search('low'))
    pipeline.error = None
    pipeline.release.clear()
    w.workspace.run_button.click()
    assert all(a is b for a, b in zip(before, (session.result, session.context, session.state, session.view)))
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert w.workspace.run_status.text() == 'Completed'
    assert session.result is pipeline.result and len(pipeline.calls) == 2


def test_filter_changes_during_run_do_not_invalidate_result(setup):
    app, pipeline, w = setup
    load(w, pipeline)
    session = w.investigation_session
    session.load(synthetic())
    generation = session.generation
    w.workspace.run_button.click()
    session.set_dataset_scope(('directory',))
    session.navigate(next(iter(session.search('ana'))))
    assert session.generation == generation
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert session.result is pipeline.result
    assert w.workspace.run_status.text() == 'Completed'


def test_invalid_completed_result_never_replaces_valid_session(setup):
    from dataclasses import replace
    from cyber_analyst.entities import EntityResult
    app, pipeline, w = setup
    load(w, pipeline)
    w.set_investigation(synthetic())
    session = w.investigation_session
    session.set_dataset_scope(('directory',))
    before = (session.result, session.context, session.state, session.view, session.generation)
    valid = pipeline.result
    pipeline.result = replace(valid, entities=EntityResult(valid.entities.entities * 2))
    w.workspace.run_button.click()
    pipeline.release.set()
    wait(app, lambda: not w.investigation_runner.running)
    assert (session.result, session.context, session.state, session.view, session.generation) == before
    assert w.workspace.run_status.text() == 'Failed'
    pipeline.result = valid
    w.workspace.run_button.click()
    wait(app, lambda: not w.investigation_runner.running)
    assert session.result is valid and w.workspace.run_status.text() == 'Completed'
