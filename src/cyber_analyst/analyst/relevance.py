"""Exact object identity matching; no semantic or keyword inference."""
import json
import re
from dataclasses import dataclass
from .models import AnalystReference


@dataclass(frozen=True)
class Subject:
    reference: AnalystReference | None
    visible: bool


def explicit_subject(question, context, view):
    identities = []
    for kind, objects in (('entity', context.entities), ('dataset', context.datasets),
                          ('analysis', context.analyses), ('correlation', context.correlations),
                          ('finding', context.findings), ('relation', context.relations)):
        for key, obj in objects.items():
            ref = AnalystReference(kind, key[1] if kind == 'analysis' else key,
                                   key[0] if kind == 'analysis' else None)
            values = [ref.target_id]
            if kind == 'entity':
                values.append(obj.canonical_value)
            for value in values:
                if not value:
                    continue
                for match in re.finditer(r'(?<![\w@.\-])' + re.escape(value) + r'(?![\w@.\-])', question):
                    identities.append((match.span(), ref))
    # A longer exact value owns its text: "ana" is not a second subject in an email.
    matches = {ref for span, ref in identities if not any(
        other[0] <= span[0] and other[1] >= span[1] and other != span
        for other, _ in identities)}
    non_datasets = {r for r in matches if r.kind != 'dataset'}
    # An explicit dataset qualifier disambiguates a composite analysis identity.
    datasets = {r.target_id for r in matches if r.kind == 'dataset'}
    if non_datasets and all(r.kind == 'analysis' for r in non_datasets) and len(datasets) == 1:
        non_datasets = {r for r in non_datasets if r.dataset_name in datasets}
        matches = non_datasets
    if len(matches) != 1:
        # A quoted unknown identity is unavailable, without an existence disclosure.
        if not matches and re.search(r'"[^"\n]+"', question):
            return Subject(None, False)
        return None
    ref = next(iter(matches))
    visible = {'entity': view.entity_ids, 'dataset': view.dataset_names,
               'analysis': view.analysis_ids, 'correlation': view.correlation_ids,
               'finding': view.finding_ids, 'relation': view.relation_ids}[ref.kind]
    key = (ref.dataset_name, ref.target_id) if ref.kind == 'analysis' else ref.target_id
    return Subject(ref, key in visible)


def supports(item, subject):
    if subject is None:
        return True
    ref = subject.reference
    if ref is None:
        return False
    if any(f.reference == ref for f in item.facts):
        return True
    if ref.kind == 'dataset':
        content = json.loads(item.content_json)
        return content.get('dataset_name', content.get('dataset')) == ref.target_id
    return False


def guarded_selection(selection, by_alias, subject):
    if subject is not None and selection['status'] == 'supported' and not all(
            supports(by_alias[a], subject) for a in selection['fact_aliases']):
        return {'status': 'insufficient', 'fact_aliases': []}
    return selection
