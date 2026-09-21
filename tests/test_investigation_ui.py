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


def test_filter_lifecycle_and_multiple_datasets(window):
    w=window;s=w.investigation_session;bar=w.workspace.filters
    assert all(not c.isEnabled() for c in (bar.datasets,bar.entities,bar.attention,bar.clear_button))
    assert bar.summary.text()=='No active investigation'
    w.set_investigation(synthetic())
    assert tuple(bar.datasets.actions_by_value)==('directory','remote_access')
    assert tuple(bar.entities.actions_by_value)==('email','ip_address','username')
    assert set(bar.attention.actions_by_value)=={'informational','low','medium','high'}
    assert bar.summary.text()=='2 datasets \u00b7 3 entities \u00b7 2 relations \u00b7 2 findings'
    original=s.state
    bar.datasets.actions_by_value['remote_access'].trigger()
    assert s.state.dataset_scope==('remote_access',)
    assert s.view.entity_ids==('ana','ip')
    bar.datasets.actions_by_value['directory'].trigger()
    assert s.state.dataset_scope==('directory','remote_access')
    assert len(s.view.entity_ids)==3 and original.dataset_scope==()
    s.clear()
    assert not bar.datasets.actions_by_value and not bar.datasets.isEnabled()
    assert bar.summary.text()=='No active investigation'
    r=synthetic()
    r=replace(r,entities=replace(r.entities,entities=()),relations=replace(r.relations,relations=()))
    w.set_investigation(r)
    assert not bar.entities.actions_by_value
    assert s.state.entity_types==() and bar.datasets.isEnabled()
    assert bar.summary.text()=='2 datasets \u00b7 0 entities \u00b7 0 relations \u00b7 2 findings'


def test_combined_filters_focus_search_and_clear(window):
    w=window;s=w.investigation_session;bar=w.workspace.filters
    r=synthetic()
    r=replace(r,findings=replace(r.findings,findings=(r.findings.findings[0],replace(r.findings.findings[1],attention_level='high'))))
    w.set_investigation(r)
    choose(w,'ana@','entity')
    focus=s.state.focus
    w.workspace.search.setText('ana')
    stale=next(r for r in s.search('ana') if r.target_id=='email')
    assert w.workspace.search_results.count()>0
    bar.datasets.actions_by_value['remote_access'].trigger()
    assert w.workspace.search_results.count()==0 and not w.workspace.search_results.isVisible()
    assert s.state.focus==focus and 'email' not in s.view.entity_ids
    assert 'ana@corp.local' in w.context_inspector.details.toPlainText()
    assert all(r.target_id!='email' for r in s.search('ana'))
    with pytest.raises(ValueError):s.navigate(stale)
    bar.entities.actions_by_value['username'].trigger()
    assert s.view.entity_ids==('ana',) and s.view.relation_ids==()
    bar.entities.actions_by_value['ip_address'].trigger()
    bar.attention.actions_by_value['high'].trigger()
    assert s.view.entity_ids==('ana','ip') and s.view.relation_ids==('r2',)
    assert s.view.finding_ids==('f2',)
    assert bar.summary.text()=='1 datasets \u00b7 2 entities \u00b7 1 relations \u00b7 1 findings'
    bar.clear_button.click()
    assert s.state.focus==focus
    assert s.state.dataset_scope==s.state.entity_types==s.state.attention_levels==()
    assert bar.summary.text()=='2 datasets \u00b7 3 entities \u00b7 2 relations \u00b7 2 findings'
    assert not any(a.isChecked() for c in (bar.datasets,bar.entities,bar.attention) for a in c.actions_by_value.values())


def test_session_filter_errors_are_atomic(window):
    s=window.investigation_session
    with pytest.raises(ValueError,match='No investigation'):s.clear_filters()
    window.set_investigation(synthetic())
    state,view=s.state,s.view
    for operation,value in ((s.set_dataset_scope,['missing']),(s.set_entity_types,['missing']),(s.set_attention_levels,['missing']),(s.set_dataset_scope,['directory','directory'])):
        with pytest.raises(ValueError):operation(value)
        assert s.state is state and s.view is view
    s.set_attention_levels(['high','low'])
    assert s.view.finding_ids==('f1',)
    assert s.view.entity_ids==view.entity_ids and s.view.relation_ids==view.relation_ids
    window.set_investigation(synthetic())
    assert s.state.attention_levels==()
