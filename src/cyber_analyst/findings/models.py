from dataclasses import dataclass


class FindingError(Exception):
    """Invalid evidence, structured response or grounding; no partial result."""


@dataclass(frozen=True)
class FindingEvidence:
    evidence_id: str
    dataset_name: str
    source_type: str
    source_id: str
    operation: str
    payload: str  # Canonical JSON object text: immutable, decoded only for transport.


@dataclass(frozen=True)
class Finding:
    finding_id: str
    attention_level: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FindingResult:
    findings: tuple[Finding, ...]
    evidence: tuple[FindingEvidence, ...] = ()

    def evidence_for(self, finding_id: str) -> tuple[FindingEvidence, ...]:
        """Return original catalog objects in reference order; no factual rewriting."""
        finding = next((item for item in self.findings if item.finding_id == finding_id), None)
        if finding is None:
            raise KeyError(finding_id)
        by_id = {item.evidence_id: item for item in self.evidence}
        return tuple(by_id[identifier] for identifier in finding.evidence_ids)
