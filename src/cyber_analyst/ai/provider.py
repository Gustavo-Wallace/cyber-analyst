"""Adaptação do llama.cpp; validação semântica do JSON pertence ao serviço."""

from typing import Any, Protocol

from cyber_analyst.ai.client import LlamaClientError, LlamaServerClient
from cyber_analyst.ai.models import AIProviderError, InferenceConfig


class AIProvider(Protocol):
    def generate_text(self, messages: list[dict[str, str]], config: InferenceConfig) -> str: ...

    def generate_structured(self, messages: list[dict[str, str]], schema_name: str,
                            schema: dict[str, Any], config: InferenceConfig) -> str:
        """Retorna texto JSON bruto para validação obrigatória pelo AIService."""
        ...


class LlamaCppProvider:
    def __init__(self, client: LlamaServerClient):
        self.client = client

    def _generate(self, messages, config, **options):
        try:
            return self.client.chat(messages, temperature=config.temperature, top_p=config.top_p,
                                    max_tokens=config.max_tokens, timeout=config.timeout, **options)
        except LlamaClientError as exc:
            raise AIProviderError("Falha na comunicação com o provider local.") from exc

    def generate_text(self, messages, config):
        return self._generate(messages, config)

    def generate_structured(self, messages, schema_name, schema, config):
        return self._generate(messages, config,
            response_format={"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": True, "schema": schema,
            }}, chat_template_kwargs={"enable_thinking": False})
