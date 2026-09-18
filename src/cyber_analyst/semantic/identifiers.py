"""Política central por tipo; tipos contextuais preservam a decisão da IA."""

REFERENCE_TYPES = frozenset({
    "email", "username", "user_id", "account_id", "ip_address", "hostname", "domain",
    "cve", "vulnerability_id", "hash", "asset_id", "device_id", "event_id", "generic_identifier",
})
NON_REFERENCE_TYPES = frozenset({
    "timestamp", "date", "time", "severity", "status", "boolean", "risk_score",
    "numeric_measure", "free_text",
})


def resolve_identifier(semantic_type: str, inferred: bool) -> bool:
    if semantic_type in REFERENCE_TYPES:
        return True
    if semantic_type in NON_REFERENCE_TYPES:
        return False
    return inferred
