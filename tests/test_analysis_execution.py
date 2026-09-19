from dataclasses import replace, FrozenInstanceError
from pathlib import Path
import json
import hashlib
from datetime import date, datetime

import polars as pl
import pytest
from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.planning.models import AnalysisPlan,AnalysisStep
from cyber_analyst.execution import AnalysisExecutionService,AnalysisExecutionError


def step(op, columns=(), groups=(), time=None, limit=None, id='s'):
    return AnalysisStep(id,op,op,'planned',tuple(columns),tuple(groups),time,limit)


def execute(dataset,*steps):
    return AnalysisExecutionService().execute(dataset=dataset,plan=AnalysisPlan(dataset.name,'test',steps))


@pytest.fixture
def dataset(tmp_path):
    path=tmp_path/'test.csv'
    path.write_text('day,kind,n\n2026-01-02,a,1\n2026-01-01,b,3\n2026-01-01,a,5\n,,\n')
    return load_csv(path)


def test_scope_null_unique_numeric_and_source(dataset):
    before=dataset.path.read_bytes()
    # Preview is intentionally wrong: execution must use lazy data.
    changed=replace(dataset,preview=pl.DataFrame({'wrong':[99]}))
    result=execute(changed,step('null_analysis',['kind'],id='a'),step('unique_count',['kind'],id='b'),step('numeric_summary',['n'],id='c'))
    assert result.results[0].rows==(('kind',1,25.0),)
    assert result.results[1].rows==(('kind',3),)
    assert result.results[2].rows==(('n',3,1,1,5,3.0,3.0,2.0),)
    assert dataset.path.read_bytes()==before
    json.dumps(result.results[2].rows,allow_nan=False)
    with pytest.raises(FrozenInstanceError): result.dataset_name='x'


@pytest.mark.parametrize('op',['column_distribution','top_values'])
def test_frequency_limit_null_ties(dataset,op):
    assert execute(dataset,step(op,['kind'])).results[0].rows==(('a',2),('b',1),(None,1))
    assert execute(dataset,step(op,['kind'],limit=1)).results[0].rows==(('a',2),)


def test_group_and_cross_tab(dataset):
    assert execute(dataset,step('group_count',groups=['kind'])).results[0].rows==(('a',2),('b',1),(None,1))
    assert execute(dataset,step('cross_tab',['kind','n'],limit=3)).results[0].rows==(('a',1,1),('a',5,1),('b',3,1))


def test_string_daily_grouped(dataset):
    result=execute(dataset,step('time_series_count',groups=['kind'],time='day')).results[0]
    assert result.rows==(('2026-01-01','a',1),('2026-01-01','b',1),('2026-01-02','a',1),(None,None,1))


@pytest.mark.parametrize('values',[[date(2026,1,1),date(2026,1,1),None],
                                  [datetime(2026,1,1,2),datetime(2026,1,1,23),None],
                                  ['2026-01-01T02:00:00','2026-01-01T23:00:00',None]])
def test_date_datetime_and_iso_strings(tmp_path,values):
    frame=pl.DataFrame({'t':values})
    data=Dataset(tmp_path/'memory',3,frame.schema,frame.head(0),frame.lazy())
    assert execute(data,step('time_series_count',time='t')).results[0].rows==(('2026-01-01',2),(None,1))


@pytest.mark.parametrize('values',[['not a date'],['2026-01-01','wrong'],[None,None],['01/02/2026']])
def test_invalid_temporal_strings(tmp_path,values):
    frame=pl.DataFrame({'t':pl.Series(values,dtype=pl.String)})
    data=Dataset(tmp_path/'memory',len(values),frame.schema,frame,frame.lazy())
    with pytest.raises(AnalysisExecutionError) as error: execute(data,step('time_series_count',time='t'))
    assert error.value.step_id=='s'
    assert error.value.operation=='time_series_count'
    assert error.value.__cause__ is not None


@pytest.mark.parametrize('bad',[step('numeric_summary',['kind']),step('cross_tab',['kind']),step('unknown'),
                                step('top_values',['missing']),step('top_values',['kind'],limit=101),
                                step('time_series_count',time='n'),step('unique_count',['kind'],limit=2),
                                step('time_series_count',groups=['day'],time='day')])
def test_contract_rejection(dataset,bad):
    with pytest.raises(AnalysisExecutionError): execute(dataset,bad)


def test_mismatch(dataset):
    with pytest.raises(AnalysisExecutionError,match='Dataset mismatch'):
        AnalysisExecutionService().execute(dataset=dataset,plan=AnalysisPlan('wrong','x',()))


def test_engine_error_wrapped(dataset):
    # Lazy engine resolves a missing column only when its plan is inspected/collected.
    dataset.path.write_text('day,kind,n\n2026-01-01,a,notnumeric\n')
    with pytest.raises(AnalysisExecutionError) as error: execute(dataset,step('numeric_summary',['n']))
    assert error.value.step_id=='s'
    assert error.value.operation=='numeric_summary'
    assert isinstance(error.value.__cause__,pl.exceptions.PolarsError)


def test_empty_and_all_null(tmp_path):
    frame=pl.DataFrame({'n':pl.Series([],dtype=pl.Int64)})
    data=Dataset(tmp_path/'empty',0,frame.schema,frame,frame.lazy())
    assert execute(data,step('null_analysis',['n'])).results[0].rows==(('n',0,0.0),)
    assert execute(data,step('numeric_summary',['n'])).results[0].rows==(('n',0,0,None,None,None,None,None),)


def test_source_collision(tmp_path):
    frame=pl.DataFrame({'count':['b','a','a']})
    data=Dataset(tmp_path/'collision',3,frame.schema,frame,frame.lazy())
    assert execute(data,step('top_values',['count'])).results[0].rows==(('a',2),('b',1))


def test_full_data_and_default_bound(tmp_path):
    path=tmp_path/'large.csv'
    path.write_text('value\n'+'\n'.join(str(i) for i in range(150))+'\n')
    data=load_csv(path)
    assert data.preview.height < data.row_count
    assert execute(data,step('unique_count',['value'])).results[0].rows == (('value',150),)
    rows=execute(data,step('top_values',['value'])).results[0].rows
    assert len(rows)==100
    assert rows[0]==(0,1) and rows[-1]==(99,1)


def test_all_null_numeric(tmp_path):
    frame=pl.DataFrame({'n':pl.Series([None,None],dtype=pl.Int64)})
    data=Dataset(tmp_path/'nulls',2,frame.schema,frame,frame.lazy())
    assert execute(data,step('null_analysis',['n'])).results[0].rows==(('n',2,100.0),)
    assert execute(data,step('unique_count',['n'])).results[0].rows==(('n',1),)
    assert execute(data,step('numeric_summary',['n'])).results[0].rows==(('n',0,2,None,None,None,None,None),)
