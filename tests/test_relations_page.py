import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import pytest
from PySide6.QtCore import Qt
from test_investigation_ui import window
from test_investigation_context import synthetic
from cyber_analyst.context import ContextService, StateService, ViewService, InvestigationFocus


def test_relation_focus_validation():
    context = ContextService().build(synthetic())
    service = StateService()
    initial = service.initial(context)
    state = service.focus_relation(service.focus_entity(initial, context, 'ana'), context, 'r1')
    assert state.focus == InvestigationFocus(relation_id='r1')
    assert initial.focus == InvestigationFocus()
    assert service.clear_focus(state).focus == InvestigationFocus()
    for field, value in [('entity_id','ana'),('dataset_name','directory'),('finding_id','f1')]:
        with pytest.raises(ValueError): InvestigationFocus(relation_id='r1', **{field:value})
    with pytest.raises(ValueError): service.focus_relation(initial, context, 'missing')
    with pytest.raises(ValueError): ViewService().build(context, replace(state, focus=InvestigationFocus(relation_id='missing')))
    hidden = service.set_entity_types(state, context, ['username'])
    assert ViewService().build(context, hidden).relation_ids == ()
    assert hidden.focus == state.focus


def test_relations_lifecycle_provenance_and_endpoints(window):
    page = window.relations_page
    assert window.pages.widget(4) is page
    assert page.empty.text().startswith('No active investigation') and page.splitter.isHidden()
    window.set_investigation(synthetic())
    session = window.investigation_session
    assert page.table.rowCount() == 2
    assert [page.table.item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(2)] == list(session.view.relation_ids)
    assert page.table.item(0,0).text() == 'ana'
    page.table.selectRow(0)
    assert session.state.focus.relation_id == 'r1'
    assert 'Co-occurrence' in window.context_inspector.details.toPlainText()
    assert 'directory' in window.context_inspector.details.toPlainText()
    assert 'ana@corp.local' in page.endpoint_labels[1].text()
    assert [page.occurrences.item(0,c).text() for c in range(6)] == ['directory','username','-','email','-','1']
    page.endpoint_a.click()
    assert session.state.focus.entity_id == 'ana'
    assert 'username / ana' in window.context_inspector.details.toPlainText()
    page.table.selectRow(0)
    page.endpoint_b.click()
    assert session.state.focus.entity_id == 'email'
    window.set_investigation(synthetic())
    assert not page.table.selectedItems()
    assert page.occurrences.isHidden()
    session.clear()
    assert page.splitter.isHidden() and page.table.rowCount() == 0


def test_relation_filters_and_stale_navigation(window):
    window.set_investigation(synthetic())
    session = window.investigation_session
    page = window.relations_page
    page.table.selectRow(0)
    session.set_attention_levels(['high'])
    assert page.table.rowCount() == 2
    session.set_dataset_scope(['remote_access'])
    assert page.table.rowCount() == 1
    assert page.table.item(0,0).data(Qt.ItemDataRole.UserRole) == 'r2'
    assert session.state.focus.relation_id == 'r1'
    assert window.context_inspector.details.toolTip() == 'r1'
    assert not page.table.selectedItems()
    before = session.state
    for identifier in ('r1','missing'):
        with pytest.raises(ValueError): session.focus_relation(identifier)
        assert session.state is before
    session.set_entity_types(['username'])
    assert page.table.rowCount() == 0 and page.splitter.isHidden()
    assert page.empty.text().startswith('No relations match')
    session.clear_filters()
    assert page.table.rowCount() == 2 and page.table.selectedItems()
    assert session.state.focus.relation_id == 'r1'


def test_visual_metadata_and_row_selection(window):
    window.set_investigation(synthetic())
    page = window.relations_page
    assert page.endpoint_cards.isHidden()
    page.table.selectRow(0)
    assert len(page.table.selectedItems()) == 6
    assert page.table.item(0,2).text() == 'Co-occurrence'
    assert window.investigation_session.context.relations['r1'].relation_type == 'co_occurrence'
    assert page.details.toolTip() == 'r1'
    assert page.summary.text() == '2 visible relations | 3 visible entities'
    assert page.observed.text() == 'Observed in\n1 occurrence | directory'
    assert window.context_inspector.details.toPlainText() == 'Co-occurrence\nusername: ana\n<-> email: ana@corp.local\n\n1 occurrence | directory'
    assert 'ana@corp.local' in page.endpoint_labels[1].toolTip()
    assert 'email' in page.endpoint_labels[1].toolTip()
    assert page.occurrences.maximumHeight() < 120
    assert page.table.item(0,0).toolTip() == 'ana\nr1'
    window.investigation_session.clear_focus()
    assert page.endpoint_cards.isHidden() and page.occurrences.isHidden()
