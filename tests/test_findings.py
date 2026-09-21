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
from cyber_analyst.entities import EntityResult


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
    return InvestigationResult(tuple(DatasetInvestigationResult(None,None,None,None,r) for r in (auth,vulnerabilities)),CorrelationPlan(()),execution,entities=EntityResult(()))


def respond(selected):
    ai=Mock(); ai.generate_structured.return_value={'selected':selected}
    return FindingService(ai).generate(fixture_investigation())


@pytest.mark.parametrize('count',[0,1,3,5])
def test_selection_and_omission(count):
    catalog=build_evidence(fixture_investigation()); ids=[e.evidence_id for e in catalog][:count]
    result=respond(dict.fromkeys(ids,'medium'))
    assert len(result.findings)==count
    assert [f.evidence_ids for f in result.findings]==[(i,) for i in ids]
    assert len(result.evidence)==5
    assert all(f.attention_level=='medium' for f in result.findings)


@pytest.mark.parametrize('value',[None,1,True,'critical',{'group_id':'g1'},['high']])
def test_invalid_attention(value):
    identifier=build_evidence(fixture_investigation())[0].evidence_id
    with pytest.raises(FindingError): respond({identifier:value})


def test_unknown_evidence():
    with pytest.raises(FindingError): respond({'invented':'low'})


@pytest.mark.parametrize('field',['assignments','group_attention','confidence','title','interpretation','finding_id'])
def test_no_extra_fields(field):
    ai=Mock(); ai.generate_structured.return_value={'selected':{},field:{}}
    with pytest.raises(FindingError): FindingService(ai).generate(fixture_investigation())


@pytest.mark.parametrize('count',[8,9])
def test_maximum_selections(monkeypatch,count):
    from cyber_analyst.findings import service
    catalog=tuple(service.evidence_record('d','analysis',str(i),'op',{}) for i in range(9))
    monkeypatch.setattr(service,'build_evidence',lambda _:catalog)
    selected={e.evidence_id:'low' for e in catalog[:count]}
    if count==9:
        with pytest.raises(FindingError): respond(selected)
    else: assert len(respond(selected).findings)==8
    schema=service.response_schema(catalog)
    assert schema['properties']['selected']['maxProperties']==8
    assert schema['properties']['selected']['additionalProperties'] is False


def test_stable_ids_original_objects_no_recomputation(monkeypatch):
    import polars as pl
    import duckdb
    from hashlib import sha256
    from dataclasses import fields
    from cyber_analyst.findings.models import Finding
    from cyber_analyst.findings import service
    from cyber_analyst.data import csv_loader
    def forbidden(*a,**k): raise AssertionError('recomputation')
    monkeypatch.setattr(pl.LazyFrame,'collect',forbidden)
    monkeypatch.setattr(duckdb,'connect',forbidden)
    monkeypatch.setattr(csv_loader,'load_csv',forbidden)
    catalog=build_evidence(fixture_investigation())
    assert catalog==build_evidence(fixture_investigation())
    monkeypatch.setattr(service,'build_evidence',lambda _:catalog)
    ids=[catalog[3].evidence_id,catalog[0].evidence_id]
    first=respond(dict.fromkeys(ids,'medium'))
    second=respond(dict.fromkeys(reversed(ids),'low'))
    assert {f.finding_id for f in first.findings}=={f.finding_id for f in second.findings}
    assert first.findings[0].finding_id!=first.findings[1].finding_id
    identifier=first.findings[0].finding_id
    assert identifier=='finding_'+sha256(service._json([ids[0]]).encode()).hexdigest()
    assert first.evidence_for(identifier)==(catalog[3],)
    assert first.evidence_for(identifier)[0] is catalog[3]
    assert first.evidence is catalog
    assert json.loads(catalog[3].payload)['rows'][0][-1]==2.204087112616015
    assert {f.name for f in fields(Finding)}=={'finding_id','attention_level','evidence_ids'}
    with pytest.raises(KeyError): first.evidence_for('missing')
    with pytest.raises(FrozenInstanceError): catalog[0].payload='changed'


def test_empty_catalog_skips_ai():
    ai=Mock()
    assert FindingService(ai).generate(InvestigationResult((),CorrelationPlan(()),CorrelationExecutionResult(()),entities=EntityResult(()))).findings==()
    ai.generate_structured.assert_not_called()


@pytest.mark.parametrize('recover',[True,False])
def test_strict_duplicate_keys_and_structured_retry(recover):
    identifier=build_evidence(fixture_investigation())[0].evidence_id
    bad='{"selected":{"'+identifier+'":"low","'+identifier+'":"high"}}'
    provider=Mock(); provider.generate_structured.side_effect=[bad,json.dumps({'selected':{identifier:'medium'}})] if recover else [bad]*3
    svc=FindingService(AIService(provider))
    if recover:
        result=svc.generate(fixture_investigation())
        assert result.findings[0].attention_level=='medium'
    else:
        with pytest.raises(FindingError): svc.generate(fixture_investigation())
    assert provider.generate_structured.call_count==(2 if recover else 3)


def test_changed_values_change_id_and_bounds():
    from cyber_analyst.findings.service import evidence_record
    a=evidence_record('d','analysis','s','op',{'rows':[[1]]})
    b=evidence_record('d','analysis','s','op',{'rows':[[2]]})
    assert a.evidence_id!=b.evidence_id
    with pytest.raises(FindingError): evidence_record('d','analysis','s','op',{'rows':[['x'*16001]]})
