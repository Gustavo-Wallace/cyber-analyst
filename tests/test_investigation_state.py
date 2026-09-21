from dataclasses import FrozenInstanceError, asdict
import pytest
from cyber_analyst.context import ContextService, InvestigationFocus, InvestigationState, StateService, StateError
from test_investigation_context import synthetic


def smoke():
    c=ContextService().build(synthetic());s=StateService()
    states=[s.initial(c)]
    states.append(s.focus_entity(states[-1],c,'ana'))
    states.append(s.set_dataset_scope(states[-1],c,['remote_access']))
    states.append(s.set_entity_types(states[-1],c,['username','ip_address']))
    states.append(s.set_attention_levels(states[-1],['high']))
    states.append(s.clear_focus(states[-1]))
    states.append(s.clear_filters(states[-1]))
    return states


def test_smoke_immutable():
    states=smoke()
    assert states[0]==states[-1]==InvestigationState()
    assert states[1].focus==states[4].focus==InvestigationFocus(entity_id='ana')
    assert states[2].dataset_scope==('remote_access',)
    assert states[3].entity_types==('ip_address','username')
    assert states[4].attention_levels==('high',)
    assert states[5].focus==InvestigationFocus()
    assert states[5].dataset_scope==states[4].dataset_scope
    assert len({id(s) for s in states})==7
    with pytest.raises(FrozenInstanceError):states[1].focus.entity_id='other'
    with pytest.raises(FrozenInstanceError):states[1].dataset_scope=()


def test_focus_replacement_and_filter_preservation():
    c=ContextService().build(synthetic());svc=StateService()
    s=svc.focus_entity(svc.initial(c),c,'ana')
    d=svc.focus_dataset(s,c,'directory')
    f=svc.focus_finding(d,c,'f2')
    assert d.focus==InvestigationFocus(dataset_name='directory')
    assert f.focus==InvestigationFocus(finding_id='f2')
    filtered=svc.set_dataset_scope(f,c,['directory'])
    assert filtered.focus==f.focus
    assert svc.clear_filters(filtered).focus==f.focus
    assert s.focus.entity_id=='ana'


@pytest.mark.parametrize('kwargs',[{'entity_id':'ana','dataset_name':'directory'},
    {'entity_id':'ana','finding_id':'f1'}, {'dataset_name':'directory','finding_id':'f1'},
    {'entity_id':'ana','dataset_name':'directory','finding_id':'f1'}])
def test_simultaneous_focus_rejected(kwargs):
    with pytest.raises(StateError):InvestigationFocus(**kwargs)


@pytest.mark.parametrize('method',['focus_entity','focus_dataset','focus_finding'])
def test_unknown_focus(method):
    c=ContextService().build(synthetic());svc=StateService()
    with pytest.raises(StateError):getattr(svc,method)(svc.initial(c),c,'missing')


@pytest.mark.parametrize('method,values',[
    ('set_dataset_scope',['missing']),('set_dataset_scope',['directory','directory']),
    ('set_entity_types',['hostname']),('set_entity_types',['username','username']),
    ('set_attention_levels',['critical']),('set_attention_levels',['high','high'])])
def test_invalid_filters(method,values):
    c=ContextService().build(synthetic());svc=StateService();s=svc.initial(c)
    with pytest.raises(StateError):
        if method=='set_attention_levels':getattr(svc,method)(s,values)
        else:getattr(svc,method)(s,c,values)
    assert s==InvestigationState()


def test_order_equal_and_detached():
    c=ContextService().build(synthetic());svc=StateService();s=svc.initial(c)
    names=['remote_access','directory']
    first=svc.set_dataset_scope(s,c,names)
    assert first==svc.set_dataset_scope(s,c,reversed(names))
    names.clear();assert first.dataset_scope==('directory','remote_access')
    assert svc.set_entity_types(s,c,['username','email'])==svc.set_entity_types(s,c,['email','username'])
    assert svc.set_attention_levels(s,['medium','high']).attention_levels==('high','medium')
    assert svc.set_dataset_scope(first,c,[])==s
    assert svc.clear_focus(s)==s and svc.clear_focus(s) is not s


def test_direct_construction_freezes_collections():
    values=['b','a'];s=InvestigationState(dataset_scope=values)
    values.append('c');assert s.dataset_scope==('a','b')
    with pytest.raises(StateError):InvestigationState(entity_types=['x','x'])
    with pytest.raises(StateError):InvestigationState(attention_levels=['invalid'])
    with pytest.raises(StateError):InvestigationState(dataset_scope='directory')
