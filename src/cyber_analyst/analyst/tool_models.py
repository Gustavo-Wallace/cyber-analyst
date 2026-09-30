"""Immutable contracts for controlled read-only investigation queries."""
from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
import json
from jsonschema import Draft202012Validator, ValidationError
from .models import _freeze, _thaw


class ToolValidationError(ValueError):
    pass


LIMITS = MappingProxyType(dict(occurrences=20, references=30, evidence=20, rows=50,
                              columns=40, search=20, text=2048))

_ARGUMENTS = {
    'get_entity': ('entity_id',), 'get_relation': ('relation_id',),
    'get_correlation': ('correlation_id',), 'get_finding': ('finding_id',),
    'get_analysis': ('dataset_name', 'analysis_id'), 'get_dataset': ('dataset_name',),
    'search_investigation': ('query',),
}
_DESCRIPTIONS = {
    'get_entity': 'Read visible entity identity and direct provenance.',
    'get_relation': 'Read a visible relation and its source occurrences.',
    'get_correlation': 'Read committed visible correlation metrics and preview.',
    'get_finding': 'Read a visible finding and its deterministic evidence.',
    'get_analysis': 'Read a visible committed analysis result.',
    'get_dataset': 'Read visible dataset context identifiers.',
    'search_investigation': 'Search visible investigation metadata using existing search.',
}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    argument_schema: Mapping

    def __post_init__(self):
        object.__setattr__(self, 'argument_schema', _freeze(self.argument_schema))

    def to_dict(self):
        return dict(name=self.name, description=self.description, argument_schema=_thaw(self.argument_schema))


def _definition(name, required):
    properties = {key: {'type': 'string', 'minLength': 1, 'pattern': r'\S'} for key in required}
    if name == 'search_investigation':
        properties['limit'] = {'type': 'integer', 'minimum': 1, 'maximum': LIMITS['search']}
    return ToolDefinition(name, _DESCRIPTIONS[name], {'type': 'object', 'additionalProperties': False,
        'required': list(required), 'properties': properties})


TOOL_REGISTRY = MappingProxyType({name: _definition(name, required) for name, required in _ARGUMENTS.items()})


@dataclass(frozen=True)
class ToolRequest:
    tool_name: str
    arguments: Mapping

    def __post_init__(self):
        if not isinstance(self.tool_name, str) or self.tool_name not in TOOL_REGISTRY:
            raise ToolValidationError('Unknown tool')
        if not isinstance(self.arguments, Mapping):
            raise ToolValidationError('Arguments must be a mapping')
        arguments = dict(self.arguments)
        if 'limit' in arguments and type(arguments['limit']) is not int:
            raise ToolValidationError('Limit must be an integer')
        try:
            Draft202012Validator(TOOL_REGISTRY[self.tool_name].to_dict()['argument_schema']).validate(arguments)
        except ValidationError as exc:
            raise ToolValidationError('Invalid tool arguments at ' + '/'.join(map(str, exc.path))) from exc
        if self.tool_name == 'search_investigation':
            arguments['query'] = arguments['query'].strip().casefold()
            arguments.setdefault('limit', LIMITS['search'])
        object.__setattr__(self, 'arguments', _freeze(arguments))


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    arguments: Mapping
    status: str
    payload: Mapping
    error_code: str | None = None

    def __post_init__(self):
        for name in ('arguments', 'payload'):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    def to_dict(self):
        payload = _thaw(self.payload)
        return dict(tool_name=self.tool_name, arguments=_thaw(self.arguments), status=self.status,
                    payload=payload, error_code=self.error_code,
                    payload_bytes=len(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode('utf-8')))
