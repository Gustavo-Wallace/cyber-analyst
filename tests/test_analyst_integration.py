"""Configured factory + real Analyst contracts, with a deterministic provider."""
import json
import pytest
from cyber_analyst.analyst import AnalystRequest
from cyber_analyst.analyst.composer import LIMITATIONS
from cyber_analyst.app.analyst import AnalystRunError
from cyber_analyst.app.config import RuntimeConfig
from cyber_analyst.app.pipeline_factory import create_pipeline
from cyber_analyst.ai.models import AIProviderError, InferenceConfig
from cyber_analyst.context import ContextService, StateService, ViewService
from test_investigation_context import synthetic


class Provider:
    def __init__(self, *, invalid_json=False, redundant_plan=False, error=None):
        self.calls = []
        self.invalid_json = invalid_json
        self.redundant_plan = redundant_plan
        self.error = error

    def generate_structured(self, messages, name, schema, config):
        self.calls.append((messages, name, schema, config))
        if self.error:
            raise self.error
        if self.invalid_json and len(self.calls) == 1:
            return 'invalid'
        if name == 'analyst_selection':
            return json.dumps({'status': 'supported', 'fact_aliases': ['F01']})
        sections = [['F01']]
        if self.redundant_plan and len(self.calls) == 2:
            sections *= 2
        return json.dumps(dict(status='answered', answer_kind='factual_summary',
                               sections=sections, limitations={code: False for code in LIMITATIONS}))


@pytest.fixture
def integration(tmp_path, monkeypatch):
    exe, model = tmp_path / 'llama-server.exe', tmp_path / 'chosen.gguf'
    exe.touch()
    model.touch()
    pipeline = create_pipeline(RuntimeConfig(exe, model))
    lifecycle = []
    monkeypatch.setattr(pipeline.runtime, 'start', lambda: lifecycle.append('start'))
    monkeypatch.setattr(pipeline.runtime, 'stop', lambda: lifecycle.append('stop'))
    context = ContextService().build(synthetic())
    state = StateService().initial(context)
    view = ViewService().build(context, state)
    # Guard all source access while exercising the real Analyst implementation.
    import polars as pl
    import duckdb
    from cyber_analyst.data import csv_loader
    def forbidden(*a, **k): raise AssertionError('Unexpected deterministic execution')
    for target, name in ((pl.LazyFrame, 'collect'), (duckdb, 'connect'), (csv_loader, 'load_csv')):
        monkeypatch.setattr(target, name, forbidden)
    return pipeline, lifecycle, context, state, view


def test_configured_factory_uses_same_inference_configuration_and_closes_runtime(integration):
    pipeline, lifecycle, context, state, view = integration
    provider = Provider()
    pipeline.ai_service.provider = provider
    config = InferenceConfig(temperature=.3, top_p=.8, max_tokens=600, timeout=7)
    pipeline.ai_service.config = config
    pipeline.ai_service.retries = 1
    outcome = pipeline.answer(AnalystRequest('What facts are recorded?'), context, state, view)
    assert lifecycle == ['start', 'stop']
    assert outcome.response.status == 'answered' and len(provider.calls) == 2
    assert all(call[3] is config for call in provider.calls)
    diagnostic = dict(outcome.diagnostics)
    assert diagnostic['Model'] == 'chosen.gguf' and diagnostic['Provider calls'] == 2
    assert diagnostic['Stage A'] == 'supported' and diagnostic['Stage B'] == 'factual_summary'
    assert diagnostic['Structured retries'] == diagnostic['Domain retries'] == 0
    assert not diagnostic['Tools used'] and state is not None


def test_independent_requests_never_include_previous_question_or_answer(integration):
    pipeline, lifecycle, context, state, view = integration
    provider = Provider()
    pipeline.ai_service.provider = provider
    pipeline.answer(AnalystRequest('FIRST UNIQUE QUESTION'), context, state, view)
    first_count = len(provider.calls)
    pipeline.answer(AnalystRequest('SECOND UNIQUE QUESTION'), context, state, view)
    assert lifecycle == ['start', 'stop', 'start', 'stop']
    messages = json.dumps([call[0] for call in provider.calls[first_count:]])
    assert 'FIRST UNIQUE QUESTION' not in messages
    assert 'SECOND UNIQUE QUESTION' in messages


@pytest.mark.parametrize('options,structured,domain', [
    ({'invalid_json': True}, 1, 0), ({'redundant_plan': True}, 0, 1),
])
def test_public_diagnostics_distinguish_structured_and_domain_retries(integration, options, structured, domain):
    pipeline, lifecycle, context, state, view = integration
    pipeline.ai_service.provider = Provider(**options)
    outcome = pipeline.answer(AnalystRequest('Which facts are available?'), context, state, view)
    diagnostics = dict(outcome.diagnostics)
    assert diagnostics['Provider calls'] == 3
    assert diagnostics['Structured retries'] == structured and diagnostics['Domain retries'] == domain
    assert lifecycle == ['start', 'stop']
    assert 'messages' not in diagnostics and 'evidence' not in diagnostics


def test_provider_exception_chain_and_cleanup_preserved(integration):
    pipeline, lifecycle, context, state, view = integration
    timeout = TimeoutError('socket timeout')
    original = AIProviderError('communication failed')
    original.__cause__ = timeout
    pipeline.ai_service.provider = Provider(error=original)
    with pytest.raises(AnalystRunError) as caught:
        pipeline.answer(AnalystRequest('What is recorded?'), context, state, view)
    assert caught.value.original is original and caught.value.__cause__ is original
    assert caught.value.__cause__.__cause__ is timeout
    assert lifecycle == ['start', 'stop']
    assert dict(caught.value.diagnostics)['Provider calls'] == 1


def test_runtime_start_failure_still_cleans_up(integration, monkeypatch):
    pipeline, lifecycle, context, state, view = integration
    original = OSError('runtime unavailable')
    def fail():
        lifecycle.append('start')
        raise original
    monkeypatch.setattr(pipeline.runtime, 'start', fail)
    pipeline.ai_service.provider = Provider()
    with pytest.raises(AnalystRunError) as caught:
        pipeline.answer(AnalystRequest('What is recorded?'), context, state, view)
    assert caught.value.original is original and lifecycle == ['start', 'stop']
    assert dict(caught.value.diagnostics)['Provider calls'] == 0
