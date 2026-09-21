from dataclasses import replace, FrozenInstanceError
import pytest
from cyber_analyst.context import (InvestigationState, InvestigationFocus, AnalysisRef, StateService,
    StateError, ViewService, SearchService, SearchResult, NavigationService, NavigationError)
from test_investigation_search import setup


def smoke():
    c,v=setup();s=InvestigationState();states=[s];nav=NavigationService()
    for query,kind in [('ana','entity'),('remote_access','dataset'),('high','finding'),('remote_access','analysis')]:
        result=next(r for r in SearchService().search(c,v,query) if r.kind==kind)
        s=nav.focus_search_result(s,c,v,result);states.append(s)
    filtered=StateService().set_dataset_scope(s,c,['directory'])
    hidden=ViewService().build(c,filtered)
    assert filtered.focus==s.focus and ('remote_access','count') not in hidden.analysis_ids
    with pytest.raises(NavigationError):nav.focus_search_result(filtered,c,hidden,result)
    return states,filtered,hidden


def test_smoke_and_immutability():
    states,filtered,hidden=smoke()
    assert states[1].focus==InvestigationFocus(entity_id='ana')
    assert states[2].focus==InvestigationFocus(dataset_name='remote_access')
    assert states[3].focus==InvestigationFocus(finding_id='f2')
    assert states[4].focus==InvestigationFocus(analysis=AnalysisRef('remote_access','count'))
    assert states[0]==InvestigationState()
    with pytest.raises(FrozenInstanceError):states[4].focus.analysis.analysis_id='other'
    assert StateService().clear_focus(states[4]).focus==InvestigationFocus()


def test_composite_identity_and_equal_transition():
    c,v=setup();s=InvestigationState();nav=NavigationService()
    results=SearchService().search(c,v,'count').by_kind('analysis')
    a,b=[nav.focus_search_result(s,c,v,r) for r in results]
    assert a.focus.analysis.analysis_id==b.focus.analysis.analysis_id=='count'
    assert a.focus.analysis.dataset_name!=b.focus.analysis.dataset_name
    assert a==nav.focus_search_result(s,c,v,results[0])
    assert StateService().set_attention_levels(a,['high']).focus==a.focus
    assert c==setup()[0] and v==setup()[1]


@pytest.mark.parametrize('kind,identifier,dataset',[
    ('analysis','count',None),('analysis','count','missing'),('analysis','missing','directory'),
    ('entity','missing',None),('finding','missing',None),('dataset','missing',None),
    ('dataset','directory','remote_access'),('entity','email','remote_access'),('finding','f1','remote_access')])
def test_bad_results(kind,identifier,dataset):
    c,v=setup()
    r=SearchResult(kind,identifier,'label',dataset,'text')
    with pytest.raises(NavigationError):NavigationService().focus_search_result(InvestigationState(),c,v,r)


@pytest.mark.parametrize('field', ['entity_id','dataset_name','finding_id'])
def test_analysis_focus_exclusive(field):
    with pytest.raises(StateError):InvestigationFocus(analysis=AnalysisRef('directory','count'),**{field:'x'})


@pytest.mark.parametrize('reference',[AnalysisRef('directory','missing'),AnalysisRef('missing','count')])
def test_stale_analysis_state(reference):
    c,v=setup()
    with pytest.raises(StateError):ViewService().build(c,InvestigationState(focus=InvestigationFocus(analysis=reference)))


def test_hidden_entity_result():
    c,v=setup();s=InvestigationState(dataset_scope=('remote_access',))
    r=next(r for r in SearchService().search(c,v,'ana') if r.target_id=='email')
    with pytest.raises(NavigationError):NavigationService().focus_search_result(s,c,ViewService().build(c,s),r)


def test_dataset_metadata_does_not_redefine_entity():
    c,v=setup();r=SearchResult('entity','ana','ana','remote_access','ana')
    s=NavigationService().focus_search_result(InvestigationState(),c,v,r)
    assert s.focus==InvestigationFocus(entity_id='ana')
