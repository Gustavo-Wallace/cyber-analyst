from dataclasses import replace
from test_investigation_ui import window
from test_investigation_context import synthetic
from PySide6.QtCore import Qt


def focus(s,value):s.navigate(next(r for r in s.search(value) if r.kind=='entity'))

def test_entity_details_navigation(window):
 p=window.entity_page;s=window.investigation_session
 assert 'No active' in p.message.text()
 window.set_investigation(synthetic())
 assert p.selector.rowCount()==3
 assert [p.selector.item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(3)]==list(s.view.entity_ids)
 p.selector.selectRow(0)
 assert s.state.focus.entity_id=='ana'
 assert 'username / ana' in window.context_inspector.details.toPlainText()
 assert p.occurrences.rowCount()==2 and p.neighbors.rowCount()==2
 assert [p.occurrences.item(0,c).text() for c in range(6)]==['directory','username','username','null','ana','1']
 p.neighbors.itemActivated.emit(p.neighbors.item(0,0))
 assert s.state.focus.entity_id=='email'
 assert p.neighbors.rowCount()==1
 assert p.neighbors.item(0,0).data(Qt.ItemDataRole.UserRole)=='ana'
 p.occurrences.itemActivated.emit(p.occurrences.item(0,0))
 assert s.state.focus.dataset_name=='directory' and p.panel.isHidden()
 focus(s,'ana@');assert not p.panel.isHidden()
 assert 'No directly linked' in p.findings.text() and 'No directly linked' in p.analyses.text()


def test_filters_lifecycle_isolated(window):
 p=window.entity_page;s=window.investigation_session
 window.set_investigation(synthetic());focus(s,'ana@')
 s.set_attention_levels(['high']);assert p.selector.rowCount()==3
 s.set_dataset_scope(['remote_access']);assert p.selector.rowCount()==2
 assert s.state.focus.entity_id=='email' and p.panel.isHidden()
 s.set_entity_types(['username']);assert p.selector.rowCount()==1
 s.clear_filters();assert p.selector.rowCount()==3 and not p.panel.isHidden()
 r=synthetic();e=replace(r.entities.entities[0],entity_id='isolated',canonical_value='isolated')
 window.set_investigation(replace(r,entities=replace(r.entities,entities=r.entities.entities+(e,))))
 assert p.selector.rowCount()==4 and not p.selector.selectedItems()
 focus(s,'isolated');assert p.neighbors.rowCount()==0 and 'No visible direct relations' in p.relation_summary.text()
 s.set_dataset_scope(['remote_access']);focus(s,'ana')
 assert p.occurrences.rowCount()==2
 p.occurrences.itemActivated.emit(p.occurrences.item(0,0))
 assert s.state.focus.entity_id=='ana' and 'hidden' in p.message.text()
 s.set_entity_types(['email']);assert p.selector.rowCount()==0
 s.clear();assert p.panel.isHidden() and 'No active' in p.message.text()
