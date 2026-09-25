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
