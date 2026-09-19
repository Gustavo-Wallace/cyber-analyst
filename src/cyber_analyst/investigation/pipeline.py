"""Sequential composition only: no loading, inference rules or analytical logic."""
from typing import Iterable
from dataclasses import replace

from cyber_analyst.analysis.exploratory import profile_dataset
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.correlation.planner import CorrelationPlan
from cyber_analyst.correlation.execution import CorrelationExecutionResult
from cyber_analyst.investigation.models import (
    InvestigationPipelineError, DatasetInvestigationResult, InvestigationResult,
)


def _stage(stage, dataset, function, /, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        raise InvestigationPipelineError(stage, dataset, exc) from exc


class InvestigationPipeline:
    def __init__(self, *, semantic_service, analysis_planner, analysis_executor,
                 correlation_planner, correlation_executor, finding_service):
        self.semantic_service = semantic_service
        self.analysis_planner = analysis_planner
        self.analysis_executor = analysis_executor
        self.correlation_planner = correlation_planner
        self.correlation_executor = correlation_executor
        self.finding_service = finding_service

    def run(self, datasets: Iterable[Dataset]) -> InvestigationResult:
        try:
            datasets = tuple(datasets)
            if not datasets:
                raise ValueError('At least one dataset is required')
            if any(not isinstance(dataset, Dataset) for dataset in datasets):
                raise TypeError('Expected already-loaded Dataset objects')
        except Exception as exc:
            raise InvestigationPipelineError('input_validation', None, exc) from exc
        results = []
        for dataset in datasets:
            profile = _stage('profiling', dataset, profile_dataset, dataset)
            understanding = _stage('semantic_understanding', dataset,
                                   self.semantic_service.understand_dataset, dataset, profile)
            plan = _stage('analysis_planning', dataset, self.analysis_planner.plan,
                          dataset=dataset, profile=profile, understanding=understanding)
            execution = _stage('analysis_execution', dataset, self.analysis_executor.execute,
                               dataset=dataset, plan=plan)
            results.append(DatasetInvestigationResult(dataset, profile, understanding, plan, execution))
        if len(datasets) > 1:
            correlation_plan = _stage('correlation_planning', None, self.correlation_planner.plan,
                                      datasets=datasets, understandings=tuple(r.understanding for r in results))
            correlation_execution = _stage('correlation_execution', None, self.correlation_executor.execute,
                                           datasets=datasets, plan=correlation_plan)
        else:
            correlation_plan = CorrelationPlan(())
            correlation_execution = CorrelationExecutionResult(())
        investigation = InvestigationResult(tuple(results), correlation_plan, correlation_execution)
        findings = _stage('findings', None, self.finding_service.generate, investigation)
        return replace(investigation, findings=findings)
