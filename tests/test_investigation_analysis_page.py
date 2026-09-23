from dataclasses import replace
import pytest
from test_investigation_ui import window
from test_investigation_context import synthetic
from cyber_analyst.execution.models import AnalysisStepResult


def fixture(operation='column_distribution',columns=('value','count'),rows=(('ana',2),('bruno',1))):
    r=synthetic()
    return replace(r,datasets=tuple(replace(d,analysis_execution=replace(d.analysis_execution,results=(AnalysisStepResult('same',operation,'Result',columns,rows),))) for d in r.datasets))


@pytest.mark.parametrize('op,columns,rows,kind',[
 ('column_distribution',('value','count'),(('ana',2),('bruno',1)),'bar'),
 ('group_count',('value','count'),(('ana',2),),'bar'),
 ('cross_tab',('a','b','count'),(('ana','yes',2),),'bar'),
 ('time_series_count',('day','count'),(('2026-01-01',2),('2026-01-02',3)),'line'),
 ('numeric_summary',('column','mean'),(('value',1.234567890123),),None),
 ('unknown',('value','count'),(('ana',2),),None),
 ('top_values',('value','count'),(('ana',None),),None),
 ('column_distribution',('value','count'),(),None)])
def test_result_rendering(window,op,columns,rows,kind):
    p=window.analysis_explorer
    assert p.currentWidget() is window.investigate_page
    window.set_investigation(fixture(op,columns,rows))
    p.selector.selectRow(0)
    assert p.chart_kind==kind
    assert p.result_table.rowCount()==len(rows)
    for i,row in enumerate(rows):
        for j,value in enumerate(row):
            from cyber_analyst.ui.investigation_analysis_page import text
            assert p.result_table.item(i,j).text()==text(value)
    assert window.investigation_session.state.focus.analysis.dataset_name=='directory'
    assert op in window.context_inspector.details.toPlainText()


def test_filters_lifecycle(window):
    window.set_investigation(fixture());p=window.analysis_explorer;s=window.investigation_session
    assert p.selector.rowCount()==2
    p.selector.selectRow(0);focus=s.state.focus
    s.set_dataset_scope(['remote_access'])
    assert p.selector.rowCount()==1 and s.state.focus==focus
    assert 'hidden' in p.heading.text() and p.result_table.isHidden()
    s.set_entity_types(['email']);s.set_attention_levels(['high'])
    assert p.selector.rowCount()==1
    s.clear_filters();assert p.selector.rowCount()==2 and not p.result_table.isHidden()
    window.set_investigation(fixture('unique_count'))
    assert not p.selector.selectedItems()
    r=fixture();r=replace(r,datasets=tuple(replace(d,analysis_execution=replace(d.analysis_execution,results=())) for d in r.datasets))
    window.set_investigation(r);assert 'No analyses' in p.message.text()
    s.clear();assert p.currentWidget() is window.investigate_page


@pytest.mark.parametrize('operation,columns,rows,expected',[
    ('column_distribution',('value','count'),(('ana',2),('bruno',1)),['ana','bruno']),
    ('group_count',('user','status','count'),(('ana','active',2),('bruno','inactive',1)),
     ['ana | active','bruno | inactive']),
])
def test_readable_category_labels_preserve_results(window,operation,columns,rows,expected):
    from PySide6.QtCore import Qt
    from cyber_analyst.ui.investigation_analysis_page import text
    result=fixture(operation,columns,rows)
    window.set_investigation(result)
    page=window.analysis_explorer
    page.selector.selectRow(0)
    assert page.chart_kind=='bar'
    axis=page.chart_view.chart().axes(Qt.Orientation.Horizontal)[0]
    assert axis.categories()==expected
    assert page.chart_view.chart().series()[0].barSets()[0].count()==len(rows)
    for i,row in enumerate(rows):
        assert page.chart_view.chart().series()[0].barSets()[0].at(i)==row[-1]
        for j,value in enumerate(row):
            assert page.result_table.item(i,j).text()==text(value)
    assert result.datasets[0].analysis_execution.results[0].rows==rows
