from dataclasses import replace, FrozenInstanceError
import pytest
from cyber_analyst.context import ContextService, InvestigationState, InvestigationFocus, StateService, StateError, ViewService
from cyber_analyst.context.models import InvestigationContext
from test_investigation_context import synthetic


def context():
    r=synthetic()
    return ContextService().build(replace(r,findings=replace(r.findings,
        findings=(r.findings.findings[0],replace(r.findings.findings[1],attention_level='high')))))


def test_unfiltered():
    v=ViewService().build(context(),InvestigationState())
    assert v.dataset_names==('directory','remote_access')
    assert v.entity_ids==('ana','email','ip')
    assert v.relation_ids==('r1','r2')
    assert v.finding_ids==('f1','f2')
    assert v.analysis_ids==(('directory','count'),('remote_access','count'))


def smoke():
    c=context();s=StateService();states=[s.initial(c)]
    states.append(s.set_dataset_scope(states[-1],c,['remote_access']))
    states.append(s.set_entity_types(states[-1],c,['username','ip_address']))
    states.append(s.set_attention_levels(states[-1],['high']))
    return [ViewService().build(c,state) for state in states]


def test_scope_combined():
    views=smoke()
    for v in views[1:]:
        assert v.dataset_names==('remote_access',)
        assert v.entity_ids==('ana','ip')
        assert v.relation_ids==('r2',)
        assert v.finding_ids==('f2',)
        assert v.analysis_ids==(('remote_access','count'),)


@pytest.mark.parametrize('types,entities,relations',[
    (('username',),('ana',),()),
    (('username','email'),('ana','email'),('r1',)),
    (('ip_address','email'),('email','ip'),())])
def test_entity_types(types,entities,relations):
    v=ViewService().build(context(),InvestigationState(entity_types=types))
    assert v.entity_ids==entities and v.relation_ids==relations
    assert v.finding_ids==('f1','f2')


def test_attention_only():
    svc=ViewService();c=context();base=svc.build(c,InvestigationState())
    high=svc.build(c,InvestigationState(attention_levels=('high',)))
    assert high==replace(base,finding_ids=('f2',))
    assert svc.build(c,InvestigationState(attention_levels=('medium',))).finding_ids==()


@pytest.mark.parametrize('focus',[
    InvestigationFocus(entity_id='email'),InvestigationFocus(dataset_name='directory'),InvestigationFocus(finding_id='f1')])
def test_focus_does_not_override(focus):
    c=context();s=InvestigationState(focus=focus,dataset_scope=('remote_access',))
    v=ViewService().build(c,s)
    assert v==ViewService().build(c,replace(s,focus=InvestigationFocus()))
    assert s.focus is focus


@pytest.mark.parametrize('state',[
    InvestigationState(dataset_scope=('missing',)),InvestigationState(entity_types=('hostname',)),
    InvestigationState(focus=InvestigationFocus(entity_id='missing')),
    InvestigationState(focus=InvestigationFocus(dataset_name='missing')),
    InvestigationState(focus=InvestigationFocus(finding_id='missing'))])
def test_stale_rejected(state):
    with pytest.raises(StateError):ViewService().build(context(),state)


def test_empty_and_immutability_no_source_access(monkeypatch):
    import polars as pl
    from cyber_analyst.data import csv_loader
    def forbidden(*a,**k):raise AssertionError('source access')
    monkeypatch.setattr(pl.LazyFrame,'collect',forbidden)
    monkeypatch.setattr(csv_loader,'load_csv',forbidden)
    c=context();s=InvestigationState(dataset_scope=('remote_access',),entity_types=('email',),attention_levels=('low',))
    before=context();v=ViewService().build(c,s)
    assert not v.entity_ids and not v.relation_ids and not v.finding_ids
    assert c==before and s.entity_types==('email',)
    with pytest.raises(FrozenInstanceError):v.entity_ids=()
    empty=ViewService().build(InvestigationContext({},{},{},{},{}),InvestigationState())
    assert all(not getattr(empty,n) for n in ('dataset_names','entity_ids','relation_ids','finding_ids','analysis_ids'))


def test_deterministic_order():
    c=context();svc=ViewService()
    a=InvestigationState(dataset_scope=('remote_access','directory'),entity_types=('username','ip_address'))
    b=InvestigationState(dataset_scope=('directory','remote_access'),entity_types=('ip_address','username'))
    assert svc.build(c,a)==svc.build(c,b)==svc.build(c,a)


def test_relation_occurrence_without_visible_endpoint_excluded():
    c=context()
    # Dataset index may include a relation whose endpoint only occurs elsewhere.
    d=replace(c.datasets['remote_access'],relation_ids=('r1','r2'))
    c=replace(c,datasets={**c.datasets,'remote_access':d})
    assert ViewService().build(c,InvestigationState(dataset_scope=('remote_access',))).relation_ids==('r2',)
