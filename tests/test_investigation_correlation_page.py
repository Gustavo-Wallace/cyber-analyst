from dataclasses import replace
import pytest
from test_investigation_ui import window
from test_investigation_context import synthetic
from cyber_analyst.correlation.models import CorrelationResult,CorrelationSummary
from cyber_analyst.correlation.execution import CorrelationProposalResult,CorrelationExecutionResult
from cyber_analyst.context import ContextService,StateService,InvestigationFocus,ViewService


def correlated():
 r=synthetic();a,b=[d.dataset for d in r.datasets]
 raw=CorrelationResult(a,b,'value','value',CorrelationSummary(1,1,1,1,1,0,0,1),('A.value','B.value'),(('ana','ana'),))
 c=CorrelationProposalResult('candidate_one',a.name,'value',b.name,'value',.9,'',raw)
 return replace(r,correlation_execution=CorrelationExecutionResult((c,)))


def test_context_identity_validation():
 r=correlated();c=ContextService().build(r);svc=StateService();s=svc.initial(c)
 s=svc.focus_correlation(s,c,'candidate_one')
 assert s.focus==InvestigationFocus(correlation_id='candidate_one')
 with pytest.raises(ValueError):InvestigationFocus(correlation_id='candidate_one',relation_id='r1')
 with pytest.raises(ValueError):svc.focus_correlation(s,c,'missing')
 with pytest.raises(ValueError):ViewService().build(c,replace(s,focus=InvestigationFocus(correlation_id='missing')))
 assert ViewService().build(c,s).correlation_ids==('candidate_one',)
 duplicate=replace(r,correlation_execution=CorrelationExecutionResult(r.correlation_execution.results*2))
 with pytest.raises(ValueError):ContextService().build(duplicate)


def test_correlation_ui(window,monkeypatch):
 import duckdb
 def forbidden(*a,**k):raise AssertionError('DuckDB execution')
 monkeypatch.setattr(duckdb,'connect',forbidden)
 p=window.correlation_explorer;s=window.investigation_session
 assert 'No active' in p.message.text()
 window.set_investigation(synthetic());assert p.selector.rowCount()==0
 window.set_investigation(correlated());assert p.selector.rowCount()==1
 p.selector.selectRow(0)
 assert s.state.focus.correlation_id=='candidate_one'
 assert 'Common keys: 1' in p.summary.text()
 assert 'Matched rows: 1' in window.context_inspector.details.toPlainText()
 assert p.overlap.counts==( ('Common',1),('Left only',0),('Right only',0))
 assert [p.preview.item(0,i).text() for i in range(2)]==['ana','ana']
 assert p.preview.horizontalHeaderItem(0).text()=='A.value'
 p.left.click();assert s.state.focus.dataset_name=='remote_access'
 p.selector.selectRow(0);p.right.click();assert s.state.focus.dataset_name=='directory'
 p.selector.selectRow(0);s.set_attention_levels(['high']);s.set_entity_types(['email'])
 assert p.selector.rowCount()==1
 s.set_dataset_scope(['directory']);assert p.selector.rowCount()==0
 assert s.state.focus.correlation_id=='candidate_one' and p.panel.isHidden()
 with pytest.raises(ValueError):s.focus_correlation('candidate_one')
 s.clear_filters();assert p.selector.rowCount()==1 and not p.panel.isHidden()
 window.set_investigation(synthetic());assert p.selector.rowCount()==0
 s.clear();assert 'No active' in p.message.text()
