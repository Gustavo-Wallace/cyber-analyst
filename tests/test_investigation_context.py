from dataclasses import replace, FrozenInstanceError
from pathlib import Path
import polars as pl
import pytest
from cyber_analyst.context import ContextService, ContextError
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.entities import Entity, EntityOccurrence, EntityResult
from cyber_analyst.relations import Relation, RelationOccurrence, RelationResult
from cyber_analyst.findings.models import Finding, FindingEvidence, FindingResult
from cyber_analyst.execution.models import AnalysisExecutionResult, AnalysisStepResult
from cyber_analyst.investigation.models import InvestigationResult, DatasetInvestigationResult
from cyber_analyst.correlation.planner import CorrelationPlan
from cyber_analyst.correlation.execution import CorrelationExecutionResult


def synthetic():
    def occurrence(dataset,column,kind,value):
        return EntityOccurrence(dataset,column,kind,None,value,1)
    entities=EntityResult((
        Entity('ana','username','ana',(occurrence('directory','username','username','ana'),occurrence('remote_access','actor','username','ana'))),
        Entity('email','email','ana@corp.local',(occurrence('directory','email','email','ana@corp.local'),)),
        Entity('ip','ip_address','10.10.1.15',(occurrence('remote_access','ip','ip_address','10.10.1.15'),))))
    relations=RelationResult((
        Relation('r1','co_occurrence','ana','email',(RelationOccurrence('directory','username','email',None,None,1),)),
        Relation('r2','co_occurrence','ana','ip',(RelationOccurrence('remote_access','actor','ip',None,None,1),))))
    datasets=[]
    for name in ('remote_access','directory'):
        frame=pl.DataFrame({'value':['ana']})
        d=Dataset(Path(name),1,frame.schema,frame,frame.lazy())
        ex=AnalysisExecutionResult(name,(AnalysisStepResult('count','unique_count','Count',('count',),((1,),)),))
        datasets.append(DatasetInvestigationResult(d,None,None,None,ex))
    evidence=(FindingEvidence('e1','directory','analysis','count','unique_count','{"count":1}'),
              FindingEvidence('e2','remote_access','analysis','count','unique_count','{"count":1}'))
    findings=FindingResult((Finding('f1','low',('e1',)),Finding('f2','medium',('e2',))),evidence)
    return InvestigationResult(tuple(datasets),CorrelationPlan(()),CorrelationExecutionResult(()),entities,relations,findings)


def test_navigation_and_provenance_no_recomputation(monkeypatch):
    import duckdb
    from cyber_analyst.data import csv_loader
    def forbidden(*a,**k):raise AssertionError('data access')
    monkeypatch.setattr(pl.LazyFrame,'collect',forbidden)
    monkeypatch.setattr(duckdb,'connect',forbidden)
    monkeypatch.setattr(csv_loader,'load_csv',forbidden)
    result=synthetic();ctx=ContextService().build(result)
    ana=ctx.entity('ana')
    assert ana.occurrences==result.entities.entities[0].occurrences
    assert ana.occurrences[0] is result.entities.entities[0].occurrences[0]
    assert ana.relation_ids==('r1','r2') and ana.neighbor_entity_ids==('email','ip')
    assert ana.dataset_names==('directory','remote_access')
    assert [e.entity_id for e in ctx.neighbors('email')]==['ana']
    assert ctx.relations_for('ana')==result.relations.relations
    directory=ctx.dataset('directory')
    assert directory.entity_ids==('ana','email')
    assert directory.relation_ids==('r1',)
    assert directory.finding_ids==('f1',)
    assert directory.analysis_result_ids==('count',)
    assert ctx.findings_for('directory')[0] is result.findings.findings[0]
    assert ctx.evidence_for('f1')[0] is result.findings.evidence[0]
    with pytest.raises(TypeError):ctx.entities['x']=ana
    with pytest.raises(FrozenInstanceError):ana.entity_id='changed'


def test_exact_evidence_dataset_not_neighbor_or_payload():
    r=synthetic()
    e=replace(r.findings.evidence[0],source_type='correlation',payload='{"right_dataset":"remote_access"}')
    ctx=ContextService().build(replace(r,findings=replace(r.findings,evidence=(e,r.findings.evidence[1]))))
    assert ctx.dataset('remote_access').finding_ids==('f2',)
    multi=replace(r.findings.findings[0],evidence_ids=('e1','e2'))
    ctx=ContextService().build(replace(r,findings=replace(r.findings,findings=(multi,))))
    assert ctx.dataset('remote_access').finding_ids==ctx.dataset('directory').finding_ids==('f1',)


def test_order_and_equality():
    r=synthetic();service=ContextService();ctx=service.build(r)
    assert ctx==service.build(r)
    reordered=replace(r,datasets=tuple(reversed(r.datasets)),
        entities=EntityResult(tuple(replace(e,occurrences=tuple(reversed(e.occurrences))) for e in reversed(r.entities.entities))),
        relations=RelationResult(tuple(reversed(r.relations.relations))),
        findings=FindingResult(tuple(reversed(r.findings.findings)),tuple(reversed(r.findings.evidence))))
    assert ctx==service.build(reordered)
    assert list(ctx.datasets)==['directory','remote_access']


@pytest.mark.parametrize('kind',['entity','relation','finding','evidence','dataset'])
def test_duplicates_rejected(kind):
    r=synthetic()
    if kind=='entity':r=replace(r,entities=EntityResult(r.entities.entities*2))
    elif kind=='relation':r=replace(r,relations=RelationResult(r.relations.relations*2))
    elif kind=='finding':r=replace(r,findings=replace(r.findings,findings=r.findings.findings*2))
    elif kind=='evidence':r=replace(r,findings=replace(r.findings,evidence=r.findings.evidence*2))
    else:r=replace(r,datasets=r.datasets*2)
    with pytest.raises(ContextError,match='Duplicate'):ContextService().build(r)


def test_unknown_endpoint():
    r=synthetic();r=replace(r,relations=RelationResult((replace(r.relations.relations[0],entity_b_id='missing'),)))
    with pytest.raises(ContextError,match='endpoint'):ContextService().build(r)


def test_unknown_evidence():
    r=synthetic();r=replace(r,findings=replace(r.findings,findings=(Finding('f','low',('missing',)),)))
    with pytest.raises(ContextError,match='evidence'):ContextService().build(r)


def test_empty_and_incomplete():
    r=synthetic();r=replace(r,entities=EntityResult(()),relations=RelationResult(()),findings=FindingResult(()))
    ctx=ContextService().build(r)
    assert not ctx.entities and not ctx.relations and not ctx.findings
    assert ctx.dataset('directory').entity_ids==()
    assert ctx.dataset('directory').analysis_result_ids==('count',)
    with pytest.raises(ContextError,match='Completed'):ContextService().build(replace(r,findings=None))


def test_relation_occurrence_contributes_entity_dataset_only():
    r=synthetic();relation=replace(r.relations.relations[0],occurrences=(RelationOccurrence('remote_access','actor','other',None,None,1),))
    ctx=ContextService().build(replace(r,relations=RelationResult((relation,))))
    assert ctx.entity('email').dataset_names==('directory','remote_access')
    assert 'email' not in ctx.dataset('remote_access').entity_ids
    assert ctx.dataset('remote_access').relation_ids==('r1',)
