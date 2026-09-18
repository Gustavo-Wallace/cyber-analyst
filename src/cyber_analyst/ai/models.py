"""Configuração e erros públicos da camada de IA."""

from dataclasses import dataclass
import math


class AIError(Exception):
    """Erro de configuração ou uso da camada de IA."""


class AIProviderError(AIError):
    """Falha de transporte ou protocolo do provider."""


class AIStructuredOutputError(AIError):
    def __init__(self, reason: str, attempts: int):
        self.reason = reason
        self.attempts = attempts
        super().__init__(f"Resposta estruturada inválida: {reason}. Tentativas esgotadas ({attempts}).")


@dataclass(frozen=True)
class InferenceConfig:
    """Defaults de desenvolvimento, não parâmetros oficiais de produção."""

    temperature: float = 0.2
    top_p: float = 0.9
    max_tokens: int = 512
    timeout: float = 60.0

    def __post_init__(self):
        for name, value in (("temperature", self.temperature), ("top_p", self.top_p), ("timeout", self.timeout)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise AIError(f"{name} deve ser um número finito.")
        if self.temperature < 0 or not 0 < self.top_p <= 1 or self.timeout <= 0:
            raise AIError("Configuração de inferência fora dos limites permitidos.")
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens < 1:
            raise AIError("max_tokens deve ser um inteiro positivo.")
