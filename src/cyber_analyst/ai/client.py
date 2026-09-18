"""Transporte HTTP local sem proxy, redirecionamentos ou registro de mensagens."""

import http.client
import json
import math
from urllib.parse import urlsplit


class LlamaClientError(Exception):
    """Falha esperada de transporte ou formato da resposta do servidor."""


class LlamaServerClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        try:
            url = urlsplit(base_url)
            port = url.port
        except ValueError as exc:
            raise LlamaClientError("Endereço local inválido.") from exc
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or port is None
                or url.username is not None or url.password is not None
                or url.path not in ("", "/") or url.query or url.fragment):
            raise LlamaClientError("Use http://127.0.0.1:<porta>, sem caminho ou credenciais.")
        if not 1 <= port <= 65535:
            raise LlamaClientError("Porta inválida.")
        self._validate_timeout(timeout)
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://127.0.0.1:{port}"

    @staticmethod
    def _validate_timeout(timeout: float) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise LlamaClientError("O timeout deve ser positivo e finito.")

    def _request(self, method: str, path: str, payload=None, *, timeout=None):
        timeout = self.timeout if timeout is None else timeout
        self._validate_timeout(timeout)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            connection.request(method, path, body=body, headers={
                "Accept": "application/json", "Content-Type": "application/json",
            })
            response = connection.getresponse()
            return response.status, response.read()
        except (OSError, http.client.HTTPException) as exc:
            raise LlamaClientError("Servidor local indisponível, resposta HTTP inválida ou timeout excedido.") from exc
        finally:
            connection.close()

    def health(self, *, timeout: float | None = None) -> int:
        """Retorna 200 (pronto) ou 503 (carregando); outras falhas geram erro."""
        status, _ = self._request("GET", "/health", timeout=timeout)
        if status not in (200, 503):
            raise LlamaClientError(f"Health check retornou HTTP {status}.")
        return status

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Envia mensagens sem streaming e retorna somente o texto da resposta."""
        if not isinstance(messages, list) or not messages:
            raise LlamaClientError("Forneça uma lista não vazia de mensagens.")
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {"role", "content"}
                    or message["role"] not in ("system", "user", "assistant")
                    or not isinstance(message["content"], str)):
                raise LlamaClientError("Cada mensagem deve conter role e content textuais válidos.")
        status, raw = self._request("POST", "/v1/chat/completions", {
            "messages": messages, "stream": False,
        })
        if status != 200:
            raise LlamaClientError(f"Chat retornou HTTP {status}.")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise LlamaClientError("O servidor retornou JSON inválido.") from exc
        if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or not data["choices"]:
            raise LlamaClientError("Resposta sem choices válidos.")
        choice = data["choices"][0]
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise LlamaClientError("Resposta sem conteúdo textual esperado.")
        return message["content"]
