import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from PySide6.QtCore import Qt
from test_investigation_ui import window
from test_investigation_context import synthetic


def ids(page):
    return tuple(page.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                 for row in range(page.table.rowCount()))


def test_empty_load_select_provenance(window):
    page = window.findings_page
    assert window.pages.widget(2) is page
    assert page.empty.text().startswith('No active investigation') and page.splitter.isHidden()
    assert ids(page) == () and page.details.isReadOnly()
    result = synthetic()
    payload = '{"value":1.234567890123,"text":"<b>unaltered</b>","null":null}'
    evidence = replace(result.findings.evidence[0], payload=payload)
    result = replace(result, findings=replace(result.findings, evidence=(evidence, result.findings.evidence[1])))
    window.set_investigation(result)
    assert ids(page) == window.investigation_session.view.finding_ids == ('f1', 'f2')
    assert page.summary.text() == '2 visible findings   Medium 1   Low 1'
    assert not page.neutral.isHidden() and page.details.isHidden()
    page.table.selectRow(0)
    assert window.investigation_session.state.focus.finding_id == 'f1'
    assert 'f1' in window.context_inspector.details.toPlainText()
    assert page.details.toPlainText() == payload
    assert page.provenance.text() == '\n'.join([
        'Finding: f1', 'Attention: low', 'Evidence ID: e1',
        'Dataset: directory', 'Source type: analysis', 'Operation: unique_count'])
    assert not page.details.isHidden()
    assert page.table.item(0, 1).text() == 'directory'
    assert page.table.item(0, 2).text() == 'unique_count'
    page.table.selectRow(1)
    page.table.itemActivated.emit(page.table.item(1, 0))
    assert window.investigation_session.state.focus.finding_id == 'f2'


def test_filters_hidden_focus_restore_and_lifecycle(window):
    window.set_investigation(synthetic())
    page = window.findings_page
    session = window.investigation_session
    page.table.selectRow(0)
    focus = session.state.focus
    session.set_attention_levels(['medium'])
    assert ids(page) == ('f2',)
    assert session.state.focus == focus
    assert not page.table.selectedItems()
    assert not page.neutral.isHidden() and page.details.isHidden()
    assert 'Attention: low' in window.context_inspector.details.toPlainText()
    session.clear_filters()
    assert ids(page) == ('f1', 'f2') and page.table.selectedItems()
    session.set_dataset_scope(['remote_access'])
    assert ids(page) == ('f2',) and session.state.focus == focus
    session.set_entity_types(['email'])
    assert ids(page) == ('f2',)
    session.set_attention_levels(['high'])
    assert ids(page) == () and page.empty.text().startswith('No findings match') and page.splitter.isHidden()
    window.set_investigation(synthetic())
    assert ids(page) == ('f1', 'f2') and not page.table.selectedItems()
    assert not page.neutral.isHidden() and page.details.isHidden()
    session.clear()
    assert ids(page) == () and not page.table.isEnabled()
    assert page.empty.text().startswith('No active investigation') and page.splitter.isHidden()


def test_search_focus_synchronizes_page_and_long_ids(window):
    result = synthetic()
    long_id = 'finding_' + 'a' * 60
    finding = replace(result.findings.findings[0], finding_id=long_id)
    window.set_investigation(replace(result, findings=replace(result.findings, findings=(finding,))))
    session = window.investigation_session
    session.navigate(next(iter(session.search(long_id))))
    page = window.findings_page
    assert page.table.selectedItems()
    assert len(page.table.item(0, 3).text()) <= 24
    assert page.table.item(0, 3).toolTip() == long_id
    assert long_id in page.provenance.text()
    session.clear_focus()
    assert not page.table.selectedItems()
    assert not page.neutral.isHidden() and page.details.isHidden()
