"""Planos declarativos; não contêm código executável."""
from dataclasses import dataclass

from cyber_analyst.planning.contracts import CONTRACTS

OPERATIONS = tuple(CONTRACTS)


class AnalysisPlanningError(Exception):
    """Contexto ou plano inválido; nenhum plano parcial é retornado."""


@dataclass(frozen=True)
class AnalysisCandidate:
    candidate_id: str
    operation: str
    columns: tuple[str, ...]
    group_by: tuple[str, ...]
    time_column: str | None
    limit: int | None
    description: str


@dataclass(frozen=True)
class AnalysisStep:
    id: str
    operation: str
    title: str
    rationale: str
    columns: tuple[str, ...]
    group_by: tuple[str, ...]
    time_column: str | None
    limit: int | None


@dataclass(frozen=True)
class AnalysisPlan:
    dataset_name: str
    summary: str
    steps: tuple[AnalysisStep, ...]
