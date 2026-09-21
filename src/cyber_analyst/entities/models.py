"""Immutable normalized entities and their source occurrences."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EntityOccurrence:
    dataset_name: str
    column_name: str
    semantic_type: str
    semantic_role: str | None
    value: str
    row_count: int


@dataclass(frozen=True)
class Entity:
    entity_id: str
    entity_type: str
    canonical_value: str
    occurrences: tuple[EntityOccurrence, ...]


@dataclass(frozen=True)
class EntityResult:
    entities: tuple[Entity, ...]

    def by_id(self, entity_id: str) -> Entity | None:
        return next((e for e in self.entities if e.entity_id == entity_id), None)

    def by_value(self, entity_type: str, canonical_value: str) -> Entity | None:
        return next((e for e in self.entities
                     if e.entity_type == entity_type and e.canonical_value == canonical_value), None)
