from dataclasses import replace, FrozenInstanceError
import pytest
from cyber_analyst.context import ContextService, InvestigationState, ViewService, SearchService, SearchError
from test_investigation_context import synthetic


def setup():
    r=synthetic()
    datasets=tuple(replace(d,analysis_execution=replace(d.analysis_execution,results=(
        replace(d.analysis_execution.results[0],operation='column_distribution',title='Distribution',columns=('username','count')),))) for d in r.datasets)
    findings=replace(r.findings,findings=(r.findings.findings[0],replace(r.findings.findings[1],attention_level='high')),
        evidence=tuple(replace(e,operation='column_distribution') for e in r.findings.evidence))
    c=ContextService().build(replace(r,datasets=datasets,findings=findings))
    return c,ViewService().build(c,InvestigationState())


@pytest.mark.parametrize('query,kind,target',[
    ('ana','entity','ana'),('USERNAME','entity','ana'),('directory','dataset','directory'),
    ('high','finding','f2'),('column_distribution','finding','f1'),
    ('remote_access','finding','f2'),('column_distribution','analysis','count'),
    ('remote_access','analysis','count'),('username','analysis','count'),
    ('Distribution','analysis','count'),('f1','finding','f1')])
def test_search_fields(query,kind,target):
    c,v=setup();results=SearchService().search(c,v,query)
    assert any(r.kind==kind and r.target_id==target for r in results)


def test_exact_before_substring_and_stable():
    c,v=setup();svc=SearchService()
    results=svc.search(c,v,'  ANA  ')
    assert [(r.kind,r.target_id) for r in results]==[('entity','ana'),('entity','email')]
    assert results==svc.search(c,v,'ana')
    assert len(svc.search(c,v,'ana',1))==1
    assert results.by_kind('entity')==results.results
    assert results.results[0].matched_text=='ana'
    with pytest.raises(FrozenInstanceError):results.results[0].label='bad'


def test_filtered_scope_and_no_mutation():
    c,v=setup();snapshot=setup()[0]
    scoped=ViewService().build(c,InvestigationState(dataset_scope=('remote_access',),entity_types=('username',),attention_levels=('high',)))
    svc=SearchService()
    assert [r.target_id for r in svc.search(c,scoped,'ana')]==['ana']
    assert not svc.search(c,scoped,'directory').results
    assert not svc.search(c,scoped,'email').results
    assert [r.target_id for r in svc.search(c,scoped,'high')]==['f2']
    assert all(r.dataset_name=='remote_access' for r in svc.search(c,scoped,'distribution'))
    assert c==snapshot and scoped.entity_ids==('ana',)


@pytest.mark.parametrize('query',['',' ','\t\n'])
def test_empty_query(query):
    c,v=setup()
    with pytest.raises(SearchError):SearchService().search(c,v,query)


@pytest.mark.parametrize('limit',[0,-1,True,1.5])
def test_bad_limit(limit):
    c,v=setup()
    with pytest.raises(SearchError):SearchService().search(c,v,'ana',limit)


@pytest.mark.parametrize('field,value',[
    ('entity_ids',('missing',)),('dataset_names',('missing',)),('finding_ids',('missing',)),
    ('relation_ids',('missing',)),('analysis_ids',(('directory','missing'),)),
    ('dataset_names',('remote_access',)),('entity_ids',('ana',))])
def test_stale_view(field,value):
    c,v=setup()
    with pytest.raises(SearchError):SearchService().search(c,replace(v,**{field:value}),'no-match')


def test_unicode_payload_exclusion_no_scan(monkeypatch):
    import polars as pl
    def forbidden(*a,**k):raise AssertionError('scan')
    monkeypatch.setattr(pl.LazyFrame,'collect',forbidden)
    c,v=setup()
    c=replace(c,entities={**c.entities,'ana':replace(c.entities['ana'],canonical_value='Stra\u00dfe')})
    assert SearchService().search(c,v,'STRASSE').results[0].target_id=='ana'
    # count exists as metadata, but numeric payload values are not searched.
    assert not SearchService().search(c,v,'{"count":1}').results


def test_analysis_namespace_and_kind_order():
    c,v=setup();r=SearchService().search(c,v,'remote_access')
    assert [x.kind for x in r]==['dataset','finding','analysis']
    analyses=SearchService().search(c,v,'count').by_kind('analysis')
    assert [x.dataset_name for x in analyses]==['directory','remote_access']
    assert len({(x.dataset_name,x.target_id) for x in analyses})==2
    assert c.analyses[('directory','count')].operation=='column_distribution'
    with pytest.raises(TypeError):c.analyses[('directory','count')]=None
