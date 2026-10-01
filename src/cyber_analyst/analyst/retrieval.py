"""Bounded orchestration of registered read tools with immutable diagnostics."""
from dataclasses import dataclass
from .models import _freeze, _thaw
from .facts import encode, FIELDS
from .tool_models import ToolRequest, ToolResult, ToolValidationError
from .tools import InvestigationToolService
from .tool_planner import planning_schema, planning_messages, ROUND_TOOL_LIMITS
from .tool_facts import compile_tool_result, combine_evidence
from .compiler import EvidencePacket
import json


@dataclass(frozen=True)
class ToolDiagnostics:
    used_tools: bool = False
    planning_rounds: int = 0
    executions: tuple = ()
    post_tool_evidence_bytes: int = 0
    post_tool_fact_count: int = 0
    truncated: bool = False
    final_stage_a: str | None = None
    requests: tuple = ()

    @property
    def actual_execution_count(self):
        return len(self.executions)

    @property
    def reused_count(self):
        return sum(r['reused'] for r in self.requests)

    def __post_init__(self):
        object.__setattr__(self, 'executions', tuple(_freeze(e) for e in self.executions))
        object.__setattr__(self, 'requests', tuple(_freeze(e) for e in self.requests))

    def to_dict(self):
        return {name: _thaw(getattr(self, name)) for name in self.__dataclass_fields__}


def visible_evidence(packet, view):
    """Do not reintroduce hidden provenance via the pre-existing base packet."""
    names = set(view.dataset_names)
    allowed = {'entity': set(view.entity_ids), 'relation': set(view.relation_ids),
               'finding': set(view.finding_ids), 'correlation': set(view.correlation_ids),
               'dataset': names, 'analysis': set(view.analysis_ids)}
    items = []
    for item in packet.items:
        if any((f.reference.dataset_name, f.reference.target_id) not in allowed['analysis']
               if f.reference.kind == 'analysis' else f.reference.target_id not in allowed[f.reference.kind]
               for f in item.facts):
            continue
        content = json.loads(item.content_json)
        kind = content['kind']
        source = content.get('dataset') if kind == 'entity_dataset' else content.get('dataset_name')
        if kind == 'relation_occurrence':
            source = content['occurrence'].get('dataset_name')
        if source is not None and (not isinstance(source, str) or source not in names):
            continue
        if kind == 'finding_evidence':
            # source_id is deliberately absent from model-facing content.
            source_ids = [json.loads(f.value_json) for f in item.facts if f.path.endswith('/source_id')]
            if source_ids and content.get('source_type') == 'correlation' and source_ids[0] not in view.correlation_ids:
                continue
        items.append(item)
    return EvidencePacket(packet.scope, tuple(items), packet.total_count)


def compact_focus(context):
    focus = context.to_dict()['data']['focus']
    if focus['kind'] == 'none' or not focus['visible']:
        return {'kind': 'none'}
    obj = focus['object']
    fields = (FIELDS[focus['kind']][1], 'dataset_name', 'canonical_value',
              'entity_type', 'operation', 'left_dataset', 'left_column',
              'right_dataset', 'right_column')
    return {'kind': focus['kind'], **{k: obj[k] for k in fields if k in obj}}


def _in_scope(request, analyst_context, tool_request):
    if request.scope != 'current_focus':
        return True
    focus = analyst_context.to_dict()['data']['focus']
    if not focus.get('visible'):
        return False
    obj, kind = focus['object'], focus['kind']
    args, tool = tool_request.arguments, tool_request.tool_name
    direct = {'entities': 'get_entity', 'relations': 'get_relation',
              'correlations': 'get_correlation', 'findings': 'get_finding',
              'analyses': 'get_analysis', 'datasets': 'get_dataset'}
    field = FIELDS[kind][1]
    if tool == direct[kind] and args.get(field) == obj.get(field):
        return kind != 'analyses' or args['dataset_name'] == obj['dataset_name']
    # Only direct links already represented in focus context, never global roaming.
    if kind == 'entities':
        links = {'get_entity': ('entity_id', 'visible_neighbor_ids'),
                 'get_relation': ('relation_id', 'visible_relation_ids'),
                 'get_dataset': ('dataset_name', 'dataset_names')}
        if tool in links:
            arg, collection = links[tool]
            return args[arg] in obj.get(collection, {}).get('items', ())
    if kind == 'relations' and tool == 'get_entity':
        return args['entity_id'] in (obj.get('entity_a_id'), obj.get('entity_b_id'))
    if kind in ('analyses', 'correlations') and tool == 'get_dataset':
        return args['dataset_name'] in (obj.get('dataset_name'), obj.get('left_dataset'), obj.get('right_dataset'))
    return False


def execute_request(raw, request, analyst_context, context, state, view):
    try:
        tool = ToolRequest(raw['tool_name'], raw['arguments'])
    except (ToolValidationError, KeyError, TypeError):
        return ToolResult('invalid_request', {}, 'error', {}, 'invalid_arguments')
    if not _in_scope(request, analyst_context, tool):
        return ToolResult(tool.tool_name, tool.arguments, 'error', {}, 'outside_request_scope')
    return InvestigationToolService().execute(tool, context, state, view)


def retrieve(stage, request, analyst_context, base, context, state, view, publish):
    previous, executions, compiled = [], [], []
    rounds = 0
    cache, requests = {}, []
    packet = base
    for number, limit in enumerate(ROUND_TOOL_LIMITS, 1):
        rounds = number
        publish(ToolDiagnostics(bool(executions), rounds, tuple(executions),
                                packet.serialized_bytes if executions else 0,
                                len(packet.items) if executions else 0,
                                requests=tuple(requests)))
        plan = stage(f'tool_planning_{number}',
                     planning_messages(request, compact_focus(analyst_context), previous, limit),
                     planning_schema(limit), lambda result: None)
        if not plan['requests']:
            publish(ToolDiagnostics(bool(executions), rounds, tuple(executions), requests=tuple(requests)))
            break
        for raw in plan['requests']:
            validated = ToolRequest(raw['tool_name'], raw['arguments'])
            key = (id(context), id(view), validated.tool_name, encode(_thaw(validated.arguments)))
            reused = key in cache
            if reused:
                result, facts = cache[key]
            else:
                result = execute_request(raw, request, analyst_context, context, state, view)
                facts = compile_tool_result(result)
                cache[key] = (result, facts)
                compiled.append(facts)
            record = result.to_dict()
            record_diagnostic = dict(tool_name=record['tool_name'], arguments=record['arguments'],
                                   status=result.status, error_code=result.error_code,
                                   result_bytes=record['payload_bytes'], generated_fact_count=len(facts.facts))
            requests.append(dict(**record_diagnostic, reused=reused))
            if not reused:
                executions.append(record_diagnostic)
            # The planner needs navigation identities, not arbitrary raw result rows.
            payload = record['payload']
            navigation = {k: v for k, v in payload.items() if k in (
                'results', 'entity_id', 'relation_id', 'correlation_id', 'finding_id',
                'analysis_id', 'dataset_name', 'canonical_value', 'entity_type',
                'entity_ids', 'relation_ids', 'finding_ids', 'analysis_ids')}
            compact = dict(tool_name=result.tool_name, status=result.status,
                           error_code=result.error_code, navigation={})
            for key, value in navigation.items():
                if isinstance(value, dict) and 'items' in value:
                    value = dict(value, items=list(value['items']))
                    while value['items'] and len(encode(value).encode('utf-8')) > 3500:
                        value['items'].pop()
                    value['included_count'] = len(value['items'])
                    value['truncated'] = value['included_count'] < value['total_count']
                proposed = {**compact['navigation'], key: value}
                if len(encode(proposed).encode('utf-8')) <= 4096:
                    compact['navigation'] = proposed
            compact['truncated'] = len(compact['navigation']) < len(navigation)
            previous.append(compact)
            packet = visible_evidence(combine_evidence(base, compiled), view)
            publish(ToolDiagnostics(True, rounds, tuple(executions), packet.serialized_bytes,
                                    len(packet.items), packet.to_dict()['truncated'], requests=tuple(requests)))
    return packet, ToolDiagnostics(bool(executions), rounds, tuple(executions),
                                   packet.serialized_bytes if executions else 0,
                                   len(packet.items) if executions else 0,
                                   packet.to_dict()['truncated'] if executions else False, requests=tuple(requests))
