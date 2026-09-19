"""Fonte única de contratos: schema, catálogo do prompt e restrições de domínio."""
from dataclasses import dataclass


@dataclass(frozen=True)
class OperationContract:
    description: str
    columns: tuple[int, int | None] | None = None
    groups: tuple[int, int] | None = None
    numeric: bool = False
    temporal: bool = False
    limited: bool = False


CONTRACTS = {
    "null_analysis": OperationContract("Avaliar ausências", columns=(1, None)),
    "unique_count": OperationContract("Contar valores distintos", columns=(1, None)),
    "column_distribution": OperationContract("Distribuição de uma coluna", columns=(1, 1), limited=True),
    "top_values": OperationContract("Valores mais frequentes", columns=(1, 1), limited=True),
    "numeric_summary": OperationContract("Resumo numérico", columns=(1, None), numeric=True),
    "group_count": OperationContract("Contar registros por grupo", groups=(1, 2), limited=True),
    "cross_tab": OperationContract("Cruzamento de duas colunas", columns=(2, 2), limited=True),
    "time_series_count": OperationContract("Contar registros no tempo", groups=(0, 1), temporal=True, limited=True),
}
LIMIT_MAX = 100


def step_schema(operation, contract):
    properties = {
        "operation": {"const": operation, "type": "string"},
        "id": {"type": "string", "minLength": 1, "maxLength": 80},
        "title": {"type": "string", "minLength": 1, "maxLength": 160},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 600},
    }
    required = list(properties)
    for name, bounds in (("columns", contract.columns), ("group_by", contract.groups)):
        if bounds is not None:
            properties[name] = {"type": "array", "items": {"type": "string"},
                                "uniqueItems": True, "minItems": bounds[0]}
            if bounds[1] is not None:
                properties[name]["maxItems"] = bounds[1]
            if bounds[0] > 0:
                required.append(name)
    if contract.temporal:
        properties["time_column"] = {"type": "string"}
        required.append("time_column")
    if contract.limited:
        properties["limit"] = {"type": ["integer", "null"], "minimum": 1, "maximum": LIMIT_MAX}
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required}


def response_schema():
    return {"type": "object", "additionalProperties": False,
            "required": ["dataset_name", "summary", "steps"], "properties": {
                "dataset_name": {"type": "string"},
                "summary": {"type": "string", "minLength": 1, "maxLength": 800},
                "steps": {"type": "array", "maxItems": 8, "items": {
                    "oneOf": [step_schema(name, contract) for name, contract in CONTRACTS.items()]}}}}


def catalog_prompt():
    lines = []
    for name, contract in CONTRACTS.items():
        schema = step_schema(name, contract)
        parts = []
        for parameter in ("columns", "group_by", "time_column", "limit"):
            spec = schema["properties"].get(parameter)
            if spec is None:
                continue
            detail = "obrigatório" if parameter in schema["required"] else "opcional"
            if "minItems" in spec:
                detail += f", {spec['minItems']} a {spec.get('maxItems', 'N')} colunas distintas"
            if parameter == "limit":
                detail += f", null ou inteiro 1–{LIMIT_MAX}"
            parts.append(f"{parameter} ({detail})")
        if contract.numeric:
            parts.append("columns somente dtype numérico")
        if contract.temporal:
            parts.append("time_column temporal plausível e ausente de group_by")
        lines.append(f"{name}: {contract.description}; " + "; ".join(parts))
    return "\n".join(lines)
