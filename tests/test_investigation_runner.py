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
    assert not w.workspace.run_button.isEnabled()
    load(w, pipeline)
    assert w.workspace.run_button.isEnabled()
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


def test_close_defers_until_worker_finishes(setup):
    app, pipeline, w = setup
    load(w, pipeline)
    w.workspace.run_button.click()
    wait(app, lambda: bool(pipeline.calls))
    w.close()
    assert w.isVisible() and w.investigation_runner.running
    pipeline.release.set()
    wait(app, lambda: not w.isVisible())
    assert w.investigation_runner.thread is None


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
