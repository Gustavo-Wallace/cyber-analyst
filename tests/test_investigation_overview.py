from dataclasses import replace
from test_investigation_ui import window
from test_investigation_context import synthetic
import pytest
from cyber_analyst.ui.count_labels import count_label


def counts(page):return tuple(int(label.text()) for label in page.metrics.values())


@pytest.mark.parametrize('singular,plural', [
    ('dataset', 'datasets'), ('entity', 'entities'), ('relation', 'relations'),
    ('finding', 'findings'), ('analysis', 'analyses'), ('correlation', 'correlations'),
])
def test_count_label_grammar(singular, plural):
    assert count_label(1, singular, plural) == f'1 {singular}'
    assert count_label(2, singular, plural) == f'2 {plural}'
    assert count_label(0, singular, plural) == f'0 {plural}'
    assert count_label(1000, singular, plural, number_format=',') == f'1,000 {plural}'

def test_overview_lifecycle_filters(window):
    p=window.overview_page;s=window.investigation_session
    assert p.currentWidget() is window.dashboard_page
    window.set_investigation(synthetic())
    assert p.currentWidget() is p.dashboard
    assert counts(p)==(2,3,2,2,2,0)
    assert p.entity_chart.counts==( ('email',1),('ip_address',1),('username',1))
    assert dict(p.attention_chart.counts)=={'low':1,'medium':1}
    assert [p.coverage.item(0,c).text() for c in range(5)]==['directory','2','1','1','1']
    before=counts(p)
    s.navigate(next(r for r in s.search('ana') if r.target_id=='ana'))
    assert counts(p)==before
    s.set_dataset_scope(['remote_access'])
    assert counts(p)==(1,2,1,1,1,0) and p.coverage.rowCount()==1
    assert p.data_summary.text() == '1 source row | 1 source column across visible datasets'
    assert any('1 visible relation' in button.text() for button in p.entity_highlights.buttons)
    s.set_entity_types(['username'])
    assert counts(p)==(1,1,0,1,1,0) and p.entity_chart.counts==( ('username',1),)
    s.set_attention_levels(['high'])
    assert counts(p)==(1,1,0,0,1,0) and p.attention_chart.counts==()
    assert not p.attention_chart.empty.isHidden()
    s.clear_filters();assert counts(p)==before
    r=synthetic();r=replace(r,findings=replace(r.findings,findings=()))
    window.set_investigation(r);assert counts(p)==(2,3,2,0,2,0)
    s.clear();assert p.currentWidget() is window.dashboard_page


def test_provenance_and_empty_entities(window):
    r=synthetic()
    evidence=replace(r.findings.evidence[0],source_type='correlation',payload='{"right_dataset":"remote_access"}')
    r=replace(r,findings=replace(r.findings,evidence=(evidence,r.findings.evidence[1])))
    window.set_investigation(r);p=window.overview_page
    assert [p.coverage.item(i,3).text() for i in range(2)]==['1','1']
    window.investigation_session.set_dataset_scope(['remote_access'])
    window.investigation_session.set_entity_types(['email'])
    assert counts(p)==(1,0,0,1,1,0)
    assert not p.entity_chart.empty.isHidden()


def test_group_order_and_minimum(window):
    from PySide6.QtWidgets import QApplication
    r=synthetic();e=r.entities.entities[0]
    r=replace(r,entities=replace(r.entities,entities=r.entities.entities+(replace(e,entity_id='other',canonical_value='other'),)))
    window.set_investigation(r)
    assert window.overview_page.entity_chart.counts[0]==('username',2)
    window.resize(640,400);QApplication.processEvents()
    assert (window.width(),window.height())==(640,400)


def test_summary_highlights_and_navigation(window):
    from test_investigation_correlation_page import correlated
    r = correlated()
    window.set_investigation(r)
    p, s = window.overview_page, window.investigation_session
    assert counts(p) == (2, 3, 2, 2, 2, 1)
    assert p.data_summary.text().startswith('2 source rows | 2 source columns')
    assert p.finding_highlights.buttons[0].text().startswith('MEDIUM')
    assert p.entity_highlights.buttons[0].toolTip() == 'ana\nana'
    assert '1 common key | 1 matched row' in p.correlation_highlights.buttons[0].text()
    p.finding_highlights.buttons[0].click()
    assert s.state.focus.finding_id == 'f2'
    assert window.pages.currentWidget() is window.findings_page
    assert 'Attention: medium' in window.context_inspector.details.toPlainText()
    window.navigation.button(0).click()
    p.entity_highlights.buttons[0].click()
    assert s.state.focus.entity_id == 'ana'
    assert window.pages.currentWidget() is window.relations_tabs
    window.navigation.button(0).click()
    p.correlation_highlights.buttons[0].click()
    assert s.state.focus.correlation_id == 'candidate_one'
    assert window.investigation_tabs.currentWidget() is window.correlation_explorer
    window.navigation.button(0).click()
    p.coverage.itemClicked.emit(p.coverage.item(0, 0))
    assert s.state.focus.dataset_name == 'directory'
    assert 'directory' in window.context_inspector.details.toPlainText()


def test_empty_sections_replacement_and_rendering_does_not_mutate(window):
    from cyber_analyst.entities import EntityResult
    from cyber_analyst.relations import RelationResult
    from cyber_analyst.execution.models import AnalysisExecutionResult
    r = synthetic()
    window.set_investigation(r)
    s, p = window.investigation_session, window.overview_page
    original = (s.context, s.view, s.state)
    for _ in range(3):
        p.refresh()
        window.resize(640, 400)
        window.resize(1366, 768)
    assert all(a is b for a, b in zip(original, (s.context, s.view, s.state)))
    assert s.result is r
    assert all(s.context.findings[f.finding_id] is f for f in r.findings.findings)
    assert p.coverage.item(0, 0).toolTip() == 'directory'
    assert not p.coverage.showGrid()
    empty = replace(r, entities=EntityResult(()), relations=RelationResult(()),
        findings=replace(r.findings, findings=()),
        datasets=tuple(replace(d, analysis_execution=AnalysisExecutionResult(d.dataset.name, ())) for d in r.datasets))
    window.set_investigation(empty)
    assert counts(p) == (2, 0, 0, 0, 0, 0)
    assert not p.filtered_empty.isHidden()
    assert not p.attention_chart.empty.isHidden()
    assert not p.entity_chart.empty.isHidden()
    assert not p.correlation_highlights.empty.isHidden()
    assert not p.finding_highlights.buttons and not p.entity_highlights.buttons
    s.clear()
    assert window.dashboard_page.empty_panel.isVisible()
    assert not window.dashboard_page.body.isVisible()
