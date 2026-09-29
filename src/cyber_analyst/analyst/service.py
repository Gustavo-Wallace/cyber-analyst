"""Selection then synthesis over compact registered evidence; no execution."""
from jsonschema import Draft202012Validator, ValidationError
from cyber_analyst.ai.models import AIError
from .models import AnalystRequest, AnalystObservation, AnalystResponse
from .budget import MAX_CONTEXT_BYTES
from .compiler import compile_evidence
from .facts import encode
from .composer import compose, validate_plan, LIMITATIONS
from .prompt import messages


class AnalystResponseError(AIError):
    pass


def _aliases(aliases, minimum=0):
    return {'type': 'array', 'minItems': minimum, 'maxItems': 8, 'uniqueItems': True,
            'items': {'enum': list(aliases)} if aliases else {'not': {}}}


def selection_schema(aliases):
    return {'type': 'object', 'additionalProperties': False,
            'required': ['status', 'fact_aliases'],
            'properties': {'status': {'enum': ['supported', 'insufficient']}, 'fact_aliases': _aliases(aliases)},
            'allOf': [{'if': {'properties': {'status': {'const': 'supported'}}},
                       'then': {'properties': {'fact_aliases': {'minItems': 1}}},
                       'else': {'properties': {'fact_aliases': {'maxItems': 0}}}}]}


def response_schema(aliases):
    return {'type': 'object', 'additionalProperties': False,
            'required': ['status', 'answer_kind', 'sections', 'limitations'],
            'properties': {
                'status': {'const': 'answered'},
                'answer_kind': {'enum': ['factual_summary', 'focused_object', 'correlation_summary', 'investigation_overview']},
                'sections': {'type': 'array', 'minItems': 1, 'maxItems': 4,
                             'items': _aliases(aliases, 1)},
                'limitations': {'type': 'object', 'additionalProperties': False,
                                'required': list(LIMITATIONS),
                                'properties': {code: {'type': 'boolean'} for code in LIMITATIONS}}}}


class AnalystService:
    def __init__(self, ai_service):
        self.ai_service = ai_service
        self.last_diagnostics = {}

    def _stage(self, name, prompt, schema, validate):
        diagnostic = {'domain_retries': 0, 'attempts': []}
        self.last_diagnostics[name] = diagnostic
        for attempt in range(2):
            sizes = {'instructions_bytes': sum(len(m['content'].encode('utf-8')) for m in prompt if m['role'] == 'system'),
                     'schema_bytes': len(encode(schema).encode('utf-8')),
                     'messages_bytes': len(encode(prompt).encode('utf-8'))}
            diagnostic['attempts'].append(sizes)
            result = self.ai_service.generate_structured(prompt, 'analyst_' + name, schema)
            sizes['response'] = result
            try:
                Draft202012Validator(schema).validate(result)
                validate(result)
            except (ValidationError, ValueError) as exc:
                reason = ('Response schema violation at ' + '/'.join(map(str, exc.absolute_path))
                          if isinstance(exc, ValidationError) else str(exc))
                sizes['violation'] = reason
                if attempt:
                    raise AnalystResponseError(name + ': ' + reason + ' after domain retry') from exc
                diagnostic['domain_retries'] += 1
                prompt = [*prompt, {'role': 'system', 'content': reason + '. Return a complete corrected response using only the provided evidence.'}]
            else:
                return result

    def answer(self, request, context):
        self.last_diagnostics = {}
        if not isinstance(request, AnalystRequest):
            raise ValueError('Expected AnalystRequest')
        if len(context.to_json().encode('utf-8')) > MAX_CONTEXT_BYTES:
            raise ValueError('AnalystContext exceeds the committed byte budget')
        packet = compile_evidence(context, request.scope)
        by_alias = {item.alias: item for item in packet.items}
        self.last_diagnostics.update(evidence_bytes=packet.serialized_bytes, evidence_count=len(packet.items),
                                     evidence_truncated=len(packet.items) < packet.total_count)
        selection = self._stage('selection', messages(request, packet.to_dict()), selection_schema(by_alias), lambda result: None)
        if selection['status'] == 'insufficient':
            summary = ('O contexto fornecido n\u00e3o sustenta uma resposta a esta pergunta.'
                       if request.response_language == 'pt-BR' else 'The supplied context does not support an answer to this question.')
            return AnalystResponse('insufficient_context', summary, (), ())
        selected = tuple(by_alias[a] for a in sorted(selection['fact_aliases']))
        selected_aliases = {item.alias: item for item in selected}

        def validate(result):
            validate_plan(result, selected)

        evidence = {'evidence': [item.to_dict() for item in selected]}
        self.last_diagnostics['synthesis_evidence_bytes'] = len(encode(evidence).encode('utf-8'))
        result = self._stage('synthesis', messages(request, evidence, synthesis=True), response_schema(selected_aliases), validate)
        return compose(result, selected, request.response_language)
