from dataclasses import replace
from test_investigation_ui import window
from test_investigation_context import synthetic


def counts(page):return tuple(int(label.text()) for label in page.metrics.values())

def test_overview_lifecycle_filters(window):
    p=window.overview_page;s=window.investigation_session
    assert p.currentWidget() is window.dashboard_page
    window.set_investigation(synthetic())
    assert p.currentWidget() is p.dashboard
    assert counts(p)==(2,3,2,2,2)
    assert p.entity_chart.counts==( ('email',1),('ip_address',1),('username',1))
    assert dict(p.attention_chart.counts)=={'low':1,'medium':1}
    assert [p.coverage.item(0,c).text() for c in range(5)]==['directory','2','1','1','1']
    before=counts(p)
    s.navigate(next(r for r in s.search('ana') if r.target_id=='ana'))
    assert counts(p)==before
    s.set_dataset_scope(['remote_access'])
    assert counts(p)==(1,2,1,1,1) and p.coverage.rowCount()==1
    s.set_entity_types(['username'])
    assert counts(p)==(1,1,0,1,1) and p.entity_chart.counts==( ('username',1),)
    s.set_attention_levels(['high'])
    assert counts(p)==(1,1,0,0,1) and p.attention_chart.counts==()
    assert not p.attention_chart.empty.isHidden()
    s.clear_filters();assert counts(p)==before
    r=synthetic();r=replace(r,findings=replace(r.findings,findings=()))
    window.set_investigation(r);assert counts(p)==(2,3,2,0,2)
    s.clear();assert p.currentWidget() is window.dashboard_page


def test_provenance_and_empty_entities(window):
    r=synthetic()
    evidence=replace(r.findings.evidence[0],source_type='correlation',payload='{"right_dataset":"remote_access"}')
    r=replace(r,findings=replace(r.findings,evidence=(evidence,r.findings.evidence[1])))
    window.set_investigation(r);p=window.overview_page
    assert [p.coverage.item(i,3).text() for i in range(2)]==['1','1']
    window.investigation_session.set_dataset_scope(['remote_access'])
    window.investigation_session.set_entity_types(['email'])
    assert counts(p)==(1,0,0,1,1)
    assert not p.entity_chart.empty.isHidden()


def test_group_order_and_minimum(window):
    from PySide6.QtWidgets import QApplication
    r=synthetic();e=r.entities.entities[0]
    r=replace(r,entities=replace(r.entities,entities=r.entities.entities+(replace(e,entity_id='other',canonical_value='other'),)))
    window.set_investigation(r)
    assert window.overview_page.entity_chart.counts[0]==('username',2)
    window.resize(640,400);QApplication.processEvents()
    assert (window.width(),window.height())==(640,400)
