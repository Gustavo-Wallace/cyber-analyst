"""Existing analytical results grouped without copying their data."""
from dataclasses import dataclass

from cyber_analyst.data.dataset import Dataset
from cyber_analyst.analysis.models import DatasetProfile
from cyber_analyst.semantic.models import DatasetUnderstanding
from cyber_analyst.planning.models import AnalysisPlan
from cyber_analyst.execution.models import AnalysisExecutionResult
from cyber_analyst.correlation.planner import CorrelationPlan
from cyber_analyst.correlation.execution import CorrelationExecutionResult
from cyber_analyst.findings.models import FindingResult


class InvestigationPipelineError(Exception):
    def __init__(self, stage: str, dataset: Dataset | None, original_exception: Exception):
        self.stage = stage
        self.dataset = dataset
        self.original_exception = original_exception
        context = f" ({dataset.name})" if dataset is not None else ""
        super().__init__(f"Investigation failed at {stage}{context}: {original_exception}")


@dataclass(frozen=True)
class DatasetInvestigationResult:
    dataset: Dataset
    profile: DatasetProfile
    understanding: DatasetUnderstanding
    analysis_plan: AnalysisPlan
    analysis_execution: AnalysisExecutionResult


@dataclass(frozen=True)
class InvestigationResult:
    datasets: tuple[DatasetInvestigationResult, ...]
    correlation_plan: CorrelationPlan
    correlation_execution: CorrelationExecutionResult
    # None only before finding generation; successful pipeline results always include it.
    findings: FindingResult | None = None
