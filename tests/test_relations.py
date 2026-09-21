from dataclasses import replace, FrozenInstanceError
from pathlib import Path
import polars as pl
import pytest
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.entities import EntityService, EntityResult
from cyber_analyst.relations import RelationService
from cyber_analyst.semantic.models import DatasetUnderstanding, ColumnUnderstanding


def source(name, data, types):
    frame=pl.DataFrame(data)
    d=Dataset(Path(name),frame.height,frame.schema,frame.head(1),frame.lazy())
    u=DatasetUnderstanding(d.path,d.name,'unknown','generic',1,'',tuple(
        ColumnUnderstanding(n,t,n+'_role',1,True) for n,t in zip(frame.columns,types)))
    return d,u


def smoke_sources():
    return [source('directory.csv',{'username':['ana'],'email':['ana@corp.local']},['username','email']),
            source('remote_access.csv',{'actor_user':['ANA','ana'],'source_address':['10.10.1.15']*2},['username','ip_address']),
            source('asset_scan.csv',{'affected_host':['SRV-01','srv-01'],'vulnerability':['CVE-2026-1234']*2},['hostname','cve'])]


def extract(sources):
    ds=[d for d,u in sources];us=[u for d,u in sources]
    entities=EntityService().extract(datasets=ds,understandings=us)
    return RelationService().extract(datasets=ds,understandings=us,entities=entities),entities


def test_smoke_relations():
    result,entities=extract(smoke_sources())
    assert len(result.relations)==3
    pairs={frozenset((entities.by_id(r.entity_a_id).entity_type,entities.by_id(r.entity_b_id).entity_type)):r for r in result.relations}
    assert pairs[frozenset(['username','email'])].occurrences[0].row_count==1
    assert pairs[frozenset(['username','ip_address'])].occurrences[0].row_count==2
    assert pairs[frozenset(['hostname','cve'])].occurrences[0].row_count==2
    for r in result.relations:
        assert r.entity_a_id<r.entity_b_id
        assert r.relation_type=='co_occurrence'
        assert result.by_id(r.relation_id) is r
        assert result.between(r.entity_b_id,r.entity_a_id) is r
        assert r in result.for_entity(r.entity_a_id)
        with pytest.raises(FrozenInstanceError): r.relation_type='other'
    assert result.by_id('missing') is None
    assert result.between('missing','other') is None
    assert result.for_entity('missing')==()


def test_merging_orientation_and_order():
    sources=[source('a.csv',{'user':['ana','ANA','ana'],'mail':['A@B','a@b','a@b']},['username','email']),
             source('b.csv',{'mail':['a@b'],'user':['ana']},['email','username'])]
    result,entities=extract(sources)
    assert len(result.relations)==1
    r=result.relations[0]
    assert [o.row_count for o in r.occurrences]==[3,1]
    for o in r.occurrences:
        assert o.entity_a_role==o.entity_a_column+'_role'
        assert o.entity_b_role==o.entity_b_column+'_role'
        types=dict(zip(sources[0][0].columns,['username','email']))
        assert types[o.entity_a_column]==entities.by_id(r.entity_a_id).entity_type
    reversed_result=RelationService().extract(datasets=[d for d,u in reversed(sources)],understandings=[u for d,u in sources],entities=entities)
    assert reversed_result==result
    assert extract(sources[:1])[0].relations[0].relation_id==r.relation_id


def test_self_invalid_unresolved_and_nonentity():
    s=source('d.csv',{'user':['ana','ana','',None,'ANA'],
        'other':['ANA','bruno','ana','ana','ana'],
        'ip':['bad','10.0.0.1','',None,'bad'], 'status':['active']*5},['username','username','ip_address','status'])
    result,entities=extract([s])
    assert len(result.relations)==3
    assert all(r.entity_a_id!=r.entity_b_id for r in result.relations)
    assert all(o.entity_a_column!='status' and o.entity_b_column!='status' for r in result.relations for o in r.occurrences)
    assert RelationService().extract(datasets=[s[0]],understandings=[s[1]],entities=EntityResult(())).relations==()


def test_separate_column_contexts():
    s=source('d.csv',{'a':['ana'],'b':['a@b'],'c':['A@B']},['username','email','email'])
    r,_=extract([s]);assert len(r.relations)==1
    assert len(r.relations[0].occurrences)==2
    assert all(o.row_count==1 for o in r.relations[0].occurrences)


@pytest.mark.parametrize('case',['missing','unexpected','duplicate_d','duplicate_u'])
def test_name_validation(case):
    d,u=smoke_sources()[0];ds=[d];us=[u]
    if case=='missing':us=[]
    if case=='unexpected':us.append(replace(u,dataset_name='other'))
    if case=='duplicate_d':ds.append(d)
    if case=='duplicate_u':us.append(u)
    with pytest.raises(ValueError,match='Relation extraction'):
        RelationService().extract(datasets=ds,understandings=us,entities=EntityResult(()))


def test_full_data_unchanged(tmp_path):
    from cyber_analyst.data.csv_loader import load_csv
    d,u=smoke_sources()[1];path=tmp_path/d.name
    d.lazy_frame.collect().write_csv(path);original=path.read_bytes();d=load_csv(path)
    d=replace(d,preview=d.preview.head(1));u=replace(u,dataset_path=path)
    frame=d.lazy_frame.collect();query=d.lazy_frame.explain()
    result,_=extract([(d,u)])
    assert result.relations[0].occurrences[0].row_count==2
    assert path.read_bytes()==original
    assert d.lazy_frame.collect().equals(frame) and d.lazy_frame.explain()==query


def test_no_cross_dataset_manufacture():
    sources=[source('a.csv',{'user':['ana']},['username']),source('b.csv',{'mail':['a@b']},['email'])]
    assert extract(sources)[0].relations==()
