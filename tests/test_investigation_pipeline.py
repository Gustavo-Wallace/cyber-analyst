from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest

from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.investigation import InvestigationPipeline, InvestigationPipelineError
from cyber_analyst.investigation import pipeline as module
from cyber_analyst.semantic.models import DatasetUnderstanding, ColumnUnderstanding
from cyber_analyst.planning.models import AnalysisPlan, AnalysisStep
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
                                    'correlation_planner','correlation_executor')}


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
    result=InvestigationPipeline(**svc).run(iter(datasets))
    assert events==[(stage,d.name) for d in datasets for stage in ('profiling','semantic','planning','execution')]
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
                                 'analysis_execution','correlation_planning','correlation_execution'])
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
    svc['correlation_planner'].plan.side_effect=callback('correlation_planning',CorrelationPlan(()))
    svc['correlation_executor'].execute.side_effect=callback('correlation_execution',object())
    with pytest.raises(InvestigationPipelineError) as error: InvestigationPipeline(**svc).run(datasets)
    assert error.value.stage==stage
    assert error.value.dataset is (None if stage.startswith('correlation') else datasets[0])
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
    return InvestigationPipeline(semantic_service=semantic,analysis_planner=planner,
        analysis_executor=AnalysisExecutionService(),correlation_planner=correlation,
        correlation_executor=CorrelationExecutionService())


def test_real_deterministic_integration(datasets):
    originals=[d.path.read_bytes() for d in datasets]
    result=synthetic_pipeline().run(datasets)
    assert [r.profile.row_count for r in result.datasets]==[3,2]
    assert [r.analysis_execution.results[0].rows for r in result.datasets]==[(('user',2),),(('user',2),)]
    summary=result.correlation_execution.results[0].correlation_result.summary
    assert summary.common==1 and summary.matched_rows==2
    assert result.correlation_execution.results[0].proposal_id=='shared'
    assert originals==[d.path.read_bytes() for d in datasets]
