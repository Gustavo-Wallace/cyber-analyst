"""Selection then synthesis over compact registered evidence; no execution."""
from jsonschema import Draft202012Validator, ValidationError
from cyber_analyst.ai.models import AIError
from .models import AnalystRequest, AnalystObservation, AnalystResponse
from .budget import MAX_CONTEXT_BYTES
from .compiler import compile_evidence
from .facts import encode
from .composer import compose, validate_plan, LIMITATIONS
from .prompt import messages
from dataclasses import replace
from .retrieval import retrieve, ToolDiagnostics, visible_evidence
from .context import AnalystContextBuilder
from .relevance import explicit_subject, guarded_selection


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
        self.tool_diagnostics = ToolDiagnostics()
        self.cancellation = None

    def _check_cancelled(self, stage=None):
        if self.cancellation is not None:
            self.cancellation.check(stage)

    def _stage(self, name, prompt, schema, validate):
        diagnostic = {'domain_retries': 0, 'attempts': []}
        self.last_diagnostics[name] = diagnostic
        for attempt in range(2):
            self._check_cancelled(name)
            sizes = {'instructions_bytes': sum(len(m['content'].encode('utf-8')) for m in prompt if m['role'] == 'system'),
                     'schema_bytes': len(encode(schema).encode('utf-8')),
                     'messages_bytes': len(encode(prompt).encode('utf-8'))}
            diagnostic['attempts'].append(sizes)
            result = self.ai_service.generate_structured(prompt, 'analyst_' + name, schema)
            self._check_cancelled()
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

    def answer(self, request, context, *, investigation_context=None, state=None, view=None, cancellation=None):
        self.cancellation = cancellation
        self._check_cancelled('preparing')
        self.last_diagnostics = {}
        self.tool_diagnostics = ToolDiagnostics()
        if not isinstance(request, AnalystRequest):
            raise ValueError('Expected AnalystRequest')
        if len(context.to_json().encode('utf-8')) > MAX_CONTEXT_BYTES:
            raise ValueError('AnalystContext exceeds the committed byte budget')
        def insufficient():
            self.tool_diagnostics = replace(self.tool_diagnostics, final_stage_a='insufficient')
            summary = ('O contexto fornecido n\u00e3o sustenta uma resposta a esta pergunta.'
                       if request.response_language == 'pt-BR' else 'The supplied context does not support an answer to this question.')
            return AnalystResponse('insufficient_context', summary, (), ())

        subject = None
        bindings = (investigation_context, state, view)
        if any(b is not None for b in bindings):
            if any(b is None for b in bindings):
                raise ValueError('Tool assistance requires context, state and view together')
            if AnalystContextBuilder().build(*bindings) != context:
                raise ValueError('AnalystContext does not match current context/state/view')
            focus = context.data['focus']
            if request.scope == 'current_focus' and not focus['visible']:
                return insufficient()
            subject = explicit_subject(request.question, investigation_context, view)
            if subject is not None and not subject.visible:
                return insufficient()
        packet = compile_evidence(context, request.scope)
        if investigation_context is not None:
            packet = visible_evidence(packet, view)
        by_alias = {item.alias: item for item in packet.items}
        self.last_diagnostics.update(evidence_bytes=packet.serialized_bytes, evidence_count=len(packet.items),
                                     evidence_truncated=len(packet.items) < packet.total_count)
        selection = self._stage('selection', messages(request, packet.to_dict()), selection_schema(by_alias), lambda result: None)
        guarded = guarded_selection(selection, by_alias, subject)
        self.last_diagnostics['selection']['subject_rejected'] = guarded != selection
        selection = guarded
        if selection['status'] == 'insufficient' and investigation_context is not None:
            def publish(diagnostic):
                self.tool_diagnostics = diagnostic
            packet, self.tool_diagnostics = retrieve(
                self._stage, request, context, packet, *bindings, publish, check=self._check_cancelled)
            self._check_cancelled()
            if self.tool_diagnostics.used_tools:
                by_alias = {item.alias: item for item in packet.items}
                selection = self._stage('post_tool_selection', messages(request, packet.to_dict()),
                                        selection_schema(by_alias), lambda result: None)
        guarded = guarded_selection(selection, by_alias, subject)
        if 'post_tool_selection' in self.last_diagnostics:
            self.last_diagnostics['post_tool_selection']['subject_rejected'] = guarded != selection
        selection = guarded
        self.tool_diagnostics = replace(self.tool_diagnostics, final_stage_a=selection['status'])
        if selection['status'] == 'insufficient':
            return insufficient()
        selected = tuple(by_alias[a] for a in sorted(selection['fact_aliases']))
        selected_aliases = {item.alias: item for item in selected}

        def validate(result):
            validate_plan(result, selected)

        evidence = {'evidence': [item.to_dict() for item in selected]}
        self.last_diagnostics['synthesis_evidence_bytes'] = len(encode(evidence).encode('utf-8'))
        result = self._stage('synthesis', messages(request, evidence, synthesis=True), response_schema(selected_aliases), validate)
        self._check_cancelled()
        return compose(result, selected, request.response_language)
