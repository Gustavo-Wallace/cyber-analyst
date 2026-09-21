import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from dataclasses import replace
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QListWidgetItem
from cyber_analyst.ui.main_window import MainWindow
from cyber_analyst.context import StateService
from test_investigation_context import synthetic


@pytest.fixture
def window(monkeypatch):
    from cyber_analyst.ai import AIService,LlamaRuntime
    import polars as pl
    def forbidden(*a,**k):raise AssertionError('backend execution')
    monkeypatch.setattr(AIService,'generate_structured',forbidden)
    monkeypatch.setattr(LlamaRuntime,'start',forbidden)
    monkeypatch.setattr(pl.LazyFrame,'collect',forbidden)
    app=QApplication.instance() or QApplication([])
    w=MainWindow();w.show();app.processEvents()
    yield w
    w.close();app.processEvents()


def choose(w,query,kind):
    w.workspace.search.setText(query)
    items=w.workspace.search_results
    item=next(items.item(i) for i in range(items.count()) if items.item(i).data(Qt.ItemDataRole.UserRole).kind==kind)
    items.itemActivated.emit(item)


def test_binding_all_focus_hidden_clear(window):
    w=window;s=w.investigation_session
    assert not w.workspace.search.isEnabled()
    assert 'Select an investigation object' in w.context_inspector.details.toPlainText()
    result=synthetic();w.set_investigation(result)
    assert s.result is result and s.context and s.state and s.view
    assert w.workspace.search.isEnabled()
    choose(w,'ana','entity')
    assert s.state.focus.entity_id=='ana'
    assert 'username / ana' in w.context_inspector.details.toPlainText()
    choose(w,'remote_access','dataset')
    assert 'Analyses: 1' in w.context_inspector.details.toPlainText()
    choose(w,'f2','finding')
    assert 'Attention: medium' in w.context_inspector.details.toPlainText()
    assert 'Operation: unique_count' in w.context_inspector.details.toPlainText()
    choose(w,'remote','analysis')
    assert s.state.focus.analysis.dataset_name=='remote_access'
    assert s.state.focus.analysis.analysis_id=='count'
    w.context_dock.hide()
    choose(w,'ana','entity')
    assert not w.context_dock.isVisible()
    assert 'username / ana' in w.context_inspector.details.toPlainText()
    w.context_dock.show()
    assert 'username / ana' in w.context_inspector.details.toPlainText()
    s.clear_focus()
    assert 'Select an investigation object' in w.context_inspector.details.toPlainText()
    s.clear()
    assert not w.workspace.search.isEnabled() and s.result is None and s.context is None and s.state is None and s.view is None
    assert w.workspace.search_results.count()==0


def test_stale_search_safe_and_transactional_load(window):
    w=window;w.set_investigation(synthetic());s=w.investigation_session
    result=next(r for r in s.search('ana') if r.target_id=='email')
    item=QListWidgetItem();item.setData(Qt.ItemDataRole.UserRole,result)
    s.set_state(StateService().set_dataset_scope(s.state,s.context,['remote_access']))
    before=s.state
    w._navigate_search_item(item)
    assert s.state is before and w.workspace.search_results.count()==0
    assert 'hidden' in w.statusBar().currentMessage()
    old=s.result
    with pytest.raises(ValueError):s.load(replace(synthetic(),findings=None))
    assert s.result is old
