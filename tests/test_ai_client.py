import http.client
import json
from unittest.mock import Mock

import pytest

from cyber_analyst.ai.client import LlamaClientError, LlamaServerClient


@pytest.fixture
def transport(monkeypatch):
    connection = Mock()
    factory = Mock(return_value=connection)
    monkeypatch.setattr(http.client, "HTTPConnection", factory)
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = b'{"choices":[{"message":{"content":"OK"}}]}'
    return factory, connection, response


def test_chat_request(transport):
    factory, connection, _ = transport
    client = LlamaServerClient("http://127.0.0.1:12345", timeout=4)
    messages = [{"role": "user", "content": "Olá"}]
    assert client.chat(messages) == "OK"
    factory.assert_called_once_with("127.0.0.1", 12345, timeout=4)
    args, kwargs = connection.request.call_args
    assert args == ("POST", "/v1/chat/completions")
    assert json.loads(kwargs["body"]) == {"messages": messages, "stream": False}
    connection.close.assert_called_once()


@pytest.mark.parametrize("status", [200, 503])
def test_health(transport, status):
    _, connection, response = transport
    response.status = status
    assert LlamaServerClient("http://127.0.0.1:12345").health() == status
    assert connection.request.call_args.args == ("GET", "/health")


@pytest.mark.parametrize("error", [ConnectionRefusedError(), TimeoutError(), http.client.BadStatusLine("bad")])
@pytest.mark.parametrize("operation", ["health", "chat"])
def test_transport_errors(transport, error, operation):
    _, connection, _ = transport
    connection.getresponse.side_effect = error
    client = LlamaServerClient("http://127.0.0.1:12345")
    with pytest.raises(LlamaClientError):
        client.health() if operation == "health" else client.chat([{"role": "user", "content": "hi"}])
    connection.close.assert_called_once()


@pytest.mark.parametrize("body", [b'bad', b'\xff', b'{}', b'[]', b'{"choices":[]}',
    b'{"choices":[{}]}', b'{"choices":[{"message":{"content":null}}]}'])
def test_invalid_response(transport, body):
    transport[2].read.return_value = body
    with pytest.raises(LlamaClientError):
        LlamaServerClient("http://127.0.0.1:12345").chat([{"role": "user", "content": "hi"}])


@pytest.mark.parametrize("operation", ["health", "chat"])
def test_http_error(transport, operation):
    transport[2].status = 500
    client = LlamaServerClient("http://127.0.0.1:12345")
    with pytest.raises(LlamaClientError, match="500"):
        client.health() if operation == "health" else client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.parametrize("url", ["http://0.0.0.0:80", "https://example.com", "http://127.0.0.1:80/path", "http://127.0.0.1:0"])
def test_local_address_only(url):
    with pytest.raises(LlamaClientError):
        LlamaServerClient(url)
