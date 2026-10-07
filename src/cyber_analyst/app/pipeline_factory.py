"""Real service composition with explicit per-run runtime ownership."""
from cyber_analyst.ai.runtime import LlamaRuntime
from cyber_analyst.ai.client import LlamaServerClient
from cyber_analyst.ai.provider import LlamaCppProvider
from cyber_analyst.ai.service import AIService
from cyber_analyst.semantic.service import SemanticUnderstandingService
from cyber_analyst.planning.service import AnalysisPlannerService
from cyber_analyst.execution.service import AnalysisExecutionService
from cyber_analyst.entities.service import EntityService
from cyber_analyst.relations.service import RelationService
from cyber_analyst.correlation.planner import CorrelationPlanner
from cyber_analyst.correlation.execution import CorrelationExecutionService
from cyber_analyst.findings.service import FindingService
from cyber_analyst.investigation.pipeline import InvestigationPipeline
from cyber_analyst.analyst import AnalystService, AnalystContextBuilder
from .analyst import AnalystRunResult, AnalystRunError, CountingProvider, diagnostics, AnalystRuntimeOwner
from cyber_analyst.analyst.cancellation import CancellationToken, AnalystCancelled
from threading import Lock
import time

class _RuntimeClient:
    def __init__(self, runtime):
        self.runtime = runtime

    def chat(self, *args, **kwargs):
        return LlamaServerClient(self.runtime.base_url).chat(*args, **kwargs)

class LocalInvestigationPipeline:
    def __init__(self, config):
        config.validate()
        self.config = config
        self._execution_lock = Lock()
        self._analyst_owner = None
        self.runtime = LlamaRuntime(config.llama_executable, config.model_path)
        ai = AIService(LlamaCppProvider(_RuntimeClient(self.runtime)))
        self.ai_service = ai
        self.pipeline = InvestigationPipeline(
            semantic_service=SemanticUnderstandingService(ai),
            analysis_planner=AnalysisPlannerService(ai), analysis_executor=AnalysisExecutionService(),
            entity_service=EntityService(), relation_service=RelationService(),
            correlation_planner=CorrelationPlanner(ai), correlation_executor=CorrelationExecutionService(),
            finding_service=FindingService(ai))

    def run(self, datasets):
        if not self._execution_lock.acquire(blocking=False):
            raise ValueError('The local runtime is already in use')
        try:
            self.runtime.start()
            return self.pipeline.run(datasets)
        finally:
            try:
                self.runtime.stop()
            finally:
                self._execution_lock.release()

    def shutdown(self):
        if self._analyst_owner is not None:
            self._analyst_owner.cancellation.cancel()
        elif self.runtime.has_process:
            self.runtime.stop()

    def answer(self, request, context, state, view, *, cancellation=None):
        """Independent Analyst request using the same configured runtime owner."""
        cancellation = cancellation or CancellationToken()
        cancellation.check('preparing')
        if not self._execution_lock.acquire(blocking=False):
            raise ValueError('The local runtime is already in use')
        owner = AnalystRuntimeOwner(self.runtime, cancellation)
        self._analyst_owner = owner
        provider = CountingProvider(self.ai_service.provider, cancellation)
        ai = AIService(provider, config=self.ai_service.config, retries=self.ai_service.retries)
        service = AnalystService(ai)
        started = time.monotonic()
        try:
            self.config.validate()
            bounded = AnalystContextBuilder().build(context, state, view)
            cancellation.check('runtime_startup')
            self.runtime.start(cancel_event=cancellation.event)
            cancellation.check()
            response = service.answer(request, bounded, investigation_context=context,
                                      state=state, view=view, cancellation=cancellation)
            cancellation.check()
            return AnalystRunResult(response, diagnostics(
                service, provider, self.config.model_path, time.monotonic() - started))
        except Exception as exc:
            if cancellation.requested:
                raise AnalystCancelled(cancellation.request_id) from exc
            raise AnalystRunError(exc, diagnostics(
                service, provider, self.config.model_path, time.monotonic() - started)) from exc
        finally:
            try:
                owner.close()
            finally:
                self._analyst_owner = None
                self._execution_lock.release()

def create_pipeline(config):
    return LocalInvestigationPipeline(config)
