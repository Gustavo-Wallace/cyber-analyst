"""Evidência de formato restrita aos samples; não classifica datasets."""

from dataclasses import dataclass
from ipaddress import ip_address
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SemanticEvidence:
    semantic_type: str
    confidence: float
    source: str
    description: str


def _ip(value):
    try:
        ip_address(value)
        return "%" not in value
    except ValueError:
        return False


def _host(value):
    return bool(value and len(value) <= 253 and all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
        for part in value.split(".")
    ))


def _email(value):
    if len(value) > 254 or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    return bool(len(local) <= 64 and re.fullmatch(r"[A-Za-z0-9_+%-]+(?:\.[A-Za-z0-9_+%-]+)*", local)
                and "." in domain and _host(domain) and domain.rsplit(".", 1)[1].isalpha())


def _url(value):
    if any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        return bool(parsed.scheme.lower() in ("http", "https") and host
                    and (_ip(host) or _host(host)) and parsed.username is None
                    and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def detect_evidence(samples, *, truncated=False) -> tuple[SemanticEvidence, ...]:
    """Exige >=2 valores distintos, não nulos, completos e 100% concordantes.

    confidence=1 refere-se apenas à concordância de formato desta amostra.
    Amostras mistas, truncadas ou escassas não geram evidência.
    """
    values = [value for value in samples if value is not None]
    if truncated or not values or any(not isinstance(value, str) for value in values):
        return ()
    values = set(values)
    if len(values) < 2:
        return ()
    detectors = {
        "ip_address": _ip,
        "email": _email,
        "cve": lambda value: bool(re.fullmatch(r"CVE-[0-9]{4}-[0-9]{4,}", value, re.IGNORECASE)),
        "url": _url,
        "hash": lambda value: len(value) in (32, 40, 64, 128) and bool(re.fullmatch(r"[0-9a-fA-F]+", value)),
    }
    return tuple(SemanticEvidence(kind, 1.0, "value_pattern",
                                 f"All {len(values)} distinct non-null samples match {kind} format; not a whole-column guarantee.")
                 for kind, detector in detectors.items() if all(detector(value) for value in values))
