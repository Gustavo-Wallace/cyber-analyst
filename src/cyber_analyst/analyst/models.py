"""Immutable JSON-compatible analyst facts; no provider or UI dependency."""
from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping
import json


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class AnalystContext:
    metadata: Mapping
    data: Mapping

    def __post_init__(self):
        object.__setattr__(self, 'metadata', _freeze(self.metadata))
        object.__setattr__(self, 'data', _freeze(self.data))

    def to_dict(self):
        return {'metadata': _thaw(self.metadata), 'data': _thaw(self.data)}

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


MAX_QUESTION_CHARS = 2000

@dataclass(frozen=True)
class AnalystRequest:
    question: str
    response_language: str = 'en'
    scope: str = 'visible_investigation'

    def __post_init__(self):
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError('Question must not be blank')
        if len(self.question) > MAX_QUESTION_CHARS:
            raise ValueError('Question exceeds 2000 characters')
        if self.scope not in ('visible_investigation', 'current_focus'):
            raise ValueError('Invalid analyst scope')
        if self.response_language not in ('pt-BR', 'en'):
            raise ValueError('Supported languages: pt-BR, en')

@dataclass(frozen=True, order=True)
class AnalystReference:
    kind: str
    target_id: str
    dataset_name: str | None = None

@dataclass(frozen=True)
class AnalystObservation:
    text: str
    references: tuple[AnalystReference, ...]
    fact_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class AnalystResponse:
    status: str
    summary: str
    observations: tuple[AnalystObservation, ...]
    limitations: tuple[str, ...]
