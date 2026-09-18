from copy import deepcopy
from unittest.mock import Mock

import pytest

from cyber_analyst.ai import (
    AIError, AIProviderError, AIStructuredOutputError, AIService, InferenceConfig,
    LlamaClientError, LlamaCppProvider,
)


SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "status": {"type": "string", "enum": ["ok"]}, "number": {"type": "integer"},
}, "required": ["status", "number"]}
MESSAGES = [{"role": "user", "content": 'Retorne status "ok" e number 42.'}]


def setup_service(responses, retries=2):
    client = Mock()
    client.chat.side_effect = responses
    return AIService(LlamaCppProvider(client), retries=retries), client


def test_text():
    service, client = setup_service([" OK \n"])
    assert service.generate_text(MESSAGES) == "OK"
    assert "response_format" not in client.chat.call_args.kwargs
    assert "chat_template_kwargs" not in client.chat.call_args.kwargs


@pytest.mark.parametrize("structured", [False, True])
def test_provider_error(structured):
    service, client = setup_service([LlamaClientError("offline")])
    with pytest.raises(AIProviderError):
        if structured:
            service.generate_structured(MESSAGES, "test", SCHEMA)
        else:
            service.generate_text(MESSAGES)
    assert client.chat.call_count == 1


def test_valid_and_nonthinking():
    service, client = setup_service(['{"status":"ok","number":42}'])
    original = deepcopy(MESSAGES)
    config = InferenceConfig(temperature=0, top_p=1, max_tokens=200, timeout=10)
    assert service.generate_structured(MESSAGES, "test", SCHEMA, config=config) == {"status": "ok", "number": 42}
    kwargs = client.chat.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_schema", "json_schema": {"name": "test", "strict": True, "schema": SCHEMA}}
    assert kwargs["chat_template_kwargs"] == {"enable_thinking": False}
    assert kwargs["timeout"] == 10 and kwargs["max_tokens"] == 200
    assert "/no_think" in client.chat.call_args.args[0][0]["content"]
    assert MESSAGES == original


@pytest.mark.parametrize("invalid", ['oops', '{"status":"bad","number":42}', ''])
def test_retry_then_success(invalid):
    service, client = setup_service([invalid, '{"status":"ok","number":42}'])
    assert service.generate_structured(MESSAGES, "test", SCHEMA)["number"] == 42
    assert client.chat.call_count == 2
    second = client.chat.call_args.args[0]
    assert "resposta anterior" in second[-1]["content"]
    assert "Traceback" not in second[-1]["content"]


@pytest.mark.parametrize("invalid,reason", [
    ('Aqui está: {"status":"ok","number":42}', "invalid_json"),
    ('```json\n{"status":"ok","number":42}\n```', "invalid_json"),
    ('{"status":"ok","number":42,"extra":true}', "schema_mismatch"),
    ('{"status":"ok","number":"42"}', "schema_mismatch"),
    ('{"status":"ok","number":NaN}', "invalid_json"),
    ('', "empty_content"),
])
def test_exhaustion(invalid, reason):
    service, client = setup_service([invalid] * 3)
    with pytest.raises(AIStructuredOutputError) as error:
        service.generate_structured(MESSAGES, "test", SCHEMA)
    assert error.value.reason == reason
    assert error.value.attempts == client.chat.call_count == 3


def test_zero_retries():
    service, client = setup_service(['invalid'], retries=0)
    with pytest.raises(AIStructuredOutputError) as error:
        service.generate_structured(MESSAGES, "test", SCHEMA)
    assert error.value.attempts == client.chat.call_count == 1


def test_invalid_schema():
    service, client = setup_service([])
    with pytest.raises(AIError):
        service.generate_structured(MESSAGES, "test", {"type": "object", "properties": {"x": {"type": "invalid"}}})
    client.chat.assert_not_called()


def test_local_schema_reference():
    service, _ = setup_service(['{"number":42}'])
    schema = {"type": "object", "$defs": {"integer": {"type": "integer"}},
              "properties": {"number": {"$ref": "#/$defs/integer"}}, "required": ["number"]}
    assert service.generate_structured(MESSAGES, "local_ref", schema) == {"number": 42}


def test_external_reference_is_not_fetched():
    service, client = setup_service(['{"number":42}'])
    schema = {"type": "object", "properties": {"number": {"$ref": "https://example.invalid/schema"}}}
    with pytest.raises(AIError, match="Referência"):
        service.generate_structured(MESSAGES, "external_ref", schema)
    assert client.chat.call_count == 1


def test_empty_text_is_provider_error():
    service, _ = setup_service(['   '])
    with pytest.raises(AIProviderError):
        service.generate_text(MESSAGES)


@pytest.mark.parametrize("kwargs", [{"temperature": -1}, {"timeout": 0}, {"top_p": 2}, {"max_tokens": True}])
def test_config_validation(kwargs):
    with pytest.raises(AIError):
        InferenceConfig(**kwargs)
