from dataclasses import asdict, replace, FrozenInstanceError
import json
import pytest
from cyber_analyst.analyst.tool_models import ToolRequest, ToolValidationError, TOOL_REGISTRY
from cyber_analyst.analyst.tools import InvestigationToolService, LIMITS
from cyber_analyst.context import InvestigationState, ViewService
from cyber_analyst.context.search import SearchService
from test_analyst_context import context


def run(name,args,c=None,s=None):
    c=c or context();s=s or InvestigationState()
    return InvestigationToolService().execute(ToolRequest(name,args),c,s,ViewService().build(c,s))


def test_registry():
    assert set(TOOL_REGISTRY)=={'get_entity','get_relation','get_correlation','get_finding','get_analysis','get_dataset','search_investigation'}
    assert InvestigationToolService.definitions()==InvestigationToolService.definitions()
    json.dumps(InvestigationToolService.definitions())
    with pytest.raises(TypeError):TOOL_REGISTRY['get_entity'].argument_schema['type']='string'


@pytest.mark.parametrize('name,args',[
 ('shell',{}),('get_entity',{}),('get_entity',{'entity_id':'ana','extra':1}),
 ('get_entity',{'entity_id':2}),('get_entity',{'entity_id':' '}),
 ('get_analysis',{'analysis_id':'count'}),('search_investigation',{'query':''}),
 ('search_investigation',{'query':'a','limit':True}),('search_investigation',{'query':'a','limit':0}),
 ('search_investigation',{'query':'a','limit':21}),('get_entity',[]),
])
def test_arguments(name,args):
    with pytest.raises(ToolValidationError):ToolRequest(name,args)


def test_get_entity_relation_dataset():
    e=run('get_entity',{'entity_id':'ana'}).payload
    assert e['canonical_value']=='ana' and len(e['occurrences']['items'])==2
    assert e['neighbor_ids']['items']==('email','ip')
    r=run('get_relation',{'relation_id':'r1'}).payload
    assert r['entity_b']['canonical_value']=='ana@corp.local'
    assert r['occurrences']['items'][0]['entity_a_column']=='username'
    d=run('get_dataset',{'dataset_name':'directory'}).payload
    assert d['entity_ids']['items']==('ana','email')
    assert d['analysis_ids']['items']==('count',)


def test_committed_results():
    c=context()
    r=run('get_correlation',{'correlation_id':'c1'},c).payload
    assert dict(r['metrics'])==asdict(c.correlations['c1'].correlation_result.summary)
    assert r['preview']['rows']['total_count']==25
    a=run('get_analysis',{'dataset_name':'directory','analysis_id':'count'},c).payload
    assert a['rows']['items'][0]['items']==(1,)
    f=run('get_finding',{'finding_id':'f1'},c).payload
    assert f['evidence']['items'][0]['payload']==c.evidence['e1'].payload


@pytest.mark.parametrize('name,args',[
 ('get_entity',{'entity_id':'ip'}),('get_relation',{'relation_id':'r2'}),
 ('get_correlation',{'correlation_id':'c1'}),('get_finding',{'finding_id':'f2'}),
 ('get_analysis',{'dataset_name':'remote_access','analysis_id':'count'}),
 ('get_dataset',{'dataset_name':'remote_access'}),('get_entity',{'entity_id':'unknown'}),
])
def test_scope_denies_ids(name,args):
    result=run(name,args,s=InvestigationState(dataset_scope=('directory',)))
    assert result.status=='error' and result.error_code=='not_visible_or_unknown' and not result.payload


def test_nested_provenance_cannot_leak():
    c=context();s=InvestigationState(dataset_scope=('directory',))
    e=run('get_entity',{'entity_id':'ana'},c,s).payload
    assert e['neighbor_ids']['items']==('email',)
    assert {o['dataset_name'] for o in e['occurrences']['items']}=={'directory'}
    c=replace(c,findings={**c.findings,'f1':replace(c.findings['f1'],evidence_ids=('e1','e2'))})
    f=run('get_finding',{'finding_id':'f1'},c,s).payload
    assert f['evidence_ids']['items']==('e1',)
    assert not run('search_investigation',{'query':'remote_access'},c,s).payload['results']['items']


def test_type_attention_filters_and_stale_view():
    c=context();s=InvestigationState(entity_types=('username',),attention_levels=('high',))
    for name,args in [('get_entity',{'entity_id':'email'}),('get_relation',{'relation_id':'r1'}),('get_finding',{'finding_id':'f1'})]:
        assert run(name,args,c,s).status=='error'
    with pytest.raises(ToolValidationError):
        InvestigationToolService().execute(ToolRequest('get_entity',{'entity_id':'ana'}),c,s,ViewService().build(c,InvestigationState()))


def test_search_delegates_and_total_count(monkeypatch):
    c=context();s=InvestigationState();v=ViewService().build(c,s)
    expected=SearchService().search(c,v,'a',100)
    original=SearchService.search;calls=[]
    def spy(self,*args):calls.append(args);return original(self,*args)
    monkeypatch.setattr(SearchService,'search',spy)
    result=run('search_investigation',{'query':' A ','limit':1},c,s)
    assert len(calls)==1 and result.arguments['query']=='a'
    payload=result.to_dict()['payload']['results']
    assert payload['total_count']==len(expected) and payload['included_count']==1 and payload['truncated']
    assert payload['items']==[asdict(expected.results[0])]


def test_bounds_and_read_only():
    c=context();e=c.entities['ana'];a=c.analyses[('directory','count')]
    c=replace(c,entities={**c.entities,'ana':replace(e,occurrences=e.occurrences*30)},analyses={**c.analyses,('directory','count'):replace(a,rows=((1,),)*60)})
    result=run('get_entity',{'entity_id':'ana'},c)
    assert result.payload['occurrences']['total_count']==60 and result.payload['occurrences']['included_count']==20
    assert result.payload['occurrences']['truncated']
    rows=run('get_analysis',{'dataset_name':'directory','analysis_id':'count'},c).payload['rows']
    assert rows['total_count']==60 and rows['included_count']==50 and rows['truncated']
    with pytest.raises(TypeError):result.payload['occurrences']['items'][0]['value']='other'
    assert result==run('get_entity',{'entity_id':'ana'},c)
    assert result.to_dict()['payload_bytes']>0


def test_no_side_effects(monkeypatch):
    import builtins, socket, polars as pl, duckdb
    from cyber_analyst.ai.runtime import LlamaRuntime
    from cyber_analyst.ai.service import AIService
    from cyber_analyst.data import csv_loader
    c=context();s=InvestigationState();v=ViewService().build(c,s);before=repr((c,s,v))
    def forbidden(*a,**k):raise AssertionError('Forbidden I/O or computation')
    for obj,name in [(builtins,'open'),(socket,'socket'),(pl.LazyFrame,'collect'),(duckdb,'connect'),(LlamaRuntime,'start'),(AIService,'generate_structured'),(csv_loader,'load_csv')]:monkeypatch.setattr(obj,name,forbidden)
    requests=[('get_entity',{'entity_id':'ana'}),('get_relation',{'relation_id':'r1'}),('get_correlation',{'correlation_id':'c1'}),('get_finding',{'finding_id':'f1'}),('get_analysis',{'dataset_name':'directory','analysis_id':'count'}),('get_dataset',{'dataset_name':'directory'}),('search_investigation',{'query':'ana'})]
    for name,args in requests:
        req=ToolRequest(name,args)
        a=InvestigationToolService().execute(req,c,s,v)
        assert a.status=='success' and a==InvestigationToolService().execute(req,c,s,v)
    assert repr((c,s,v))==before


def test_correlation_evidence_cannot_bypass_endpoint_scope():
    c=context()
    c=replace(c,evidence={**c.evidence,'e1':replace(c.evidence['e1'],source_type='correlation',source_id='c1',payload='{"right_dataset":"remote_access"}')})
    s=InvestigationState(dataset_scope=('directory',))
    result=run('get_finding',{'finding_id':'f1'},c,s)
    assert result.payload['evidence']['items']==()
    assert result.payload['evidence_ids']['items']==()
    assert run('get_finding',{'finding_id':'f1'},c).payload['evidence_ids']['items']==('e1',)


def test_preview_evidence_text_and_columns_bounds():
    c=context();r=c.correlations['c1'];a=c.analyses[('directory','count')]
    c=replace(c,correlations={'c1':replace(r,correlation_result=replace(r.correlation_result,preview_rows=(('a','b'),)*55))},
              analyses={**c.analyses,('directory','count'):replace(a,title='x'*3000,columns=tuple(str(i) for i in range(45)),rows=(tuple(range(45)),))})
    preview=run('get_correlation',{'correlation_id':'c1'},c).payload['preview']['rows']
    assert preview['included_count']==50 and preview['total_count']==55 and preview['truncated']
    result=run('get_analysis',{'dataset_name':'directory','analysis_id':'count'},c).payload
    assert result['title']['truncated'] and result['title']['total_count']==3000
    assert result['columns']['truncated'] and result['rows']['items'][0]['truncated']
    evidence={f'e{i}':replace(c.evidence['e1'],evidence_id=f'e{i}') for i in range(25)}
    c=replace(c,evidence={**c.evidence,**evidence},findings={**c.findings,'f1':replace(c.findings['f1'],evidence_ids=tuple(evidence))})
    result=run('get_finding',{'finding_id':'f1'},c).payload
    assert result['evidence']['total_count']==25 and result['evidence']['included_count']==20 and result['evidence']['truncated']
    assert result['evidence_ids']['items']==tuple(e['evidence_id'] for e in result['evidence']['items'])


def test_request_copies_arguments_and_integer_is_strict():
    args={'query':' ANA '};r=ToolRequest('search_investigation',args);args['query']='other'
    assert r.arguments['query']=='ana'
    with pytest.raises(TypeError):r.arguments['query']='other'
    with pytest.raises(ToolValidationError):ToolRequest('search_investigation',{'query':'ana','limit':2.0})
