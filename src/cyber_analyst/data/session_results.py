"""Últimos resultados concluídos da sessão; sem Qt ou cálculos analíticos."""

from dataclasses import dataclass

from cyber_analyst.analysis.models import DatasetProfile
from cyber_analyst.correlation.models import CorrelationResult
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.data.dataset_collection import DatasetCollection


@dataclass(frozen=True)
class CompletedAnalysis:
    dataset: Dataset
    profile: DatasetProfile


class SessionResults:
    def __init__(self) -> None:
        self.last_analysis: CompletedAnalysis | None = None
        self.last_correlation: CorrelationResult | None = None

    def record_analysis(self, dataset: Dataset, profile: DatasetProfile) -> None:
        self.last_analysis = CompletedAnalysis(dataset, profile)

    def record_correlation(self, result: CorrelationResult) -> None:
        self.last_correlation = result

    def invalidate(self, collection: DatasetCollection) -> None:
        """Remove resultados de objetos que não pertencem mais à sessão.

        A identidade também impede reaproveitar resultado após remover/recarregar
        um arquivo com o mesmo caminho.
        """
        def present(dataset: Dataset) -> bool:
            return collection.contains(dataset.path) and collection.get(dataset.path) is dataset

        if self.last_analysis is not None and not present(self.last_analysis.dataset):
            self.last_analysis = None
        if self.last_correlation is not None:
            if not all(present(dataset) for dataset in (
                self.last_correlation.dataset_a, self.last_correlation.dataset_b,
            )):
                self.last_correlation = None
