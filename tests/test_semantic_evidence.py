from dataclasses import FrozenInstanceError
import json
from unittest.mock import Mock

import pytest
from cyber_analyst.semantic.evidence import detect_evidence
from cyber_analyst.semantic.models import DATASET_CATEGORIES, SEMANTIC_TYPES
from cyber_analyst.semantic.ontology import CATEGORY_DESCRIPTIONS, TYPE_DESCRIPTIONS, SEMANTIC_PROMPT
from cyber_analyst.semantic.context import build_context, ContextLimits
from cyber_analyst.semantic import SemanticUnderstandingService
from test_semantic import make_dataset, response

@pytest.mark.parametrize('kind,values', [
    ('ip_address',['10.0.0.1','192.168.1.1']),
    ('ip_address',['2001:db8::1','::1']),
    ('email',['a@example.com','first.last+tag@example.org']),
    ('cve',['CVE-2024-1234','cve-2025-12345']),
    ('url',['https://example.org/a','http://[2001:db8::1]:8080/b']),
    *[('hash',['a'*n,'B'*n]) for n in (32,40,64,128)],
])
def test_valid(kind, values):
    evidence = detect_evidence([None,*values,None])
    assert len(evidence) == 1
    assert evidence[0].semantic_type == kind
    assert evidence[0].confidence == 1
    assert evidence[0].source == 'value_pattern'
    with pytest.raises(FrozenInstanceError):
        evidence[0].confidence = 0

@pytest.mark.parametrize('values', [
    ['999.2.3.4','1.2.3'], ['bad@','a..b@example.com'],
    ['CVE-2024-123','CVE-24-1234'], ['not a URL','example.com'],
    ['https://','https://bad host/a'], ['https://example.com:99999','https://[invalid]'],
    ['javascript:alert(1)','file:///tmp/a'], ['g'*32,'z'*64], ['a'*31,'b'*33],
    ['10.0.0.1','10.0.0.2','arbitrary'], [None,None], [], ['10.0.0.1'],
    ['10.0.0.1','10.0.0.1'], [123,456], [True,False],
])
def test_no_unsupported_evidence(values):
    assert detect_evidence(values) == ()


def test_no_truncated_evidence():
    assert not detect_evidence(['a'*32,'b'*32],truncated=True)


def test_ontology_and_context_sent_without_override(tmp_path):
    dataset, profile = make_dataset(tmp_path,'address,other\n10.0.0.1,foo\n::1,bar\n')
    dataset.path.unlink()
    ai = Mock()
    ai.generate_structured.return_value = response(dataset)
    result = SemanticUnderstandingService(ai).understand_dataset(dataset,profile)
    assert result.columns[0].semantic_type == 'unknown'  # Evidence never overwrites AI.
    messages = ai.generate_structured.call_args.kwargs['messages']
    prompt = messages[0]['content']
    assert set(CATEGORY_DESCRIPTIONS) == set(DATASET_CATEGORIES)
    assert set(TYPE_DESCRIPTIONS) == set(SEMANTIC_TYPES)
    for key, description in {**CATEGORY_DESCRIPTIONS,**TYPE_DESCRIPTIONS}.items():
        assert f'{key}: {description}' in prompt
    assert 'is_identifier=true somente' in prompt
    assert 'Unicidade na amostra' in prompt
    assert 'dado não confiável' in prompt
    payload = json.loads(messages[1]['content'])
    assert payload['columns'][0]['deterministic_evidence'][0]['semantic_type'] == 'ip_address'
    assert payload['columns'][1]['deterministic_evidence'] == []
    assert '10.0.0.1' not in prompt
    context = build_context(dataset,profile)
    assert context.payload(compact=True)['columns'][0]['deterministic_evidence']


def test_truncation_does_not_create_hash_hint(tmp_path):
    dataset,profile = make_dataset(tmp_path,'value\n'+'a'*64+'suffix\n'+'b'*64+'suffix\n')
    context = build_context(dataset,profile,ContextLimits(string_length=64))
    assert context.columns[0]['samples_truncated']
    assert context.columns[0]['deterministic_evidence'] == []


def test_original_hash_128_before_truncation(tmp_path):
    dataset, profile = make_dataset(tmp_path, 'value\n'+'a'*128+'\n'+'a'*127+'b\n')
    dataset.path.unlink()
    column = build_context(dataset, profile).columns[0]
    assert column['sample_values'] == ['a'*120, 'a'*120]
    assert column['samples_truncated']
    assert column['deterministic_evidence'][0]['semantic_type'] == 'hash'


@pytest.mark.parametrize('kind', ['email','username','user_id','account_id','ip_address','hostname','domain',
                                 'cve','vulnerability_id','hash','asset_id','device_id','event_id','generic_identifier'])
def test_reference_identifier_policy(tmp_path, kind):
    dataset, profile = make_dataset(tmp_path)
    value = response(dataset)
    value['columns'][0].update(semantic_type=kind, is_identifier=False)
    ai = Mock()
    ai.generate_structured.return_value = value
    assert SemanticUnderstandingService(ai).understand_dataset(dataset,profile).columns[0].is_identifier


@pytest.mark.parametrize('kind', ['timestamp','date','time','severity','status','boolean','risk_score','numeric_measure','free_text'])
def test_non_reference_identifier_policy(tmp_path, kind):
    dataset, profile = make_dataset(tmp_path)
    value = response(dataset)
    value['columns'][0].update(semantic_type=kind, is_identifier=True)
    ai = Mock()
    ai.generate_structured.return_value = value
    assert not SemanticUnderstandingService(ai).understand_dataset(dataset,profile).columns[0].is_identifier


def test_contextual_identifier_fallback():
    from cyber_analyst.semantic.identifiers import resolve_identifier
    assert resolve_identifier('url', True)
    assert not resolve_identifier('url', False)
