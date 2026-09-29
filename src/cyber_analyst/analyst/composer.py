"""Deterministic bilingual presentation of compiled facts, never inference."""
import json
from .facts import encode
from .models import AnalystObservation, AnalystResponse

LIMITATIONS = {
    'bounded_evidence': ('Only the supplied bounded evidence is represented.', 'Somente as evidências limitadas fornecidas estão representadas.'),
    'no_causation': ('Correlation does not establish causation.', 'Correlação não estabelece causalidade.'),
    'no_attribution': ('No attacker attribution is established by this answer.', 'Esta resposta não estabelece atribuição a um atacante.'),
    'no_absence_inference': ('Missing evidence does not establish absence.', 'A falta de evidências não estabelece ausência.'),
}
METRICS = {
    'common_keys': ('common keys', 'chaves em comum'),
    'matched_rows': ('matched rows', 'linhas correspondentes'),
    'left_only_keys': ('left-only keys', 'chaves exclusivas à esquerda'),
    'right_only_keys': ('right-only keys', 'chaves exclusivas à direita'),
    'left_rows': ('left rows', 'linhas à esquerda'),
    'right_rows': ('right rows', 'linhas à direita'),
    'left_unique_keys': ('left unique keys', 'chaves distintas à esquerda'),
    'right_unique_keys': ('right unique keys', 'chaves distintas à direita'),
}


def validate_plan(plan, selected):
    if not 1 <= len(plan['sections']) <= 4:
        raise ValueError('Use one to four sections')
    flags = plan['limitations']
    if (not isinstance(flags, dict) or set(flags) != set(LIMITATIONS)
            or any(type(value) is not bool for value in flags.values())):
        raise ValueError('Provide all controlled limitation flags as booleans')
    aliases = [a for section in plan['sections'] for a in section]
    if not 1 <= len(aliases) <= 8 or len(set(aliases)) != len(aliases):
        raise ValueError('Use one to eight aliases without repetition across sections')
    known = {i.alias: i for i in selected}
    if not set(aliases) <= known.keys():
        raise ValueError('Unknown or unselected alias')
    required = {i.alias for i in selected if (d := json.loads(i.content_json)).get('is_focus')
                and d['kind'] == 'correlation_metric'
                and d['metric'] in ('common_keys', 'matched_rows', 'left_only_keys', 'right_only_keys')}
    if not required <= set(aliases):
        raise ValueError('Include all selected focused correlation core metrics')


def render(item, language):
    d = json.loads(item.content_json)
    pt = language == 'pt-BR'
    if language not in ('en', 'pt-BR'):
        raise ValueError('Unsupported response language')
    q = encode  # Quote dataset-derived strings as data, including embedded controls.
    kind = d['kind']
    if kind == 'entity_identity':
        value, entity_type = q(d['canonical_value']), q(d['entity_type'])
        return (f'{value} é representado como uma entidade do tipo {entity_type}.' if pt
                else f'{value} is represented as a {entity_type} entity.')
    if kind == 'entity_occurrence':
        value, dataset, column, count = q(d['subject']), q(d['dataset_name']), q(d['column_name']), q(d['row_count'])
        return (f'{value} aparece em {dataset}, na coluna {column}; linhas registradas: {count}.' if pt
                else f'{value} appears in {dataset}, column {column}; recorded rows: {count}.')
    if kind == 'entity_dataset':
        return (f'Entidade {q(d["subject"])}; dataset: {q(d["dataset"])}.' if pt
                else f'Entity {q(d["subject"])}; dataset: {q(d["dataset"])}.')
    if kind in ('correlation_metric', 'correlation_preview_row'):
        subject = d['subject']
        endpoint = (f'{q(subject["left_dataset"])}.{q(subject["left_column"])} ↔ '
                    f'{q(subject["right_dataset"])}.{q(subject["right_column"])}')
        prefix = 'Correlação' if pt else 'Correlation'
        if kind == 'correlation_metric':
            label = METRICS[d['metric']][int(pt)]
            return f'{prefix} {endpoint}; {label}: {q(d["value"])}.'
        return f'{prefix} {endpoint}; ' + ('colunas' if pt else 'columns') + f': {q(d["columns"])}; ' + ('linha de preview' if pt else 'preview row') + f': {q(d["row"])}.'
    if kind == 'finding_evidence':
        # Payload is original deterministic JSON, not a paraphrase of its values.
        return (('Evidência' if pt else 'Evidence') + f'; dataset: {q(d.get("dataset_name"))}; '
                + ('tipo de fonte' if pt else 'source type') + f': {q(d.get("source_type"))}; '
                + ('operação' if pt else 'operation') + f': {q(d.get("operation"))}; '
                + ('atenção' if pt else 'attention') + f': {q(d.get("attention_level"))}; payload: {q(d.get("payload"))}.')
    if kind in ('analysis_metadata', 'analysis_result_row'):
        text = (('Análise' if pt else 'Analysis') + f'; dataset: {q(d.get("dataset_name"))}; '
                + ('operação' if pt else 'operation') + f': {q(d.get("operation"))}; '
                + ('título' if pt else 'title') + f': {q(d.get("title"))}; '
                + ('colunas' if pt else 'columns') + f': {q(d.get("columns"))}.')
        if kind == 'analysis_result_row':
            text += (' Linha: ' if pt else ' Row: ') + q(d['row'])
        return text
    if kind == 'relation_endpoints':
        return (('Relação registrada' if pt else 'Recorded relation') + f': {q(d["relation_type"])}; '
                + ('extremidades' if pt else 'endpoints') + f': {q(d["endpoints"])}.')
    if kind == 'relation_occurrence':
        return (('Ocorrência da relação' if pt else 'Relation occurrence') + f' {q(d["relation_type"])}: {q(d["occurrence"])}.')
    raise ValueError('Unsupported compiled evidence kind')


def compose(plan, selected, language):
    validate_plan(plan, selected)
    by_alias = {i.alias: i for i in selected}
    observations = []
    seen = set()
    for section in plan['sections']:
        for alias in section:
            item = by_alias[alias]
            ids = tuple(sorted({f.fact_id for f in item.facts}))
            if ids in seen:
                continue
            seen.add(ids)
            references = tuple(sorted({f.reference for f in item.facts}, key=lambda r: (r.kind, r.target_id, r.dataset_name or '')))
            observations.append(AnalystObservation(render(item, language), references, ids))
    limitations = tuple(LIMITATIONS[code][language == 'pt-BR'] for code in LIMITATIONS if plan['limitations'][code])
    return AnalystResponse('answered', 'Fatos observados' if language == 'pt-BR' else 'Observed facts', tuple(observations), limitations)
