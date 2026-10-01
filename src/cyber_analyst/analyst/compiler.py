"""Typed, bounded projection of registered facts. Never reads source datasets."""
from dataclasses import dataclass
import json
import re

from .facts import AnalystFact, FIELDS, encode, fact_registry

MAX_MODEL_EVIDENCE_BYTES = 6 * 1024
MAX_MODEL_FACTS = 24
_SHA = re.compile(r'(?<![a-fA-F0-9])[a-fA-F0-9]{64}(?![a-fA-F0-9])')
_METRICS = {'common': 'common_keys', 'only_a': 'left_only_keys',
            'only_b': 'right_only_keys', 'rows_a': 'left_rows', 'rows_b': 'right_rows',
            'unique_a': 'left_unique_keys', 'unique_b': 'right_unique_keys',
            'matched_rows': 'matched_rows'}


@dataclass(frozen=True)
class CompiledEvidence:
    alias: str
    content_json: str
    facts: tuple[AnalystFact, ...]

    def to_dict(self):
        return {'alias': self.alias, **json.loads(self.content_json)}


@dataclass(frozen=True)
class EvidencePacket:
    scope: str
    items: tuple[CompiledEvidence, ...]
    total_count: int

    def to_dict(self):
        return {'scope': self.scope, 'evidence': [i.to_dict() for i in self.items],
                'available_items': self.total_count, 'included_items': len(self.items),
                'truncated': len(self.items) < self.total_count}

    @property
    def serialized_bytes(self):
        return len(encode(self.to_dict()).encode('utf-8'))


def compile_evidence(context, scope, *, max_facts=MAX_MODEL_FACTS,
                     max_bytes=MAX_MODEL_EVIDENCE_BYTES):
    """Aliases identify typed bundles; every value retains its original fact mapping."""
    focus = context.to_dict()['data']['focus']
    facts = fact_registry(context, scope)
    focused_reference = None
    if focus['kind'] != 'none':
        kind, field = FIELDS[focus['kind']]
        obj = focus['object']
        focused_reference = (kind, obj[field], obj.get('dataset_name') if kind == 'analysis' else None)
        if scope == 'visible_investigation' and focus.get('visible'):
            facts = tuple({f.fact_id: f for f in (*fact_registry(context, 'current_focus'), *facts)}.values())
    groups = {}
    for fact in facts:
        groups.setdefault(fact.reference, {})[fact.path] = fact
    candidates = []
    for ref, fields in groups.items():
        values = {p: json.loads(f.value_json) for p, f in fields.items()}
        is_focus = (ref.kind, ref.target_id, ref.dataset_name) == focused_reference

        def add(kind, paths, **content):
            supporting = tuple(fields[p] for p in paths if p in fields)
            if not supporting:
                return
            item = {'kind': kind, 'is_focus': is_focus, **content}
            # Internal hashes are navigation keys, never model vocabulary. A
            # pathological value containing one is omitted, with truncation reported.
            candidates.append((item, supporting))

        if ref.kind == 'entity':
            identity = ['canonical_value', 'entity_type']
            add('entity_identity', identity, canonical_value=values.get('canonical_value'),
                entity_type=values.get('entity_type'))
            for path, value in values.items():
                if path.startswith('occurrences/'):
                    add('entity_occurrence', [*identity, path], subject=values.get('canonical_value'),
                        **value)
                elif path.startswith('dataset_names/'):
                    add('entity_dataset', [*identity, path], subject=values.get('canonical_value'), dataset=value)
        elif ref.kind == 'correlation':
            endpoints = ['left_dataset', 'left_column', 'right_dataset', 'right_column']
            subject = {p: values[p] for p in endpoints if p in values}
            for metric in ('common', 'matched_rows', 'only_a', 'only_b', 'rows_a', 'rows_b', 'unique_a', 'unique_b'):
                path = 'metrics/' + metric
                if path in values:
                    add('correlation_metric', [*endpoints, path], subject=subject,
                        metric=_METRICS[metric], value=values[path])
            columns = [v for p, v in values.items() if p.startswith('preview/columns/')]
            for path, value in values.items():
                if path.startswith('preview/rows/'):
                    add('correlation_preview_row', [*endpoints, path, *[p for p in fields if p.startswith('preview/columns/')]],
                        subject=subject, columns=columns, row=value)
        elif ref.kind == 'finding':
            prefixes = sorted({p.rsplit('/', 1)[0] for p in fields if p.startswith('evidence/')})
            for prefix in prefixes:
                paths = [p for p in fields if p.startswith(prefix + '/') and p.rsplit('/', 1)[-1] not in ('evidence_id', 'source_id')]
                payload = {p.rsplit('/', 1)[-1]: values[p] for p in paths}
                add('finding_evidence', ['attention_level', *paths], attention_level=values.get('attention_level'), **payload)
        elif ref.kind == 'analysis':
            paths = [p for p in fields if not p.startswith('result/')]
            metadata = {p: values[p] for p in ('dataset_name', 'operation', 'title') if p in values}
            metadata['columns'] = [v for p, v in values.items() if p.startswith('columns/')]
            add('analysis_metadata', paths, **metadata)
            for path, value in values.items():
                if path.startswith('result/rows/'):
                    add('analysis_result_row', [*paths, path], **metadata, row=value)
        elif ref.kind == 'relation':
            # Endpoint identities are resolved exclusively from the registered facts.
            endpoints = []
            support = []
            for key in ('entity_a_id', 'entity_b_id'):
                for entity_ref, entity_fields in groups.items():
                    if entity_ref.kind == 'entity' and entity_ref.target_id == values.get(key):
                        endpoints.append({p: json.loads(entity_fields[p].value_json) for p in ('canonical_value', 'entity_type') if p in entity_fields})
                        support.extend(entity_fields[p] for p in ('canonical_value', 'entity_type') if p in entity_fields)
            if len(endpoints) == 2:
                add('relation_endpoints', ['relation_type', 'entity_a_id', 'entity_b_id'], relation_type=values.get('relation_type'), endpoints=endpoints)
                item, supporting = candidates[-1]
                candidates[-1] = (item, (*supporting, *support))
            for path, value in values.items():
                if path.startswith('occurrences/'):
                    add('relation_occurrence', ['relation_type', path], relation_type=values.get('relation_type'), occurrence=value)
        # Dataset identity itself is a registry reference, not a registered fact.
        # Do not manufacture facts from identifiers skipped by fact_registry.

    candidates.sort(key=lambda pair: not pair[0]['is_focus'])  # stable within priority
    selected = []
    for item, supporting in candidates:
        if len(selected) == max_facts:
            break
        if _SHA.search(encode(item)):
            continue
        candidate = CompiledEvidence(f'F{len(selected) + 1:02d}', encode(item), supporting)
        proposed = EvidencePacket(scope, (*selected, candidate), len(candidates))
        if proposed.serialized_bytes <= max_bytes:
            selected.append(candidate)
    return EvidencePacket(scope, tuple(selected), len(candidates))
