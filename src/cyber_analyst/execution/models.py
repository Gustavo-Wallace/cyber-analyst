from dataclasses import dataclass


class AnalysisExecutionError(Exception):
    def __init__(self, step_id, operation, message):
        self.step_id = step_id
        self.operation = operation
        super().__init__(f"Step {step_id!r} ({operation}): {message}")


@dataclass(frozen=True)
class AnalysisStepResult:
    step_id: str
    operation: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str | int | float | bool | None, ...], ...]


@dataclass(frozen=True)
class AnalysisExecutionResult:
    dataset_name: str
    results: tuple[AnalysisStepResult, ...]
