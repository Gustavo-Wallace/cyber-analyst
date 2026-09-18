"""Entendimento semântico com schema estrito e validação de domínio."""

from jsonschema import validate, ValidationError
import math

from cyber_analyst.ai import AIError, AIService, InferenceConfig
from cyber_analyst.semantic.context import ContextLimits, build_context
from cyber_analyst.semantic.models import (
    DATASET_CATEGORIES, SEMANTIC_TYPES, ColumnUnderstanding, DatasetUnderstanding, SemanticUnderstandingError,
)
from cyber_analyst.semantic.ontology import SEMANTIC_PROMPT
from cyber_analyst.semantic.identifiers import resolve_identifier


def response_schema(mode="full"):
    confidence = {"type": "number", "minimum": 0, "maximum": 1}
    properties = {"dataset_name": {"type": "string"}}
    if mode != "columns":
        properties.update({"dataset_category": {"type": "string", "enum": list(DATASET_CATEGORIES)},
                           "dataset_type": {"type": "string", "minLength": 1, "maxLength": 120},
                           "confidence": confidence, "summary": {"type": "string", "maxLength": 600}})
    if mode != "dataset":
        column = {"name": {"type": "string"}, "semantic_type": {"type": "string", "enum": list(SEMANTIC_TYPES)},
                  "semantic_role": {"type": ["string", "null"], "maxLength": 80}, "confidence": confidence,
                  "is_identifier": {"type": "boolean"}}
        properties["columns"] = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                             "properties": column, "required": list(column)}}
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


class SemanticUnderstandingService:
    def __init__(self, ai_service: AIService, *, limits: ContextLimits | None = None,
                 config: InferenceConfig | None = None):
        self.ai_service = ai_service
        self.limits = limits or ContextLimits()
        self.config = config or InferenceConfig(max_tokens=3072, timeout=180)

    def _call(self, context, payload, mode, names):
        schema = response_schema(mode)
        messages = [{"role": "system", "content": SEMANTIC_PROMPT},
                    {"role": "user", "content": context.serialize(payload)}]
        try:
            result = self.ai_service.generate_structured(messages=messages, schema_name=f"semantic_{mode}",
                                                          schema=schema, config=self.config)
            # Também protege o limite de domínio se um adaptador de serviço for substituído.
            validate(result, schema)
        except (AIError, ValidationError) as exc:
            raise SemanticUnderstandingError("Resposta semântica inválida ou falha da IA.") from exc
        if result["dataset_name"] != context.dataset_name:
            raise SemanticUnderstandingError("Nome do dataset alterado pela IA.")
        confidences = ([result["confidence"]] if mode != "columns" else [])
        confidences.extend(column["confidence"] for column in result.get("columns", []))
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in confidences):
            raise SemanticUnderstandingError("Confidence inválida.")
        if mode != "dataset":
            actual = [column["name"] for column in result["columns"]]
            if len(actual) != len(names) or len(set(actual)) != len(actual) or set(actual) != set(names):
                raise SemanticUnderstandingError(
                    f"Colunas inválidas: omitidas={sorted(set(names) - set(actual))}; "
                    f"inesperadas={sorted(set(actual) - set(names))}; "
                    f"duplicadas={sorted({name for name in actual if actual.count(name) > 1})}."
                )
        return result

    def understand_dataset(self, dataset, profile) -> DatasetUnderstanding:
        context = build_context(dataset, profile, self.limits)
        # Prepara todos os payloads antes de chamar a IA: nenhum lote é ignorado.
        batches = []
        batch = []
        for column in context.columns:
            candidate = [*batch, column]
            try:
                context.serialize(context.payload(candidate))
                fits = len(candidate) <= self.limits.columns_per_batch
            except SemanticUnderstandingError:
                fits = False
            if not fits and batch:
                batches.append(batch)
                batch = []
            batch.append(column)
            context.serialize(context.payload(batch))
        if batch:
            batches.append(batch)
        if len(batches) <= 1:
            result = self._call(context, context.payload(), "full", dataset.columns)
        else:
            compact = context.payload(compact=True)
            context.serialize(compact)
            result = self._call(context, compact, "dataset", [])
            result["columns"] = []
            for batch in batches:
                part = self._call(context, context.payload(batch), "columns", [column["name"] for column in batch])
                result["columns"].extend(part["columns"])
        by_name = {column["name"]: ColumnUnderstanding(**{
            **column, "is_identifier": resolve_identifier(column["semantic_type"], column["is_identifier"]),
        }) for column in result["columns"]}
        return DatasetUnderstanding(dataset.path, result["dataset_name"], result["dataset_category"],
                                    result["dataset_type"], result["confidence"], result["summary"],
                                    tuple(by_name[name] for name in dataset.columns))
