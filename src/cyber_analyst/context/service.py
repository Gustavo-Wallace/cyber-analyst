"""Build indexes without loading data, calculating metrics or traversing graphs."""
from cyber_analyst.investigation.models import InvestigationResult
from .models import EntityContext, DatasetContext, InvestigationContext


class ContextError(ValueError):
    """The supplied investigation contains inconsistent references."""


def _index(items, key, label):
    result = {}
    for item in items:
        identifier = key(item)
        if identifier in result:
            raise ContextError(f'Duplicate {label}: {identifier}')
        result[identifier] = item
    return result


class ContextService:
    def build(self, result: InvestigationResult) -> InvestigationContext:
        if result.findings is None:
            raise ContextError('Completed investigation requires findings')
        datasets = _index(result.datasets,lambda d:d.dataset.name,'dataset name')
        entities = _index(result.entities.entities,lambda e:e.entity_id,'entity ID')
        relations = _index(result.relations.relations,lambda r:r.relation_id,'relation ID')
        findings = _index(result.findings.findings,lambda f:f.finding_id,'finding ID')
        evidence = _index(result.findings.evidence,lambda e:e.evidence_id,'evidence ID')
        ds_entities = {n:set() for n in datasets}
        ds_relations = {n:set() for n in datasets}
        ds_findings = {n:set() for n in datasets}
        entity_relations = {i:set() for i in entities}
        neighbors = {i:set() for i in entities}
        entity_datasets = {i:set() for i in entities}
        def check_dataset(name):
            if name not in datasets:
                raise ContextError(f'Unknown source dataset: {name}')
        for identifier, entity in entities.items():
            for occurrence in entity.occurrences:
                check_dataset(occurrence.dataset_name)
                ds_entities[occurrence.dataset_name].add(identifier)
                entity_datasets[identifier].add(occurrence.dataset_name)
        for identifier, relation in relations.items():
            a,b = relation.entity_a_id,relation.entity_b_id
            if a not in entities or b not in entities:
                raise ContextError(f'Unknown relation endpoint: {identifier}')
            if a == b:
                raise ContextError(f'Self relation: {identifier}')
            entity_relations[a].add(identifier); entity_relations[b].add(identifier)
            neighbors[a].add(b); neighbors[b].add(a)
            for occurrence in relation.occurrences:
                check_dataset(occurrence.dataset_name)
                ds_relations[occurrence.dataset_name].add(identifier)
                entity_datasets[a].add(occurrence.dataset_name)
                entity_datasets[b].add(occurrence.dataset_name)
        for item in evidence.values():
            check_dataset(item.dataset_name)
        for identifier, finding in findings.items():
            if len(set(finding.evidence_ids)) != len(finding.evidence_ids):
                raise ContextError(f'Duplicate evidence reference: {identifier}')
            for reference in finding.evidence_ids:
                if reference not in evidence:
                    raise ContextError(f'Unknown finding evidence: {reference}')
                ds_findings[evidence[reference].dataset_name].add(identifier)
        dataset_contexts = {}
        analysis_index = {}
        for name,dataset in datasets.items():
            execution = dataset.analysis_execution
            if execution.dataset_name != name:
                raise ContextError(f'Analysis dataset mismatch: {name}')
            analyses = _index(execution.results,lambda s:s.step_id,'analysis step ID')
            analysis_index.update({(name,i):step for i,step in analyses.items()})
            dataset_contexts[name] = DatasetContext(name,tuple(sorted(ds_entities[name])),
                tuple(sorted(ds_relations[name])),tuple(sorted(ds_findings[name])),tuple(sorted(analyses)))
        entity_contexts = {i:EntityContext(i,e.entity_type,e.canonical_value,
            tuple(sorted(e.occurrences,key=lambda o:(o.dataset_name,o.column_name,o.semantic_type,
                o.semantic_role is not None,o.semantic_role or '',o.value,o.row_count))),
            tuple(sorted(entity_relations[i])),tuple(sorted(neighbors[i])),tuple(sorted(entity_datasets[i])))
            for i,e in entities.items()}
        return InvestigationContext(entity_contexts,dataset_contexts,relations,findings,evidence,analysis_index)
