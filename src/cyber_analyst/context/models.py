"""Read-only navigation over existing investigation facts."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from cyber_analyst.entities.models import EntityOccurrence
from cyber_analyst.relations.models import Relation
from cyber_analyst.findings.models import Finding, FindingEvidence


@dataclass(frozen=True)
class EntityContext:
    entity_id: str
    entity_type: str
    canonical_value: str
    occurrences: tuple[EntityOccurrence, ...]
    relation_ids: tuple[str, ...]
    neighbor_entity_ids: tuple[str, ...]
    dataset_names: tuple[str, ...]


@dataclass(frozen=True)
class DatasetContext:
    dataset_name: str
    entity_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    analysis_result_ids: tuple[str, ...]


@dataclass(frozen=True)
class InvestigationContext:
    entities: Mapping[str, EntityContext]
    datasets: Mapping[str, DatasetContext]
    relations: Mapping[str, Relation]
    findings: Mapping[str, Finding]
    evidence: Mapping[str, FindingEvidence]

    def __post_init__(self):
        for name in ('entities','datasets','relations','findings','evidence'):
            object.__setattr__(self,name,MappingProxyType(dict(sorted(getattr(self,name).items()))))

    def entity(self, entity_id: str) -> EntityContext:
        return self.entities[entity_id]

    def dataset(self, dataset_name: str) -> DatasetContext:
        return self.datasets[dataset_name]

    def neighbors(self, entity_id: str) -> tuple[EntityContext, ...]:
        return tuple(self.entities[i] for i in self.entities[entity_id].neighbor_entity_ids)

    def relations_for(self, entity_id: str) -> tuple[Relation, ...]:
        return tuple(self.relations[i] for i in self.entities[entity_id].relation_ids)

    def findings_for(self, dataset_name: str) -> tuple[Finding, ...]:
        return tuple(self.findings[i] for i in self.datasets[dataset_name].finding_ids)

    def evidence_for(self, finding_id: str) -> tuple[FindingEvidence, ...]:
        return tuple(self.evidence[i] for i in sorted(self.findings[finding_id].evidence_ids))
