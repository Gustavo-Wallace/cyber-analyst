from dataclasses import dataclass


@dataclass(frozen=True)
class RelationOccurrence:
    dataset_name: str
    entity_a_column: str
    entity_b_column: str
    entity_a_role: str | None
    entity_b_role: str | None
    row_count: int


@dataclass(frozen=True)
class Relation:
    relation_id: str
    relation_type: str
    entity_a_id: str
    entity_b_id: str
    occurrences: tuple[RelationOccurrence, ...]


@dataclass(frozen=True)
class RelationResult:
    relations: tuple[Relation, ...]

    def by_id(self, relation_id: str) -> Relation | None:
        return next((r for r in self.relations if r.relation_id == relation_id), None)

    def for_entity(self, entity_id: str) -> tuple[Relation, ...]:
        return tuple(r for r in self.relations if entity_id in (r.entity_a_id, r.entity_b_id))

    def between(self, entity_a_id: str, entity_b_id: str) -> Relation | None:
        a, b = sorted((entity_a_id, entity_b_id))
        return next((r for r in self.relations if (r.entity_a_id, r.entity_b_id) == (a, b)), None)
