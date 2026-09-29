import json
from dataclasses import replace
import pytest
from cyber_analyst.analyst.compiler import compile_evidence, CompiledEvidence, MAX_MODEL_EVIDENCE_BYTES, MAX_MODEL_FACTS
from cyber_analyst.analyst.facts import encode, fact_registry
from cyber_analyst.analyst.fidelity import validate_text
from cyber_analyst.context import StateService, InvestigationState
from test_analyst_context import context, build


def test_alias_mapping_typed_evidence_deterministic():
    p = build(context())
    packet = compile_evidence(p, 'visible_investigation')
    assert packet == compile_evidence(p, 'visible_investigation')
    assert [i.alias for i in packet.items] == [f'F{i:02d}' for i in range(1, len(packet.items) + 1)]
    registry = {f.fact_id: f for f in fact_registry(p, 'visible_investigation')}
    for item in packet.items:
        assert item.facts
        assert all(registry[f.fact_id] == f for f in item.facts)
        assert 'path' not in item.to_dict() and 'kind' in item.to_dict()
    kinds = {i.to_dict()['kind'] for i in packet.items}
    assert {'entity_identity', 'finding_evidence', 'correlation_metric'} <= kinds


def test_focus_priority_isolation_occurrence_roles():
    c = context()
    state = StateService().focus_entity(InvestigationState(), c, 'ana')
    p = build(c, state)
    packet = compile_evidence(p, 'current_focus')
    assert packet.items[0].to_dict()['kind'] == 'entity_identity'
    assert packet.items[0].to_dict()['canonical_value'] == 'ana'
    assert not any(f.reference.kind == 'finding' for i in packet.items for f in i.facts)
    occurrences = [i.to_dict() for i in packet.items if i.to_dict()['kind'] == 'entity_occurrence']
    assert occurrences and all(o['subject'] == 'ana' and o['row_count'] >= 1 for o in occurrences)
    assert {'dataset_name', 'column_name', 'semantic_role'} <= occurrences[0].keys()
    all_scope = compile_evidence(p, 'visible_investigation')
    assert all_scope.items[0].to_dict()['is_focus']
    with pytest.raises(ValueError):
        compile_evidence(build(c), 'current_focus')


def test_correlation_metrics_typed_and_first():
    c = context()
    state = StateService().focus_correlation(InvestigationState(), c, 'c1')
    packet = compile_evidence(build(c, state), 'current_focus')
    metrics = [i.to_dict() for i in packet.items[:4]]
    assert [i['metric'] for i in metrics] == ['common_keys', 'matched_rows', 'left_only_keys', 'right_only_keys']
    assert all(i['kind'] == 'correlation_metric' for i in metrics)
    assert all('left_column' in i['subject'] and i['is_focus'] for i in metrics)


def test_both_packet_limits_and_oversized_value_no_mutation():
    from cyber_analyst.analyst.models import AnalystContext
    raw = build(context()).to_dict()
    raw['data']['entities']['items'] = [dict(entity_id=f'e{i}', entity_type='username',
        canonical_value='x' * 400 + str(i)) for i in range(60)]
    p = AnalystContext(**raw)
    before = p.to_json()
    packet = compile_evidence(p, 'visible_investigation')
    assert packet.serialized_bytes <= MAX_MODEL_EVIDENCE_BYTES
    assert len(packet.items) <= MAX_MODEL_FACTS
    assert packet.to_dict()['truncated']
    assert p.to_json() == before
    assert encode(packet.to_dict()) == encode(compile_evidence(p, 'visible_investigation').to_dict())


def evidence(value):
    return (CompiledEvidence('F01', encode({'kind': 'test', 'value': value}), ()),)


@pytest.mark.parametrize('text', ['CVE-2026-1234', '10.10.1.15', '2001:db8::1', 'ana@corp.local', 'srv-fin-01', '4 common keys', '9.8', '9,8'])
def test_exact_supported_tokens(text):
    validate_text(text, evidence('CVE-2026-1234 10.10.1.15 2001:db8::1 ana@corp.local srv-fin-01 4 9.8'))


@pytest.mark.parametrize('text', ['CVE-2026-9999', '10.10.1.16', '2001:db8::2', 'bob@corp.local', 'srv-fin-02', '5 common keys', '9.9'])
def test_exact_unsupported_tokens(text):
    with pytest.raises(ValueError):
        validate_text(text, evidence('CVE-2026-1234 10.10.1.15 2001:db8::1 ana@corp.local srv-fin-01 4 9.8'))


def test_alias_digits_are_not_numeric_evidence():
    with pytest.raises(ValueError):
        validate_text('There is 1 record.', evidence('ana'))


def test_stable_analysis_composite_references_preserved():
    facts = fact_registry(build(context()), 'visible_investigation')
    assert len({f.reference.dataset_name for f in facts if f.reference.kind == 'analysis'}) == 2


def test_twenty_four_item_limit_independent_of_bytes():
    from cyber_analyst.analyst.models import AnalystContext
    raw = build(context()).to_dict()
    raw['data']['entities']['items'] = [dict(entity_id=f'e{i}', entity_type='username', canonical_value=f'user{i}') for i in range(60)]
    packet = compile_evidence(AnalystContext(**raw), 'visible_investigation')
    assert len(packet.items) == 24
    assert packet.serialized_bytes < 6144
    assert packet.to_dict()['truncated']


def test_internal_sha_never_rendered_in_packet():
    from cyber_analyst.analyst.models import AnalystContext
    raw = build(context()).to_dict()
    raw['data']['entities']['items'][0]['canonical_value'] = 'entity_' + 'a' * 64
    packet = compile_evidence(AnalystContext(**raw), 'visible_investigation')
    assert 'a' * 64 not in encode(packet.to_dict())
    assert packet.to_dict()['truncated']
