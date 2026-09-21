"""Immutable selection intent; no filtering execution or UI dependencies."""
from dataclasses import dataclass, field, replace
from collections.abc import Iterable
from cyber_analyst.findings.service import ATTENTION_LEVELS
from .models import InvestigationContext


class StateError(ValueError):
    """Invalid focus, filter or context reference."""


def _ordered(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise StateError('Expected a collection of filter values, not a string')
    values = tuple(values)
    if any(not isinstance(value, str) for value in values):
        raise StateError('Filter values must be strings')
    if len(values) != len(set(values)):
        raise StateError('Duplicate filter values')
    return tuple(sorted(values))


def _known(value, allowed, label):
    if not isinstance(value, str) or value not in allowed:
        raise StateError(f'Unknown {label}: {value!r}')


@dataclass(frozen=True)
class InvestigationFocus:
    entity_id: str | None = None
    dataset_name: str | None = None
    finding_id: str | None = None

    def __post_init__(self):
        values = (self.entity_id, self.dataset_name, self.finding_id)
        if sum(v is not None for v in values) > 1:
            raise StateError('Focus allows at most one object')
        if any(v is not None and not isinstance(v, str) for v in values):
            raise StateError('Focus references must be strings')


@dataclass(frozen=True)
class InvestigationState:
    focus: InvestigationFocus = field(default_factory=InvestigationFocus)
    dataset_scope: tuple[str, ...] = ()
    entity_types: tuple[str, ...] = ()
    attention_levels: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.focus, InvestigationFocus):
            raise StateError('Expected InvestigationFocus')
        for name in ('dataset_scope', 'entity_types', 'attention_levels'):
            object.__setattr__(self, name, _ordered(getattr(self, name)))
        for value in self.attention_levels:
            _known(value, ATTENTION_LEVELS, 'attention level')


class StateService:
    def initial(self, context: InvestigationContext) -> InvestigationState:
        return InvestigationState()

    def focus_entity(self, state, context, entity_id):
        _known(entity_id, context.entities, 'entity')
        return replace(state, focus=InvestigationFocus(entity_id=entity_id))

    def focus_dataset(self, state, context, dataset_name):
        _known(dataset_name, context.datasets, 'dataset')
        return replace(state, focus=InvestigationFocus(dataset_name=dataset_name))

    def focus_finding(self, state, context, finding_id):
        _known(finding_id, context.findings, 'finding')
        return replace(state, focus=InvestigationFocus(finding_id=finding_id))

    def clear_focus(self, state):
        return replace(state, focus=InvestigationFocus())

    def set_dataset_scope(self, state, context, dataset_names):
        values = _ordered(dataset_names)
        for value in values:
            _known(value, context.datasets, 'dataset')
        return replace(state, dataset_scope=values)

    def set_entity_types(self, state, context, entity_types):
        values = _ordered(entity_types)
        allowed = {e.entity_type for e in context.entities.values()}
        for value in values:
            _known(value, allowed, 'entity type')
        return replace(state, entity_types=values)

    def set_attention_levels(self, state, attention_levels):
        return replace(state, attention_levels=_ordered(attention_levels))

    def clear_filters(self, state):
        return replace(state, dataset_scope=(), entity_types=(), attention_levels=())
