"""Read-only filtered IDs; no data access or inference."""
from dataclasses import dataclass
from .models import InvestigationContext
from .state import InvestigationState, StateService


@dataclass(frozen=True)
class InvestigationView:
    dataset_names: tuple[str, ...]
    entity_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    # Step IDs are local to a dataset, so preserve their namespace.
    analysis_ids: tuple[tuple[str, str], ...]

    def __post_init__(self):
        for name in ('dataset_names','entity_ids','relation_ids','finding_ids','analysis_ids'):
            values = getattr(self,name)
            if name == 'analysis_ids':
                values = (tuple(pair) for pair in values)
            object.__setattr__(self,name,tuple(sorted(set(values))))


class ViewService:
    def build(self, context: InvestigationContext, state: InvestigationState) -> InvestigationView:
        # Reuse state validation without modifying the supplied state.
        validator = StateService()
        validator.set_dataset_scope(state,context,state.dataset_scope)
        validator.set_entity_types(state,context,state.entity_types)
        validator.set_attention_levels(state,state.attention_levels)
        focus = state.focus
        if focus.entity_id is not None:
            validator.focus_entity(state,context,focus.entity_id)
        if focus.dataset_name is not None:
            validator.focus_dataset(state,context,focus.dataset_name)
        if focus.finding_id is not None:
            validator.focus_finding(state,context,focus.finding_id)
        names = state.dataset_scope or tuple(context.datasets)
        entities,relations,findings,analyses = set(),set(),set(),set()
        for name in names:
            dataset = context.datasets[name]
            entities.update(dataset.entity_ids)
            relations.update(dataset.relation_ids)
            findings.update(dataset.finding_ids)
            analyses.update((name,identifier) for identifier in dataset.analysis_result_ids)
        if state.entity_types:
            entities = {i for i in entities if context.entities[i].entity_type in state.entity_types}
        relations = {i for i in relations if context.relations[i].entity_a_id in entities
                     and context.relations[i].entity_b_id in entities}
        if state.attention_levels:
            findings = {i for i in findings if context.findings[i].attention_level in state.attention_levels}
        return InvestigationView(tuple(names),tuple(entities),tuple(relations),tuple(findings),tuple(analyses))
