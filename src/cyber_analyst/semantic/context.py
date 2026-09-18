"""Contexto derivado exclusivamente de metadados, perfil e preview existentes."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
import json
import math

from cyber_analyst.analysis.models import DatasetProfile
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.semantic.models import SemanticUnderstandingError
from cyber_analyst.semantic.evidence import detect_evidence


@dataclass(frozen=True)
class ContextLimits:
    samples_per_column: int = 5
    string_length: int = 120
    columns_per_batch: int = 12
    payload_bytes: int = 24000

    def __post_init__(self):
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in (
            self.samples_per_column, self.string_length, self.columns_per_batch, self.payload_bytes,
        )):
            raise SemanticUnderstandingError("Limites de contexto devem ser inteiros positivos.")


@dataclass(frozen=True)
class SemanticContext:
    dataset_name: str
    row_count: int
    column_count: int
    columns: tuple[dict, ...]
    limits: ContextLimits

    def payload(self, columns=None, *, compact=False) -> dict:
        selected = self.columns if columns is None else columns
        return {
            "dataset_name": self.dataset_name, "row_count": self.row_count,
            "column_count": self.column_count,
            "sampling": {"source": "existing_preview", "max_distinct_values": self.limits.samples_per_column,
                         "max_string_characters": self.limits.string_length,
                         "notice": "Strings may be truncated; temporal/non-finite values are represented as strings. Samples are not representative of all rows."},
            "columns": [{"name": column["name"], "dtype": column["dtype"], "deterministic_evidence": column["deterministic_evidence"]} for column in selected] if compact else list(selected),
        }

    def serialize(self, payload: dict) -> str:
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(text.encode("utf-8")) > self.limits.payload_bytes:
            raise SemanticUnderstandingError("Contexto excede o limite de payload; nenhuma coluna será omitida.")
        return text


def build_context(dataset: Dataset, profile: DatasetProfile, limits: ContextLimits | None = None) -> SemanticContext:
    limits = limits or ContextLimits()
    if (profile.name != dataset.name or profile.row_count != dataset.row_count
            or profile.column_count != dataset.column_count
            or [column.name for column in profile.columns] != dataset.columns
            or any(column.dtype != dataset.schema[column.name] for column in profile.columns)
            or dataset.preview.columns != dataset.columns):
        raise SemanticUnderstandingError("Profile incompatível com o dataset.")

    def value_for_json(value):
        if isinstance(value, (datetime, date, time)):
            value = value.isoformat()
        elif isinstance(value, float) and not math.isfinite(value):
            value = str(value)
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        return value[:limits.string_length] if isinstance(value, str) else value

    columns = []
    for column in profile.columns:
        samples = []
        original_samples = []
        seen = set()
        truncated = False
        for value in dataset.preview.get_column(column.name):
            if value is None:
                continue
            truncated |= isinstance(value, str) and len(value) > limits.string_length
            sample = value_for_json(value)
            key = (type(value), value)
            if key not in seen:
                seen.add(key)
                samples.append(sample)
                original_samples.append(value)
            if len(samples) == limits.samples_per_column:
                break
        fact = {"name": column.name, "dtype": str(column.dtype), "null_count": column.null_count,
                "null_percentage": column.null_percentage, "unique_count": column.unique_count,
                "sample_values": samples, "samples_truncated": truncated}
        fact["deterministic_evidence"] = [asdict(item) for item in detect_evidence(original_samples)]
        if column.dtype.is_numeric():
            fact["statistics"] = {name: value_for_json(getattr(column, name))
                                  for name in ("minimum", "maximum", "mean", "median", "std")}
        columns.append(fact)
    return SemanticContext(dataset.name, dataset.row_count, dataset.column_count, tuple(columns), limits)
