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
from .analyst import AnalystRunResult, AnalystRunError, CountingProvider, diagnostics
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
        try:
            self.runtime.start()
            return self.pipeline.run(datasets)
        finally:
            self.runtime.stop()

    def shutdown(self):
        self.runtime.stop()

    def answer(self, request, context, state, view):
        """Independent Analyst request using the same configured runtime owner."""
        provider = CountingProvider(self.ai_service.provider)
        ai = AIService(provider, config=self.ai_service.config, retries=self.ai_service.retries)
        service = AnalystService(ai)
        started = time.monotonic()
        try:
            self.config.validate()
            bounded = AnalystContextBuilder().build(context, state, view)
            self.runtime.start()
            response = service.answer(request, bounded, investigation_context=context,
                                      state=state, view=view)
            return AnalystRunResult(response, diagnostics(
                service, provider, self.config.model_path, time.monotonic() - started))
        except Exception as exc:
            raise AnalystRunError(exc, diagnostics(
                service, provider, self.config.model_path, time.monotonic() - started)) from exc
        finally:
            self.runtime.stop()

def create_pipeline(config):
    return LocalInvestigationPipeline(config)
