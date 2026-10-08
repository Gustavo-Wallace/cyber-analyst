"""Bounded navigation suggestions from visible facts, without inference."""
from dataclasses import dataclass
from hashlib import sha256
import json

from .models import InvestigationContext
from .view import InvestigationView

MAX_RECOMMENDED_STEPS = 4
ATTENTION_ORDER = ('high', 'medium', 'low', 'informational')


@dataclass(frozen=True)
class RecommendedStep:
    step_id: str
    kind: str
    title: str
    supporting_label: str
    target_kind: str
    target_id: str
    rank: int
    source_ids: tuple[str, ...]


class NextStepsService:
    def build(self, context: InvestigationContext, view: InvestigationView) -> tuple[RecommendedStep, ...]:
        steps, seen = [], set()

        def add(kind, title, supporting, target_kind, target_id, source_ids, identity):
            if identity in seen:
                return
            seen.add(identity)
            key = json.dumps([target_kind, target_id], ensure_ascii=False, separators=(',', ':'))
            steps.append(RecommendedStep(
                'next_step_' + sha256(key.encode('utf-8')).hexdigest(), kind, title, supporting,
                target_kind, target_id, len(steps) + 1, tuple(sorted(source_ids))))

        names = set(view.dataset_names)
        for identifier in sorted(view.finding_ids, key=lambda i: (
                ATTENTION_ORDER.index(context.findings[i].attention_level), i)):
            finding = context.findings[identifier]
            evidence = context.evidence_for(identifier)
            sources = sorted({e.dataset_name for e in evidence if e.dataset_name in names})
            operations = sorted({e.operation for e in evidence if e.dataset_name in names})
            columns = sorted({column for e in evidence
                if (e.dataset_name, e.source_id) in view.analysis_ids
                for column in context.analyses[(e.dataset_name, e.source_id)].columns})
            provenance = tuple(sorted((e.source_type, e.dataset_name, e.source_id, e.operation) for e in evidence))
            supporting = finding.attention_level.capitalize() + ' attention | ' + ', '.join(operations)
            if columns:
                supporting += ' | ' + ', '.join(columns)
            add('review_alert', 'Review alert in ' + ', '.join(sources),
                supporting, 'finding', identifier, finding.evidence_ids, ('evidence', provenance))

        for identifier in sorted(view.correlation_ids, key=lambda i: (
                -context.correlations[i].correlation_result.summary.common,
                -context.correlations[i].correlation_result.summary.matched_rows, i)):
            item = context.correlations[identifier]
            endpoints = tuple(sorted(((item.left_dataset, item.left_column), (item.right_dataset, item.right_column))))
            add('review_data_match', f'Review {item.left_column} <-> {item.right_column} data match',
                f'{item.left_dataset} | {item.right_dataset}', 'correlation', identifier,
                (identifier,), ('match', endpoints))

        visible_relations = set(view.relation_ids)
        connected = sorted(view.entity_ids, key=lambda i: (
            -len(visible_relations.intersection(context.entities[i].relation_ids)),
            context.entities[i].entity_type, context.entities[i].canonical_value, i))
        for identifier in connected:
            entity = context.entities[identifier]
            relations = visible_relations.intersection(entity.relation_ids)
            if not relations:
                continue
            count = len(relations)
            add('inspect_identifier', f'Inspect {entity.canonical_value}',
                f'{entity.entity_type} | {count} visible connection' + ('s' if count != 1 else ''),
                'entity', identifier, tuple(relations), ('entity', entity.entity_type, entity.canonical_value))

        # Dataset fallback only when there is no stronger object-level action.
        if not steps:
            for name in view.dataset_names:
                analyses = tuple(identifier for dataset, identifier in view.analysis_ids if dataset == name)
                if analyses:
                    add('explore_dataset', f'Explore {name}', 'Executed analyses available',
                        'dataset', name, analyses, ('dataset', name))
        return self._select(steps)

    @staticmethod
    def _select(ranked_steps):
        # Reserve category diversity without changing candidate ranks or IDs.
        quotas = {'finding': 2, 'correlation': 1, 'entity': 1}
        selected, selected_ids = [], set()
        for step in ranked_steps:
            if quotas.get(step.target_kind, 0) > 0:
                selected.append(step)
                selected_ids.add(step.step_id)
                quotas[step.target_kind] -= 1
            if len(selected) == MAX_RECOMMENDED_STEPS:
                return tuple(selected)

        # Fill unused places in the original rank order; fallback stays last.
        for step in ranked_steps:
            if step.step_id not in selected_ids:
                selected.append(step)
                selected_ids.add(step.step_id)
            if len(selected) == MAX_RECOMMENDED_STEPS:
                break
        return tuple(selected)
