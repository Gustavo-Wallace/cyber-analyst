"""Execução sequencial de propostas via motor existente, sem interpretação."""
from dataclasses import dataclass
from typing import Iterable

from cyber_analyst.data.dataset import Dataset
from cyber_analyst.correlation import engine
from cyber_analyst.correlation.models import CorrelationResult
from cyber_analyst.correlation.planner import CorrelationPlan, CorrelationProposal


class CorrelationExecutionError(Exception):
    def __init__(self, proposal: CorrelationProposal, message: str):
        self.proposal = proposal
        self.proposal_id = proposal.id
        super().__init__(
            f"Proposal {proposal.id!r}: {proposal.left_dataset}.{proposal.left_column} -> "
            f"{proposal.right_dataset}.{proposal.right_column}: {message}"
        )


@dataclass(frozen=True)
class CorrelationProposalResult:
    proposal_id: str
    left_dataset: str
    left_column: str
    right_dataset: str
    right_column: str
    confidence: float
    rationale: str
    correlation_result: CorrelationResult


@dataclass(frozen=True)
class CorrelationExecutionResult:
    results: tuple[CorrelationProposalResult, ...]


class CorrelationExecutionService:
    def execute(self, *, plan: CorrelationPlan, datasets: Iterable[Dataset],
                preview_limit: int = 100) -> CorrelationExecutionResult:
        if not plan.proposals:
            return CorrelationExecutionResult(())
        # Preflight de todas as referências antes de abrir qualquer conexão.
        current = plan.proposals[0]
        try:
            registry: dict[str, list[Dataset]] = {}
            for dataset in datasets:
                registry.setdefault(dataset.name, []).append(dataset)
            if isinstance(preview_limit, bool) or not isinstance(preview_limit, int) or preview_limit < 1:
                raise ValueError('preview_limit must be a positive integer')
            resolved = []
            for current in plan.proposals:
                pair = []
                for name in (current.left_dataset, current.right_dataset):
                    matches = registry.get(name, [])
                    if len(matches) != 1:
                        raise ValueError(f'Dataset missing or ambiguous: {name}')
                    pair.append(matches[0])
                left, right = pair
                engine.validate_compatibility(left, right, current.left_column, current.right_column)
                resolved.append((current, left, right))
        except Exception as exc:
            raise CorrelationExecutionError(current, str(exc)) from exc
        results = []
        for proposal, left, right in resolved:
            try:
                result = engine.correlate(left, right, proposal.left_column, proposal.right_column,
                                          preview_limit=preview_limit)
            except Exception as exc:
                raise CorrelationExecutionError(proposal, str(exc)) from exc
            results.append(CorrelationProposalResult(
                proposal.id, proposal.left_dataset, proposal.left_column,
                proposal.right_dataset, proposal.right_column, proposal.confidence,
                proposal.rationale, result,
            ))
        return CorrelationExecutionResult(tuple(results))
