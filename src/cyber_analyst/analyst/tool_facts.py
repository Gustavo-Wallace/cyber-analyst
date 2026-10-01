"""Project bounded tool results onto the existing fact registry and renderers."""
from dataclasses import dataclass, replace, asdict
import hashlib
import json

from .compiler import compile_evidence, EvidencePacket
from .facts import AnalystFact, encode, fact_registry
from .models import AnalystContext, AnalystReference
from .tools import bounded

MAX_COMBINED_MODEL_EVIDENCE_BYTES = 8 * 1024
MAX_COMBINED_MODEL_FACTS = 32


@dataclass(frozen=True)
class ToolFacts:
    facts: tuple
    evidence: tuple
    navigation: tuple
    available_items: int = 0


def compile_tool_result(result):
    """Navigation records are registry facts, not factual prose/composer inputs.

    Search and dataset indexes locate details. They cannot impersonate entity
    identities or executed results. Only supported typed facts enter Stage A.
    """
    if result.status != 'success':
        return ToolFacts((), (), ())
    payload = result.to_dict()['payload']
    data = {'focus': {'kind': 'none', 'visible': False, 'object': None}}
    name = result.tool_name
    section = {'get_entity': 'entities', 'get_relation': 'relations',
               'get_correlation': 'correlations', 'get_finding': 'findings',
               'get_analysis': 'analyses', 'get_dataset': 'datasets'}.get(name)
    obj = dict(payload)
    navigation = []
    if name == 'search_investigation':
        for item in payload['results']['items']:
            ref = AnalystReference(item['kind'], item['target_id'],
                                   item['dataset_name'] if item['kind'] == 'analysis' else None)
            value = {key: item[key] for key in ('kind', 'target_id', 'label', 'dataset_name')}
            digest = hashlib.sha256(encode([asdict(ref), 'search_reference', value]).encode('utf-8')).hexdigest()
            navigation.append(AnalystFact('fact_' + digest, ref, 'search_reference', encode(value)))
    elif name == 'get_entity':
        obj['visible_relation_ids'] = obj.pop('relation_ids')
        obj['visible_neighbor_ids'] = obj.pop('neighbor_ids')
    elif name == 'get_analysis':
        obj['result'] = {'columns': obj['columns'], 'rows': obj.pop('rows')}
    elif name == 'get_relation':
        endpoints = [obj.pop('entity_a'), obj.pop('entity_b')]
        obj['entity_a_id'], obj['entity_b_id'] = [e['entity_id'] for e in endpoints]
        data['entities'] = bounded(endpoints, len(endpoints))
    elif name == 'get_finding':
        # The committed context stores payload as deterministic JSON text.
        for evidence in obj['evidence']['items']:
            if not isinstance(evidence['payload'], str):
                evidence['payload'] = encode(evidence['payload'])
    if section:
        data[section] = bounded([obj], 1)
    context = AnalystContext({}, data)
    facts = fact_registry(context, 'visible_investigation')
    packet = compile_evidence(context, 'visible_investigation',
                              max_facts=MAX_COMBINED_MODEL_FACTS,
                              max_bytes=MAX_COMBINED_MODEL_EVIDENCE_BYTES)
    return ToolFacts((*facts, *navigation), packet.items, tuple(navigation), packet.total_count)


def combine_evidence(base, retrieved):
    """Focus first, retrieved details next, then the existing base priority order."""
    focused = [i for i in base.items if json.loads(i.content_json)['is_focus']]
    remaining = [i for i in base.items if not json.loads(i.content_json)['is_focus']]
    candidates, seen = [], set()
    for item in (*focused, *(i for r in retrieved for i in r.evidence), *remaining):
        content = json.loads(item.content_json)
        content.pop('is_focus', None)
        # Same content for different source objects is not equivalent evidence.
        key = (encode(content), tuple(sorted({encode(asdict(f.reference)) for f in item.facts})))
        if key not in seen:
            seen.add(key)
            candidates.append(item)
    omitted = max(0, base.total_count - len(base.items)) + sum(
        max(0, r.available_items - len(r.evidence)) for r in retrieved)
    total = len(candidates) + omitted
    chosen = []
    for item in candidates:
        if len(chosen) >= MAX_COMBINED_MODEL_FACTS:
            break
        item = replace(item, alias=f'F{len(chosen)+1:02d}')
        if EvidencePacket(base.scope, (*chosen, item), total).serialized_bytes <= MAX_COMBINED_MODEL_EVIDENCE_BYTES:
            chosen.append(item)
    return EvidencePacket(base.scope, tuple(chosen), total)
