from dataclasses import replace, FrozenInstanceError
from unittest.mock import Mock
import json
import pytest

from cyber_analyst.findings import FindingService, FindingError, build_evidence
from cyber_analyst.execution.models import AnalysisExecutionResult, AnalysisStepResult
from cyber_analyst.correlation.models import CorrelationResult, CorrelationSummary
from cyber_analyst.correlation.planner import CorrelationPlan
from cyber_analyst.correlation.execution import CorrelationExecutionResult, CorrelationProposalResult
from cyber_analyst.investigation.models import InvestigationResult, DatasetInvestigationResult
from cyber_analyst.ai import AIService


def fixture_investigation():
    # Synthetic executed-result fixtures, not measurements of actual user files.
    auth=AnalysisExecutionResult('authentication.csv',(
        AnalysisStepResult('outcomes','column_distribution','',('result','count'),(('failed',4),('success',2))),
        AnalysisStepResult('mfa','group_count','',('result','mfa','count'),(('failed',False,2),('failed',True,2),('success',True,2)))))
    vulnerabilities=AnalysisExecutionResult('vulnerabilities.csv',(
        AnalysisStepResult('severity','column_distribution','',('severity','count'),(('critical',2),('medium',2),('high',1))),
        AnalysisStepResult('cvss','numeric_summary','',('column','count','null_count','minimum','maximum','mean','median','std'),
                           (('cvss',5,0,4.3,9.8,7.56,8.1,2.204087112616015),))))
    correlation=CorrelationResult(None,None,'hostname','affected_host',CorrelationSummary(4,5,4,4,4,0,0,5),(),())
    execution=CorrelationExecutionResult((CorrelationProposalResult('hosts','inventory.csv','hostname','vulnerabilities.csv','affected_host',0.9,'not evidence',correlation),))
    return InvestigationResult(tuple(DatasetInvestigationResult(None,None,None,None,r) for r in (auth,vulnerabilities)),CorrelationPlan(()),execution)


def assignments(ids, group='g1'):
    selected={i:group for i in ids}
    return {**selected, **{e.evidence_id:None for e in build_evidence(fixture_investigation()) if e.evidence_id not in selected}}


def run(response):
    response.setdefault('group_attention',{g:'medium' for g in response.get('assignments',{}).values() if isinstance(g,str)})
    ai=Mock(); ai.generate_structured.return_value=response
    return FindingService(ai).generate(fixture_investigation())


@pytest.mark.parametrize('count',[0,1,2,4])
def test_valid_selection_and_omission(count):
    catalog=build_evidence(fixture_investigation()); ids=[e.evidence_id for e in catalog][:count]
    result=run({'assignments':assignments(ids)})
    assert len(result.findings)==bool(count)
    assert len(result.evidence)==5
    if count:
        assert result.findings[0].evidence_ids==tuple(ids)
        with pytest.raises(FrozenInstanceError): result.findings[0].attention_level="low"


def test_multiple_groups():
    ids=[e.evidence_id for e in build_evidence(fixture_investigation())]
    result=run({'assignments':{**assignments(ids[:2]),**{k:v for k,v in assignments(ids[2:],'g2').items() if v is not None}}})
    assert [f.evidence_ids for f in result.findings]==[tuple(ids[:2]),tuple(ids[2:])]
    refs=[i for f in result.findings for i in f.evidence_ids]
    assert len(refs)==len(set(refs))==5


@pytest.mark.parametrize('value',['g9',True,1,['g1','g2'],{'group_id':'g1'}])
def test_invalid_assignment_schema(value):
    ids=[build_evidence(fixture_investigation())[0].evidence_id]
    data=assignments(ids); data[ids[0]]=value
    with pytest.raises(FindingError): run({'assignments':data,'group_attention':{}})


def test_no_confidence_or_free_text():
    from dataclasses import fields
    from cyber_analyst.findings.models import Finding
    assert {f.name for f in fields(Finding)}=={'finding_id','attention_level','evidence_ids'}
    for field in ('confidence','title','interpretation'):
        with pytest.raises(FindingError): run({'assignments':assignments([]),'group_attention':{},field:0.8})


def test_unknown_key_and_old_contract_rejected():
    for response in ({'assignments':assignments(['invented'])},{'findings':[]}):
        with pytest.raises(FindingError): run(response)


def test_schema_exclusive_keys_and_eight_groups():
    from cyber_analyst.findings.service import response_schema, evidence_record
    from jsonschema import validate, ValidationError
    catalog=tuple(evidence_record('d','analysis',str(i),'op',{}) for i in range(9))
    schema=response_schema(catalog); obj=schema['properties']['assignments']
    assert obj['additionalProperties'] is False
    assert set(obj['properties'])=={e.evidence_id for e in catalog}
    assert set(obj['required'])==set(obj['properties'])
    assert obj['properties'][catalog[0].evidence_id]['enum']==[None,*[f'g{i}' for i in range(1,9)]]
    data={e.evidence_id:f'g{i+1}' for i,e in enumerate(catalog)}
    with pytest.raises(ValidationError): validate({'assignments':data,'group_attention':{}},schema)


@pytest.mark.parametrize('violation',['missing','unused','size'])
@pytest.mark.parametrize('recover',[False,True])
def test_domain_retry_all_or_nothing(violation,recover):
    ids=[e.evidence_id for e in build_evidence(fixture_investigation())]
    bad=assignments(ids if violation=='size' else ids[:2])
    attention={'g1':'medium'}
    if violation=='missing': attention={}
    if violation=='unused': attention['g2']='low'
    bad_response={'assignments':bad,'group_attention':attention}
    good={'assignments':assignments(ids[-1:]),'group_attention':{'g1':'low'}}
    ai=Mock(); ai.generate_structured.side_effect=[bad_response,good if recover else bad_response]
    if recover:
        result=FindingService(ai).generate(fixture_investigation())
        assert result.findings[0].evidence_ids==(ids[-1],)
    else:
        with pytest.raises(FindingError,match='Domain retry exhausted'): FindingService(ai).generate(fixture_investigation())
    assert ai.generate_structured.call_count==2
    assert 'Violations:' in ai.generate_structured.call_args.kwargs['messages'][-1]['content']


def test_stable_ids_original_objects_and_no_recomputation(monkeypatch):
    import polars as pl
    import duckdb
    from hashlib import sha256
    from cyber_analyst.data import csv_loader
    from cyber_analyst.findings import service
    def forbidden(*a,**k): raise AssertionError('recomputation')
    monkeypatch.setattr(pl.LazyFrame,'collect',forbidden)
    monkeypatch.setattr(duckdb,'connect',forbidden)
    monkeypatch.setattr(csv_loader,'load_csv',forbidden)
    catalog=build_evidence(fixture_investigation())
    assert catalog==build_evidence(fixture_investigation())
    monkeypatch.setattr(service,'build_evidence',lambda _:catalog)
    ids=[catalog[3].evidence_id,catalog[0].evidence_id]
    first=run({'assignments':assignments(ids)})
    reordered=run({'assignments':assignments(list(reversed(ids)),'g8')})
    different=run({'assignments':assignments(ids[:1])})
    identifier=first.findings[0].finding_id
    assert identifier==reordered.findings[0].finding_id
    assert identifier!=different.findings[0].finding_id
    assert identifier=='finding_'+sha256(service._json(sorted(ids)).encode('utf-8')).hexdigest()
    assert first.evidence_for(identifier)[0] is catalog[3]
    assert first.evidence_for(identifier)[1] is catalog[0]
    assert first.evidence is catalog
    assert json.loads(catalog[3].payload)['rows'][0][-1]==2.204087112616015
    with pytest.raises(KeyError): first.evidence_for('missing')
    with pytest.raises(FrozenInstanceError): catalog[0].payload='changed'


def test_empty_catalog_skips_ai():
    ai=Mock()
    assert FindingService(ai).generate(InvestigationResult((),CorrelationPlan(()),CorrelationExecutionResult(()))).findings==()
    ai.generate_structured.assert_not_called()


def test_ai_service_offline():
    provider=Mock(); provider.generate_structured.return_value=json.dumps({'assignments':assignments([]),'group_attention':{}})
    assert FindingService(AIService(provider)).generate(fixture_investigation()).findings==()


def test_changed_values_change_id_and_bounds():
    from cyber_analyst.findings.service import evidence_record
    a=evidence_record('d','analysis','s','op',{'rows':[[1]]})
    b=evidence_record('d','analysis','s','op',{'rows':[[2]]})
    assert a.evidence_id!=b.evidence_id
    with pytest.raises(FindingError): evidence_record('d','analysis','s','op',{'rows':[['x'*16001]]})


@pytest.mark.parametrize('missing_all',[False,True])
def test_missing_required_evidence_rejected(missing_all):
    data=assignments([])
    if missing_all: data.clear()
    else: data.pop(next(iter(data)))
    with pytest.raises(FindingError): run({'assignments':data})


def test_empty_catalog_schema_accepts_empty_object():
    from jsonschema import validate
    from cyber_analyst.findings.service import response_schema
    validate({'assignments':{},'group_attention':{}},response_schema(()))
