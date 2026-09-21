from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest

from cyber_analyst.entities import EntityService, EntityResult
from cyber_analyst.relations import RelationService, RelationResult
from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.investigation import InvestigationPipeline, InvestigationPipelineError
from cyber_analyst.investigation import pipeline as module
from cyber_analyst.semantic.models import DatasetUnderstanding, ColumnUnderstanding
from cyber_analyst.planning.models import AnalysisPlan, AnalysisStep
from cyber_analyst.findings import FindingService
from cyber_analyst.findings.models import FindingResult
from cyber_analyst.execution import AnalysisExecutionService
from cyber_analyst.correlation.planner import CorrelationPlan, CorrelationProposal
from cyber_analyst.correlation.execution import CorrelationExecutionService


@pytest.fixture
def datasets(tmp_path):
    result=[]
    for name,content in [('b.csv','user\nana\nbia\nbia\n'),('a.csv','user\nbia\ncaio\n')]:
        path=tmp_path/name
        path.write_text(content,encoding='utf-8')
        result.append(load_csv(path))
    return result


def services():
    return {name:Mock() for name in ('semantic_service','analysis_planner','analysis_executor',
                                    'correlation_planner','correlation_executor','finding_service','entity_service','relation_service')}


@pytest.mark.parametrize('count',[1,2])
def test_order_identity_and_complete_flow(datasets,monkeypatch,count):
    datasets=datasets[:count]; svc=services(); events=[]
    profiles=[object() for _ in datasets]; meanings=[object() for _ in datasets]
    plans=[object() for _ in datasets]; executions=[object() for _ in datasets]
    def profile(d):
        events.append(('profiling',d.name)); return profiles[datasets.index(d)]
    def semantic(d,p):
        i=datasets.index(d); assert p is profiles[i]
        events.append(('semantic',d.name)); return meanings[i]
    def plan(**kw):
        i=datasets.index(kw['dataset'])
        assert kw['profile'] is profiles[i] and kw['understanding'] is meanings[i]
        events.append(('planning',datasets[i].name)); return plans[i]
    def execute(**kw):
        i=datasets.index(kw['dataset']); assert kw['plan'] is plans[i]
        events.append(('execution',datasets[i].name)); return executions[i]
    monkeypatch.setattr(module,'profile_dataset',profile)
    svc['semantic_service'].understand_dataset.side_effect=semantic
    svc['analysis_planner'].plan.side_effect=plan
    svc['analysis_executor'].execute.side_effect=execute
    entity_result=EntityResult(())
    def entities(**kwargs):
        assert kwargs==dict(datasets=tuple(datasets),understandings=tuple(meanings))
        svc['correlation_planner'].plan.assert_not_called()
        events.append(('entities',None))
        return entity_result
    svc['entity_service'].extract.side_effect=entities
    relation_result=RelationResult(())
    def relations(**kwargs):
        assert kwargs['entities'] is entity_result
        assert kwargs['datasets']==tuple(datasets)
        assert kwargs['understandings']==tuple(meanings)
        svc['correlation_planner'].plan.assert_not_called()
        events.append(('relations',None))
        return relation_result
    svc['relation_service'].extract.side_effect=relations
    def findings(investigation):
        assert investigation.relations is relation_result
        assert investigation.entities is entity_result
        assert [r.analysis_execution for r in investigation.datasets]==executions
        assert svc['analysis_executor'].execute.call_count==count
        assert svc['correlation_executor'].execute.call_count==(1 if count>1 else 0)
        events.append(('findings',None))
        return FindingResult(())
    svc['finding_service'].generate.side_effect=findings
    result=InvestigationPipeline(**svc).run(iter(datasets))
    svc['finding_service'].generate.assert_called_once()
    svc['entity_service'].extract.assert_called_once()
    assert result.entities is entity_result
    assert result.relations is relation_result
    svc['relation_service'].extract.assert_called_once()
    supplied=svc['finding_service'].generate.call_args.args[0]
    assert supplied.datasets is result.datasets
    assert supplied.correlation_execution is result.correlation_execution
    assert supplied.correlation_plan is result.correlation_plan
    assert result.findings==FindingResult(())
    assert supplied.findings is None
    assert events==[(stage,d.name) for d in datasets for stage in ('profiling','semantic','planning','execution')]+[('entities',None),('relations',None),('findings',None)]
    for i,item in enumerate(result.datasets):
        assert item.dataset is datasets[i]
        assert item.profile is profiles[i]
        assert item.understanding is meanings[i]
        assert item.analysis_plan is plans[i]
        assert item.analysis_execution is executions[i]
    if count==1:
        assert result.correlation_plan.proposals==()
        assert result.correlation_execution.results==()
        svc['correlation_planner'].plan.assert_not_called()
        svc['correlation_executor'].execute.assert_not_called()
    else:
        svc['correlation_planner'].plan.assert_called_once_with(datasets=tuple(datasets),understandings=tuple(meanings))
        svc['correlation_executor'].execute.assert_called_once_with(datasets=tuple(datasets),plan=result.correlation_plan)
        assert result.correlation_plan is svc['correlation_planner'].plan.return_value
        assert result.correlation_execution is svc['correlation_executor'].execute.return_value
    with pytest.raises(FrozenInstanceError): result.datasets=()


def test_empty_rejected():
    svc=services()
    with pytest.raises(InvestigationPipelineError) as error: InvestigationPipeline(**svc).run([])
    assert error.value.stage=='input_validation'
    assert isinstance(error.value.original_exception,ValueError)
    assert error.value.dataset is None
    assert all(not mock.mock_calls for mock in svc.values())


@pytest.mark.parametrize('stage',['profiling','semantic_understanding','analysis_planning',
                                 'analysis_execution','entities','relations','correlation_planning','correlation_execution','findings'])
def test_failure_context_and_fail_fast(datasets,monkeypatch,stage):
    svc=services(); calls=[]; failure=RuntimeError('original')
    def callback(name,value):
        def call(*args,**kwargs):
            calls.append(name)
            if name==stage: raise failure
            return value
        return call
    monkeypatch.setattr(module,'profile_dataset',callback('profiling',object()))
    svc['semantic_service'].understand_dataset.side_effect=callback('semantic_understanding',object())
    svc['analysis_planner'].plan.side_effect=callback('analysis_planning',object())
    svc['analysis_executor'].execute.side_effect=callback('analysis_execution',object())
    svc['entity_service'].extract.side_effect=callback('entities',EntityResult(()))
    svc['relation_service'].extract.side_effect=callback('relations',RelationResult(()))
    svc['correlation_planner'].plan.side_effect=callback('correlation_planning',CorrelationPlan(()))
    svc['correlation_executor'].execute.side_effect=callback('correlation_execution',object())
    svc['finding_service'].generate.side_effect=callback('findings',FindingResult(()))
    with pytest.raises(InvestigationPipelineError) as error: InvestigationPipeline(**svc).run(datasets)
    assert error.value.stage==stage
    assert error.value.dataset is (None if stage.startswith('correlation') or stage in ('findings','entities','relations') else datasets[0])
    assert error.value.original_exception is failure
    assert error.value.__cause__ is failure
    assert calls[-1]==stage


def synthetic_pipeline():
    semantic=Mock(); planner=Mock(); correlation=Mock()
    def understand(dataset,profile):
        return DatasetUnderstanding(dataset.path,dataset.name,'identity_data','directory',0.8,'',
            (ColumnUnderstanding('user','username',None,0.8,True),))
    semantic.understand_dataset.side_effect=understand
    planner.plan.side_effect=lambda **kw: AnalysisPlan(kw['dataset'].name,'Count users',(
        AnalysisStep('unique','unique_count','Distinct users','Quality check',('user',),(),None,None),))
    def correlate_plan(*,datasets,understandings):
        return CorrelationPlan((CorrelationProposal('shared',datasets[0].name,'user',datasets[1].name,'user','Possible shared username',0.8),))
    correlation.plan.side_effect=correlate_plan
    ai=Mock()
    def select(**kwargs):
        import json
        evidence=json.loads(kwargs['messages'][1]['content'])
        return {'selected':{e['evidence_id']:'low' for e in evidence}}
    ai.generate_structured.side_effect=select
    return InvestigationPipeline(semantic_service=semantic,analysis_planner=planner,
        analysis_executor=AnalysisExecutionService(),correlation_planner=correlation,
        correlation_executor=CorrelationExecutionService(),finding_service=FindingService(ai),entity_service=EntityService(),relation_service=RelationService())


@pytest.mark.parametrize('count',[1,2])
def test_real_deterministic_integration(datasets,count):
    datasets=datasets[:count]
    originals=[d.path.read_bytes() for d in datasets]
    result=synthetic_pipeline().run(datasets)
    assert [r.profile.row_count for r in result.datasets]==[3,2][:count]
    assert [r.analysis_execution.results[0].rows for r in result.datasets]==[(('user',2),),(('user',2),)][:count]
    if count==2:
        summary=result.correlation_execution.results[0].correlation_result.summary
        assert summary.common==1 and summary.matched_rows==2
        assert result.correlation_execution.results[0].proposal_id=='shared'
    assert isinstance(result.findings,FindingResult)
    assert len(result.findings.findings)==(1 if count==1 else 3)
    assert result.relations==RelationResult(())
    assert isinstance(result.entities,EntityResult)
    assert result.entities.by_value("username","bia") is not None
    assert len(result.entities.by_value("username","bia").occurrences)==count
    evidence=tuple(e for f in result.findings.findings for e in result.findings.evidence_for(f.finding_id))
    assert [e.source_type for e in evidence]==(['analysis'] if count==1 else ['analysis','analysis','correlation'])
    assert originals==[d.path.read_bytes() for d in datasets]


def entity_smoke(tmp_path):
    from test_entities import smoke_sources
    from dataclasses import replace
    sources=[]
    for d,u in smoke_sources():
        path=tmp_path/d.name
        d.lazy_frame.collect().write_csv(path)
        sources.append((load_csv(path),replace(u,dataset_path=path)))
    datasets=[d for d,u in sources]; meanings={d.name:u for d,u in sources}
    svc=services()
    svc['semantic_service'].understand_dataset.side_effect=lambda d,p: meanings[d.name]
    svc['analysis_planner'].plan.side_effect=lambda **k: AnalysisPlan(k['dataset'].name,'Count identifiers',(
        AnalysisStep('unique','unique_count','Distinct','Count values',tuple(k['dataset'].columns),(),None,None),))
    svc['analysis_executor']=AnalysisExecutionService()
    svc['correlation_planner'].plan.return_value=CorrelationPlan((
        CorrelationProposal('users','directory.csv','username','remote_access.csv','actor_user','',0.8),
        CorrelationProposal('hosts','asset.csv','hostname','scan.csv','affected_host','',0.8)))
    svc['correlation_executor']=CorrelationExecutionService()
    ai=Mock()
    def select(**kw):
        import json
        return {'selected':{e['evidence_id']:'low' for e in json.loads(kw['messages'][1]['content'])}}
    ai.generate_structured.side_effect=select
    svc['finding_service']=FindingService(ai)
    svc['entity_service']=Mock(wraps=EntityService())
    svc['relation_service']=RelationService()
    pipeline=InvestigationPipeline(**svc)
    result=pipeline.run(datasets)
    calls=(svc['semantic_service'].understand_dataset.call_count,svc['analysis_planner'].plan.call_count,
           svc['correlation_planner'].plan.call_count,ai.generate_structured.call_count)
    svc['entity_service'].extract.assert_called_once()
    baseline_entities=Mock(); baseline_entities.extract.return_value=EntityResult(())
    pipeline.entity_service=baseline_entities
    baseline=pipeline.run(datasets)
    after=(svc['semantic_service'].understand_dataset.call_count,svc['analysis_planner'].plan.call_count,
           svc['correlation_planner'].plan.call_count,ai.generate_structured.call_count)
    assert tuple(a-b for a,b in zip(after,calls))==calls
    assert [r.analysis_execution for r in result.datasets]==[r.analysis_execution for r in baseline.datasets]
    assert [r.correlation_result.summary for r in result.correlation_execution.results]==[r.correlation_result.summary for r in baseline.correlation_execution.results]
    assert result.findings==baseline.findings
    return result,calls


def test_entity_smoke(tmp_path):
    result,calls=entity_smoke(tmp_path)
    assert len(result.entities.entities)==3
    assert len(result.entities.by_value('username','ana').occurrences)==2
    assert len(result.entities.by_value('hostname','srv-01').occurrences)==2
    assert calls==(4,4,1,1)


def test_relations_required():
    from cyber_analyst.investigation.models import InvestigationResult
    from cyber_analyst.correlation.execution import CorrelationExecutionResult
    with pytest.raises(TypeError,match='relations'):
        InvestigationResult((),CorrelationPlan(()),CorrelationExecutionResult(()),entities=EntityResult(()))


def relation_smoke(tmp_path):
    from test_relations import smoke_sources
    from dataclasses import replace
    sources=[]
    for d,u in smoke_sources():
        path=tmp_path/d.name
        d.lazy_frame.collect().write_csv(path)
        sources.append((load_csv(path),replace(u,dataset_path=path)))
    datasets=[d for d,u in sources]; meanings={d.name:u for d,u in sources}
    svc=services()
    svc['semantic_service'].understand_dataset.side_effect=lambda d,p:meanings[d.name]
    svc['analysis_planner'].plan.side_effect=lambda **k:AnalysisPlan(k['dataset'].name,'Counts',(
        AnalysisStep('unique','unique_count','Distinct','Counts',tuple(k['dataset'].columns),(),None,None),))
    svc['analysis_executor']=AnalysisExecutionService()
    svc['entity_service']=EntityService()
    svc['relation_service']=Mock(wraps=RelationService())
    svc['correlation_planner'].plan.return_value=CorrelationPlan((
        CorrelationProposal('users','directory.csv','username','remote_access.csv','actor_user','Equality',0.8),))
    svc['correlation_executor']=CorrelationExecutionService()
    ai=Mock()
    def select(**kw):
        import json
        return {'selected':{e['evidence_id']:'low' for e in json.loads(kw['messages'][1]['content'])}}
    ai.generate_structured.side_effect=select
    svc['finding_service']=FindingService(ai)
    pipeline=InvestigationPipeline(**svc)
    result=pipeline.run(datasets)
    svc['relation_service'].extract.assert_called_once()
    def counts():
        return (svc['semantic_service'].understand_dataset.call_count,svc['analysis_planner'].plan.call_count,
                svc['correlation_planner'].plan.call_count,ai.generate_structured.call_count)
    before=counts()
    empty=Mock();empty.extract.return_value=RelationResult(())
    pipeline.relation_service=empty
    baseline=pipeline.run(datasets)
    assert tuple(a-b for a,b in zip(counts(),before))==before
    assert result.entities==baseline.entities
    assert [d.analysis_execution for d in result.datasets]==[d.analysis_execution for d in baseline.datasets]
    assert [c.correlation_result.summary for c in result.correlation_execution.results]==[c.correlation_result.summary for c in baseline.correlation_execution.results]
    assert result.findings==baseline.findings
    return result,before


def test_relation_smoke(tmp_path):
    result,calls=relation_smoke(tmp_path)
    assert len(result.relations.relations)==3
    pairs={frozenset((result.entities.by_id(r.entity_a_id).entity_type,result.entities.by_id(r.entity_b_id).entity_type)) for r in result.relations.relations}
    assert pairs=={frozenset(('username','email')),frozenset(('username','ip_address')),frozenset(('hostname','cve'))}
    assert calls==(3,3,1,1)
