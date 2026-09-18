from dataclasses import dataclass
from pathlib import Path


DATASET_CATEGORIES = (
    "identity_data", "authentication_events", "network_events", "endpoint_events",
    "vulnerability_data", "asset_inventory", "credential_exposure", "email_security",
    "access_control", "application_events", "security_alerts", "generic_security_data", "unknown",
)
SEMANTIC_TYPES = (
    "email", "username", "user_id", "account_id", "ip_address", "hostname", "domain", "url",
    "port", "protocol", "timestamp", "date", "time", "boolean", "status", "severity", "risk_score",
    "cve", "vulnerability_id", "hash", "file_path", "process_name", "command_line", "user_agent",
    "country", "region", "city", "department", "organizational_unit", "role", "mfa_status",
    "account_status", "password", "credential", "asset_id", "device_id", "event_id", "source",
    "category", "numeric_measure", "free_text", "generic_identifier", "unknown",
)


class SemanticUnderstandingError(Exception):
    """Contexto incompatível ou interpretação inválida; nenhum resultado parcial."""


@dataclass(frozen=True)
class ColumnUnderstanding:
    name: str
    semantic_type: str
    semantic_role: str | None
    confidence: float
    is_identifier: bool


@dataclass(frozen=True)
class DatasetUnderstanding:
    """Confiança declarada pelo modelo, não probabilidade estatística calibrada."""

    dataset_path: Path
    dataset_name: str
    dataset_category: str
    dataset_type: str
    confidence: float
    summary: str
    columns: tuple[ColumnUnderstanding, ...]
