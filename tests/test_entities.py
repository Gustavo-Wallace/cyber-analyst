from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import polars as pl
import pytest

from cyber_analyst.data.dataset import Dataset
from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.semantic.models import DatasetUnderstanding, ColumnUnderstanding
from cyber_analyst.entities import EntityService


def source(name, values, kind, column='value'):
    frame=pl.DataFrame({column:values})
    dataset=Dataset(Path(name),frame.height,frame.schema,frame.head(1),frame.lazy())
    understanding=DatasetUnderstanding(dataset.path,dataset.name,'unknown','generic',0.8,'',
        (ColumnUnderstanding(column,kind,'reference',0.8,True),))
    return dataset,understanding


def extract(*sources):
    return EntityService().extract(datasets=[s[0] for s in sources],understandings=[s[1] for s in sources])


def smoke_sources():
    return [source('directory.csv',['ana','bruno'],'username','username'),
            source('remote_access.csv',['ANA','ana'],'username','actor_user'),
            source('asset.csv',['srv-01'],'hostname','hostname'),
            source('scan.csv',['SRV-01'],'hostname','affected_host')]


def test_shared_entities_smoke():
    result=extract(*smoke_sources())
    assert len(result.entities)==3
    ana=result.by_value('username','ana')
    assert [(o.dataset_name,o.row_count) for o in ana.occurrences]==[('directory.csv',1),('remote_access.csv',2)]
    host=result.by_value('hostname','srv-01')
    assert len(host.occurrences)==2
    assert all(o.value=='srv-01' and o.semantic_role=='reference' for o in host.occurrences)
    assert result.by_id(ana.entity_id) is ana
    assert result.by_id('missing') is None
    assert result.by_value('username','absent') is None
    with pytest.raises(FrozenInstanceError): ana.canonical_value='changed'


@pytest.mark.parametrize('kind,values,expected',[
    ('username',[' STRASSE ','Stra\u00dfe'],'strasse'),
    ('email',[' A@B.COM ','a@b.com'],'a@b.com'),
    ('hostname',[' SRV-01 ','srv-01'],'srv-01'),
    ('domain',[' EXAMPLE.COM ','example.com'],'example.com'),
    ('cve',[' cve-2026-1234 ','CVE-2026-1234'],'CVE-2026-1234'),
    ('hash',[' AAbb ','aabb'],'aabb'),
    ('ip_address',[' 2001:0db8:0:0:0:0:0:1 ','2001:db8::1'],'2001:db8::1'),
    ('ip_address',[' 192.168.1.1 ','192.168.1.1'],'192.168.1.1'),
])
def test_normalization(kind,values,expected):
    result=extract(source('d.csv',values+[None,'','  '],kind))
    assert len(result.entities)==1
    entity=result.entities[0]
    assert entity.canonical_value==expected
    assert entity.occurrences[0].row_count==2


@pytest.mark.parametrize('kind',['user_id','account_id','asset_id','device_id','event_id'])
def test_opaque_ids_case_sensitive(kind):
    result=extract(source('d.csv',[' Ab ','Ab','ab'],kind))
    assert [(e.canonical_value,e.occurrences[0].row_count) for e in result.entities]==[('Ab',2),('ab',1)]


@pytest.mark.parametrize('kind',['generic_identifier','status','severity','timestamp','numeric_measure','free_text','unknown'])
def test_unsupported_ignored(kind):
    assert extract(source('d.csv',['value'],kind)).entities==()


def test_types_distinct_stable_order():
    sources=[source('z.csv',['same','other'],'username'),source('a.csv',['same'],'hostname'),
             source('b.csv',['SAME'],'username')]
    first=extract(*sources); second=extract(*reversed(sources))
    assert first==second
    assert first.by_value('username','same').entity_id!=first.by_value('hostname','same').entity_id
    assert [(e.entity_type,e.canonical_value) for e in first.entities]==sorted((e.entity_type,e.canonical_value) for e in first.entities)
    assert extract(source('z.csv',['other','same'],'username')).by_value('username','same').entity_id==first.by_value('username','same').entity_id


def test_file_and_lazy_unchanged_full_data(tmp_path):
    path=tmp_path/'users.csv';path.write_text('user\nana\nbruno\nANA\n')
    before=path.read_bytes();d=load_csv(path)
    original=d.lazy_frame.collect();query=d.lazy_frame.explain()
    d=replace(d,preview=d.preview.head(1))
    u=DatasetUnderstanding(path,d.name,'unknown','generic',1,'',(ColumnUnderstanding('user','username',None,1,True),))
    result=extract((d,u))
    assert result.by_value('username','ana').occurrences[0].row_count==2
    assert result.by_value('username','bruno') is not None
    assert d.lazy_frame.collect().equals(original)
    assert d.lazy_frame.explain()==query and path.read_bytes()==before


def test_invalid_ips_ignored():
    result=extract(source('d.csv',['bad','192.168.1.1',' 192.168.1.1 ',
        '2001:0db8:0:0:0:0:0:1','2001:db8::1','999.1.1.1',None,''],'ip_address'))
    assert [(e.canonical_value,e.occurrences[0].row_count) for e in result.entities]==[
        ('192.168.1.1',2),('2001:db8::1',2)]
    assert extract(source('bad.csv',['bad','999.1.1.1'],'ip_address')).entities==()


def test_bad_context_and_empty():
    d,u=source('d.csv',['ana'],'username')
    with pytest.raises(ValueError): extract((d,replace(u,dataset_name='wrong')))
    with pytest.raises(ValueError): EntityService().extract(datasets=[d],understandings=[])
    assert extract().entities==()


def test_two_columns_same_dataset():
    frame=pl.DataFrame({'owner':['ANA','ana'],'actor':['ana','bruno']})
    d=Dataset(Path('d.csv'),2,frame.schema,frame.head(1),frame.lazy())
    u=DatasetUnderstanding(d.path,d.name,'unknown','generic',1,'',tuple(
        ColumnUnderstanding(n,'username',None,1,True) for n in frame.columns))
    result=extract((d,u))
    assert [(o.column_name,o.row_count) for o in result.by_value('username','ana').occurrences]==[('actor',1),('owner',2)]


def test_null_only_and_numeric_id():
    assert extract(source('null.csv',[None,None],'username')).entities==()
    result=extract(source('ids.csv',[42,42,None],'user_id'))
    assert result.entities[0].canonical_value=='42'
    assert result.entities[0].occurrences[0].row_count==2


@pytest.mark.parametrize('reverse_datasets,reverse_understandings',[(False,True),(True,False),(True,True)])
def test_independent_input_order(reverse_datasets,reverse_understandings):
    sources=smoke_sources()
    datasets=[d for d,u in sources]; understandings=[u for d,u in sources]
    result=EntityService().extract(datasets=iter(datasets[::-1] if reverse_datasets else datasets),
        understandings=iter(understandings[::-1] if reverse_understandings else understandings))
    assert result==extract(*sources)


@pytest.mark.parametrize('case,message',[
    ('missing','missing understandings'),('unexpected','unexpected understandings'),
    ('duplicate_dataset','duplicate dataset names'),('duplicate_understanding','duplicate understanding dataset names')])
def test_name_sets(case,message):
    d,u=source('d.csv',['ana'],'username'); extra,extra_u=source('extra.csv',['bruno'],'username')
    datasets=[d]; understandings=[u]
    if case=='missing': datasets.append(extra)
    elif case=='unexpected': understandings.append(extra_u)
    elif case=='duplicate_dataset': datasets.append(d)
    else: understandings.append(u)
    with pytest.raises(ValueError,match=message):
        EntityService().extract(datasets=datasets,understandings=understandings)
