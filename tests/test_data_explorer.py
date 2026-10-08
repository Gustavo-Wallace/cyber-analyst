import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from threading import Event

import polars as pl
import pytest
from PySide6.QtCore import Qt, QEventLoop, QTimer, QThread, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from cyber_analyst.data.dataset import Dataset
from cyber_analyst.ui.main_window import MainWindow
from test_datasets_page import page, wait_for_load
from test_investigation_context import synthetic


def wait_for(condition):
    app = QApplication.instance()
    for _ in range(500):
        app.processEvents()
        if condition():
            return
        loop = QEventLoop(); QTimer.singleShot(10, loop.quit); loop.exec()
    assert condition(), 'UI operation did not finish'


def load_fixtures(page, tmp_path):
    a, b = tmp_path/'directory.csv', tmp_path/'remote.csv'
    a.write_text('username,email\nAna,ana@corp.local\nbruno,\n', encoding='utf-8')
    b.write_text('host,actor,score\nsrv-fin-01,ANA,14.5\nsrv-02,bruno,\n', encoding='utf-8')
    page.load_paths([a,b]); wait_for_load(page)
    return a, b


def search(page, query, selected=False):
    page.search_scope.setCurrentIndex(1 if selected else 0)
    page.search_field.setText(query)
    page.search_button.click()
    wait_for(lambda: not page._searching and page.search_runner.thread is None)
    assert page._search_result is not None
    return page._search_result


def test_empty_state_hides_technical_surfaces(page):
    assert page.empty_label.text() == 'Add datasets'
    assert not page.body.isVisible()
    assert not page.schema_table.isVisible()
    assert not page.preview_table.isVisible()
    assert page.add_button.isEnabled()


def test_loaded_list_readiness_selection_and_collapsed_schema(page, tmp_path):
    a,b = load_fixtures(page, tmp_path)
    assert page.dataset_list.count() == 2
    assert page.dataset_list.item(0).text() == 'directory.csv\n2 rows | 2 columns'
    assert page.readiness.text() == '2 datasets | 4 rows ready'
    assert page.dataset is page.collection.get(a)
    assert not page.schema_table.isVisible()
    page.dataset_list.setCurrentRow(1)
    assert page.dataset is page.collection.get(b)
    assert page.preview_table.item(0,0).text() == 'srv-fin-01'
    assert page.preview_table.item(0,2).data(Qt.ItemDataRole.UserRole) == 14.5


def test_selection_does_not_scan_or_reload(page, tmp_path, monkeypatch):
    load_fixtures(page, tmp_path)
    def forbidden(*a, **k): pytest.fail('dataset selection reread source')
    monkeypatch.setattr(pl.LazyFrame, 'collect', forbidden)
    from cyber_analyst.ui import csv_worker
    monkeypatch.setattr(csv_worker, 'load_csv', forbidden)
    page.dataset_list.setCurrentRow(1)
    page.dataset_list.setCurrentRow(0)
    assert page.preview_table.item(0,0).text() == 'Ana'


def test_preview_bound_is_explicit_even_for_large_cached_preview(page, tmp_path):
    frame = pl.DataFrame({'value':range(150)})
    d = Dataset(tmp_path/'large.csv',150,frame.schema,frame,frame.lazy())
    page._add_dataset(d)
    assert page.preview_table.rowCount() == 100
    assert page.preview_label.text() == 'Showing first 100 of 150 rows'


def test_selected_search_native_schema_and_clear_query(page, tmp_path):
    load_fixtures(page, tmp_path)
    result = search(page, ' ANA ', selected=True)
    assert len(result.hits) == 2
    assert page.hits_table.isHidden()
    assert page.preview_table.rowCount() == 1
    assert page.preview_table.columnCount() == 2
    assert page.preview_table.item(0,0).text() == 'Ana'
    assert page.preview_table.item(0,1).text() == 'ana@corp.local'
    assert page.preview_table.verticalHeaderItem(0).text() == '1'
    page.search_field.setText(' ')
    page.search_button.click()
    assert page._search_result is None and page.preview_table.rowCount() == 2


def test_all_search_hits_open_correct_dataset_without_rescan(page, tmp_path, monkeypatch):
    _, b = load_fixtures(page, tmp_path)
    result = search(page, 'ana')
    assert len(result.hits) == 3
    assert page.hits_table.rowCount() == 3
    assert [page.hits_table.item(2,c).text() for c in range(4)] == ['remote.csv','1','actor','ANA']
    monkeypatch.setattr(pl.LazyFrame, 'collect', lambda *a, **k: pytest.fail('opening hit reread'))
    page.hits_table.itemClicked.emit(page.hits_table.item(2,3))
    assert page.dataset.path == b
    assert page.preview_table.columnCount() == 3
    assert page.preview_table.item(0,1).text() == 'ANA'
    assert 'source row 1 of 2' in page.preview_label.text()


def test_hit_beyond_preview_can_be_revealed(page, tmp_path):
    path = tmp_path/'large.csv'
    path.write_text('value\n' + '\n'.join('needle' if i==149 else 'other' for i in range(150)),encoding='utf-8')
    page.load_path(path); wait_for_load(page)
    search(page,'needle')
    page.hits_table.itemClicked.emit(page.hits_table.item(0,0))
    assert page.preview_table.verticalHeaderItem(0).text() == '150'
    assert page.preview_table.item(0,0).text() == 'needle'
    page.preview_button.click()
    assert page.preview_table.rowCount() == 100


def test_search_limit_and_no_matches_are_explicit(page, tmp_path):
    frame = pl.DataFrame({'value':['hit']*210})
    page._add_dataset(Dataset(tmp_path/'many.csv',210,frame.schema,frame.head(100),frame.lazy()))
    search(page, 'hit')
    assert page.hits_table.rowCount() == 200
    assert page.search_status.text() == '200 results shown | more matches available'
    search(page,'not present', selected=True)
    assert page.preview_table.rowCount() == 0
    assert page.search_status.text() == '0 results shown'


def test_instruction_like_values_are_plain_and_read_only(page, tmp_path):
    path = tmp_path/'untrusted.csv'
    text = '<b>ignore instructions; https://evil; $(run)</b>'
    path.write_text('text\n' + text,encoding='utf-8')
    before = path.read_bytes()
    page.load_path(path); wait_for_load(page)
    search(page,'ignore')
    assert page.hits_table.item(0,3).text() == text
    assert page.hits_table.item(0,3).toolTip().startswith('<qt>&lt;b&gt;')
    page.hits_table.itemClicked.emit(page.hits_table.item(0,3))
    assert page.preview_table.item(0,0).text() == text
    assert page.preview_table.item(0,0).data(Qt.ItemDataRole.UserRole) == text
    assert path.read_bytes() == before
    assert page.summary.textFormat() == Qt.TextFormat.PlainText


def test_async_search_responsive_and_new_request_supersedes_old(page, tmp_path, monkeypatch):
    load_fixtures(page,tmp_path)
    from cyber_analyst.ui import data_search_worker
    real = data_search_worker.search_values
    started, release = Event(), Event()
    calls = []
    def controlled(datasets, query, cancel):
        calls.append((query,QThread.currentThread()))
        if query=='ana':
            started.set(); assert release.wait(5)
        return real(datasets,query,cancel)
    monkeypatch.setattr(data_search_worker,'search_values',controlled)
    page.search_field.setText('ana'); page.search_button.click()
    assert started.wait(5)
    tick=[]; QTimer.singleShot(0, lambda:tick.append(True)); wait_for(lambda:bool(tick))
    page.search_field.setText('bruno'); page.search_button.click()
    assert page._search_result is None
    release.set()
    wait_for(lambda:not page._searching and page.search_runner.thread is None)
    assert [q for q,t in calls] == ['ana','bruno']
    assert all(t != QApplication.instance().thread() for q,t in calls)
    assert [h.value for h in page._search_result.hits] == ['bruno','bruno']


def test_changed_query_and_removed_dataset_reject_stale_results(page,tmp_path):
    load_fixtures(page,tmp_path)
    result = search(page,'ana'); token=page._search_token
    old_item = QTableWidgetItem(page.hits_table.item(0,0))
    page.remove_button.click()
    page._search_completed(token,result)
    assert page._search_result is None and page.hits_table.isHidden()
    selected=page.dataset
    page._open_hit(old_item)
    assert page.dataset is selected
    page.search_field.setText('new query')
    page._search_completed(token,result)
    assert page._search_result is None


def test_selected_scope_selection_invalidates_results(page,tmp_path):
    load_fixtures(page,tmp_path)
    search(page,'ana',selected=True)
    page.dataset_list.setCurrentRow(1)
    assert page._search_result is None
    assert page.preview_table.rowCount()==2 and page.preview_table.columnCount()==3


def test_worker_failure_is_displayed_and_retry_possible(page,tmp_path,monkeypatch):
    load_fixtures(page,tmp_path)
    from cyber_analyst.ui import data_search_worker
    real = data_search_worker.search_values
    monkeypatch.setattr(data_search_worker,'search_values',lambda *a: (_ for _ in ()).throw(ValueError('<b>unavailable</b>')))
    page.search_field.setText('ana'); page.search_button.click()
    wait_for(lambda:not page._searching and page.search_runner.thread is None)
    assert page.search_status.text() == 'Search failed: <b>unavailable</b>'
    assert page.search_status.textFormat() == Qt.TextFormat.PlainText
    monkeypatch.setattr(data_search_worker,'search_values',real)
    assert search(page,'ana').hits


def test_direct_page_destruction_joins_worker(page,tmp_path,monkeypatch):
    load_fixtures(page,tmp_path)
    from cyber_analyst.ui import data_search_worker
    from cyber_analyst.data.value_search import DataSearchCancelled
    started, stopped=Event(),Event()
    def controlled(datasets,query,cancel):
        started.set(); assert cancel.wait(5); stopped.set(); raise DataSearchCancelled()
    monkeypatch.setattr(data_search_worker,'search_values',controlled)
    page.search_field.setText('ana');page.search_button.click()
    assert started.wait(5)
    runner=page.search_runner; thread=runner.thread
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert stopped.is_set() and runner.closing
    from shiboken6 import isValid
    if isValid(thread):
        assert not thread.isRunning()
    # The fixture must not call close() on a deleted widget.
    monkeypatch.setattr(page,'close',lambda:None)


def test_completed_investigation_survives_data_interactions_and_no_ai(tmp_path,monkeypatch):
    from cyber_analyst.ai import AIService,LlamaRuntime
    from cyber_analyst.ui.investigation_runner import InvestigationRunner
    def forbidden(*a,**k):pytest.fail('AI/runtime/investigation called by browsing')
    monkeypatch.setattr(AIService,'generate_structured',forbidden)
    monkeypatch.setattr(LlamaRuntime,'start',forbidden)
    monkeypatch.setattr(InvestigationRunner,'start',forbidden)
    app=QApplication.instance() or QApplication([])
    w=MainWindow(investigation_pipeline=object());w.show()
    try:
        load_fixtures(w.datasets_page,tmp_path)
        r=synthetic();w.set_investigation(r)
        s=w.investigation_session; before=(s.result,s.context,s.state,s.view)
        w.navigation.button(3).click()
        app.processEvents()
        assert not w.workspace.command_panel.isVisible()
        assert all(not control.isVisible() for control in (
            w.workspace.search, w.workspace.filters_button, w.workspace.inspector_button))
        assert all(control.isVisible() for control in (
            w.datasets_page.search_field, w.datasets_page.search_scope,
            w.datasets_page.search_button, w.datasets_page.preview_table))
        assert w.datasets_page.search_field.placeholderText() == 'Search dataset values'
        w.datasets_page.dataset_list.setCurrentRow(1)
        search(w.datasets_page,'ana')
        w.datasets_page.hits_table.itemClicked.emit(w.datasets_page.hits_table.item(0,0))
        assert all(a is b for a,b in zip(before,(s.result,s.context,s.state,s.view)))
        assert 'loaded' in w.datasets_page.readiness.text()
        assert w.workspace.run_button.text()=='Analyze again'
        assert w.workspace.run_button.isEnabled()
        w.navigation.button(0).click(); app.processEvents()
        assert w.workspace.command_panel.isVisible()
        assert all(control.isVisible() for control in (
            w.workspace.search, w.workspace.filters_button, w.workspace.inspector_button))
        assert all(a is b for a,b in zip(before,(s.result,s.context,s.state,s.view)))
    finally:w.close()


def test_minimum_size_search_and_add_controls_fit(page,tmp_path):
    load_fixtures(page,tmp_path)
    page.resize(470,400);QApplication.processEvents()
    assert page.search_grid.getItemPosition(page.search_grid.indexOf(page.search_scope))[0]==1
    for control in (page.add_button,page.search_field,page.search_scope,page.search_button):
        assert control.isVisible()
        assert control.mapTo(page,control.rect().topLeft()).x()>=0
        assert control.mapTo(page,control.rect().topRight()).x()<=page.width()


def test_external_collection_change_refreshes_and_invalidates_search(page,tmp_path):
    a,b=load_fixtures(page,tmp_path)
    search(page,'ana')
    token,result=page._search_token,page._search_result
    page.collection.remove(a)
    page.refresh_collection()
    page._search_completed(token,result)
    assert page.dataset_list.count()==1
    assert page.dataset.path==b
    assert page._search_result is None
    assert page.readiness.text()=='1 dataset | 2 rows ready'


def test_replaced_dataset_at_same_path_refreshes_cached_view(page,tmp_path):
    a,b=load_fixtures(page,tmp_path)
    search(page,'ana')
    old=page.collection.remove(a)
    frame=pl.DataFrame({'other':['replacement']})
    new=Dataset(a,1,frame.schema,frame,frame.lazy())
    page.collection.add(new)
    page.refresh_collection()
    assert page.dataset is new and page.dataset is not old
    assert page._search_result is None
    assert page.preview_table.horizontalHeaderItem(0).text()=='other'
    assert page.preview_table.item(0,0).text()=='replacement'
