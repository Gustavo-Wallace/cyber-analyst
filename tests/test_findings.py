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


def finding(ids):
    return dict(attention_level='medium',confidence=0.8,evidence_ids=ids)


def test_evidence_actual_values_ids_immutable_no_recomputation(monkeypatch):
    import polars as pl
    import duckdb
    from cyber_analyst.data import csv_loader
    def forbidden(*args,**kwargs): raise AssertionError('recomputation')
    monkeypatch.setattr(pl.LazyFrame,'collect',forbidden)
    monkeypatch.setattr(duckdb,'connect',forbidden)
    monkeypatch.setattr(csv_loader,'load_csv',forbidden)
    investigation=fixture_investigation(); evidence=build_evidence(investigation)
    assert len(evidence)==5 and evidence==build_evidence(investigation)
    assert {e.evidence_id for e in evidence}=={e.evidence_id for e in build_evidence(replace(investigation,datasets=tuple(reversed(investigation.datasets))))}
    assert json.loads(evidence[0].payload)['rows']==[['failed',4],['success',2]]
    assert json.loads(evidence[-1].payload)['metrics']['matched_rows']==5
    assert 'not evidence' not in str(evidence)
    assert 'confidence' not in json.loads(evidence[-1].payload)
    with pytest.raises(FrozenInstanceError): evidence[0].payload='changed'
    ai=Mock(); ai.generate_structured.return_value={'findings':[finding([evidence[0].evidence_id])]}
    assert FindingService(ai).generate(investigation).findings


@pytest.mark.parametrize('references',[1,2,4])
def test_valid_findings(references):
    investigation=fixture_investigation(); ids=[e.evidence_id for e in build_evidence(investigation)][:references]
    ai=Mock(); ai.generate_structured.return_value={'findings':[finding(ids)]}
    result=FindingService(ai).generate(investigation)
    assert result.findings[0].evidence_ids==tuple(ids)
    with pytest.raises(FrozenInstanceError): result.findings=()


def test_empty_findings_and_empty_catalog():
    ai=Mock(); ai.generate_structured.return_value={'findings':[]}
    assert FindingService(ai).generate(fixture_investigation()).findings==()
    ai.reset_mock()
    assert FindingService(ai).generate(InvestigationResult((),CorrelationPlan(()),CorrelationExecutionResult(()))).findings==()
    ai.generate_structured.assert_not_called()


@pytest.mark.parametrize('invalid',['unknown','duplicate_finding','duplicate_reference','attention','negative','over','nan','many_findings','many_references','no_reference'])
def test_invalid(invalid):
    investigation=fixture_investigation(); ids=[e.evidence_id for e in build_evidence(investigation)]
    item=finding(ids[:1]); items=[item]
    if invalid=='unknown': item['evidence_ids']=['invented']
    elif invalid=='duplicate_finding': items.append(dict(item))
    elif invalid=='duplicate_reference': item['evidence_ids']=[ids[0],ids[0]]
    elif invalid=='attention': item['attention_level']='critical'
    elif invalid=='negative': item['confidence']=-0.1
    elif invalid=='over': item['confidence']=1.1
    elif invalid=='nan': item['confidence']=float('nan')
    elif invalid=='many_findings': items=[dict(item) for _ in range(9)]
    elif invalid=='many_references': item['evidence_ids']=ids
    else: item['evidence_ids']=[]
    ai=Mock(); ai.generate_structured.return_value={'findings':items}
    with pytest.raises(FindingError): FindingService(ai).generate(investigation)
    assert ai.generate_structured.call_count==(2 if invalid in ('unknown','duplicate_finding','duplicate_reference','nan') else 1)


def test_retry_success_complete_replacement():
    investigation=fixture_investigation(); evidence=build_evidence(investigation)
    ai=Mock(); ai.generate_structured.side_effect=[{'findings':[finding(['invented'])]},
        {'findings':[finding([evidence[0].evidence_id])]}]
    assert FindingService(ai).generate(investigation).findings[0].evidence_ids==(evidence[0].evidence_id,)
    assert ai.generate_structured.call_count==2
    assert 'Existing evidence' not in ai.generate_structured.call_args.kwargs['messages'][-1]['content']


def test_changed_values_change_id_and_bounds():
    from cyber_analyst.findings.service import evidence_record
    a=evidence_record('d','analysis','s','op',{'rows':[[1]]})
    b=evidence_record('d','analysis','s','op',{'rows':[[2]]})
    assert a.evidence_id!=b.evidence_id
    with pytest.raises(FindingError): evidence_record('d','analysis','s','op',{'rows':[['x'*16001]]})


def test_ai_service_offline():
    provider=Mock(); provider.generate_structured.return_value='{"findings": []}'
    assert FindingService(AIService(provider)).generate(fixture_investigation()).findings==()


@pytest.mark.parametrize('field', ['title', 'interpretation', 'summary', 'description', 'cause'])
def test_free_text_fields_rejected(field):
    investigation=fixture_investigation(); catalog=build_evidence(investigation)
    item={**finding([catalog[0].evidence_id]), field:'Unsupported factual claim'}
    ai=Mock(); ai.generate_structured.return_value={'findings':[item]}
    with pytest.raises(FindingError): FindingService(ai).generate(investigation)


def test_selection_schema_and_model_have_only_controlled_fields():
    from dataclasses import fields
    from cyber_analyst.findings.models import Finding
    from cyber_analyst.findings.service import response_schema
    expected={'finding_id','attention_level','confidence','evidence_ids'}
    schema=response_schema(); item=schema['properties']['findings']['items']
    assert set(item['properties']) == set(item['required']) == expected - {'finding_id'}
    assert {f.name for f in fields(Finding)} == expected
    assert item['additionalProperties'] is False
    assert schema['additionalProperties'] is False


def test_retry_preserves_original_evidence(monkeypatch):
    from cyber_analyst.findings import service
    investigation=fixture_investigation(); catalog=build_evidence(investigation)
    payloads=tuple(e.payload for e in catalog)
    monkeypatch.setattr(service,'build_evidence',lambda _:catalog)
    item=finding([catalog[3].evidence_id,catalog[0].evidence_id])
    ai=Mock(); ai.generate_structured.side_effect=[{'findings':[finding(['invented'])]},{'findings':[item]}]
    result=FindingService(ai).generate(investigation)
    assert result.evidence_for(result.findings[0].finding_id)[0] is catalog[3]
    assert result.evidence_for(result.findings[0].finding_id)[1] is catalog[0]
    assert tuple(e.payload for e in result.evidence)==payloads
    assert json.loads(result.evidence_for(result.findings[0].finding_id)[0].payload)['rows'][0][-1]==2.204087112616015
    with pytest.raises(KeyError): result.evidence_for('missing')
    assert ai.generate_structured.call_count==2


def test_invalid_selection_rejects_whole_result_after_retry():
    catalog=build_evidence(fixture_investigation())
    good=finding([catalog[0].evidence_id])
    bad={**good,'evidence_ids':['invented']}
    ai=Mock(); ai.generate_structured.return_value={'findings':[good,bad]}
    with pytest.raises(FindingError, match='Domain retry exhausted'):
        FindingService(ai).generate(fixture_investigation())
    assert ai.generate_structured.call_count==2


@pytest.mark.parametrize('identifier', ['f1', 'MFA implementation is vulnerable'])
def test_ai_finding_id_rejected(identifier):
    item={**finding([build_evidence(fixture_investigation())[0].evidence_id]),
          'finding_id':identifier}
    ai=Mock(); ai.generate_structured.return_value={'findings':[item]}
    with pytest.raises(FindingError): FindingService(ai).generate(fixture_investigation())


@pytest.mark.parametrize('recover', [False, True])
def test_global_evidence_exclusivity_and_retry(recover):
    investigation=fixture_investigation()
    ids=[e.evidence_id for e in build_evidence(investigation)]
    repeated={'findings':[finding(ids[:2]), finding(ids[1:3])]}
    replacement={'findings':[finding(ids[:3]), finding(ids[3:])]}
    ai=Mock(); ai.generate_structured.side_effect=[repeated, replacement if recover else repeated]
    if recover:
        result=FindingService(ai).generate(investigation)
        assert [f.evidence_ids for f in result.findings]==[tuple(ids[:3]),tuple(ids[3:])]
    else:
        with pytest.raises(FindingError, match='evidence reused across findings'):
            FindingService(ai).generate(investigation)
    assert ai.generate_structured.call_count==2
    assert 'evidence reused across findings' in ai.generate_structured.call_args.kwargs['messages'][-1]['content']


def test_stable_finding_ids_depend_only_on_evidence_set():
    investigation=fixture_investigation()
    ids=[e.evidence_id for e in build_evidence(investigation)]
    ai=Mock(); ai.generate_structured.side_effect=[
        {'findings':[finding(ids[:2])]},
        {'findings':[{**finding(list(reversed(ids[:2]))),'confidence':0.2,'attention_level':'low'}]},
        {'findings':[finding(ids[1:3])]}]
    service=FindingService(ai)
    first, reordered, different=[service.generate(investigation).findings[0] for _ in range(3)]
    assert first.finding_id==reordered.finding_id
    assert first.finding_id!=different.finding_id
    assert first.finding_id.startswith('finding_')
    assert first.evidence_ids==tuple(ids[:2])
    assert reordered.evidence_ids==tuple(reversed(ids[:2]))
