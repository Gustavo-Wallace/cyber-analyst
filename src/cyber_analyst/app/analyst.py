"""Immutable UI-facing outcomes and compact diagnostics; no transcript memory."""
from dataclasses import dataclass
from cyber_analyst.analyst import AnalystResponse


@dataclass(frozen=True)
class AnalystRunResult:
    response: AnalystResponse
    diagnostics: tuple[tuple[str, str | int | float | bool], ...] = ()


class AnalystRunError(Exception):
    def __init__(self, original, diagnostics):
        super().__init__(str(original))
        self.original = original
        self.diagnostics = diagnostics


class CountingProvider:
    """Delegate identical requests and count calls, without retaining prompts."""
    def __init__(self, provider):
        self.provider = provider
        self.calls = 0

    def generate_structured(self, *args, **kwargs):
        self.calls += 1
        return self.provider.generate_structured(*args, **kwargs)

    def generate_text(self, *args, **kwargs):
        self.calls += 1
        return self.provider.generate_text(*args, **kwargs)


def diagnostics(service, provider, model, seconds):
    """Project public diagnostics only; never return arguments or raw evidence."""
    stages = [v for v in service.last_diagnostics.values()
              if isinstance(v, dict) and 'attempts' in v]
    attempts = sum(len(s['attempts']) for s in stages)
    tools = service.tool_diagnostics
    synthesis = service.last_diagnostics.get('synthesis', {}).get('attempts', ())
    answer_kind = synthesis[-1].get('response', {}).get('answer_kind', '') if synthesis else ''
    return (
        ('Provider', 'llama.cpp'), ('Model', str(model.name)),
        ('Tools used', tools.used_tools), ('Tool requests', len(tools.requests)),
        ('Tool executions', tools.actual_execution_count), ('Tool reuse', tools.reused_count),
        ('Stage A', tools.final_stage_a or 'Not completed'),
        ('Stage B', answer_kind or 'Not executed'),
        ('Provider calls', provider.calls), ('Structured retries', max(0, provider.calls - attempts)),
        ('Domain retries', sum(s.get('domain_retries', 0) for s in stages)),
        ('Latency (s)', round(seconds, 3)),
    )
