"""Bounded read tools over completed context; no source or engine access."""
from dataclasses import asdict, replace
from datetime import date, datetime, time
from decimal import Decimal
import math
from cyber_analyst.context.view import ViewService
from cyber_analyst.context.search import SearchService
from .tool_models import ToolRequest, ToolResult, ToolValidationError, TOOL_REGISTRY, LIMITS



def bounded(values, limit):
    values = tuple(values)
    return {'total_count': len(values), 'included_count': min(len(values),limit),
            'truncated': len(values)>limit, 'items': list(values[:limit])}


def value(item):
    if isinstance(item, (datetime,date,time)):
        return item.isoformat()
    if isinstance(item, Decimal) or isinstance(item,float) and not math.isfinite(item):
        return str(item)
    if isinstance(item,str) and len(item)>LIMITS['text']:
        return dict(text=item[:LIMITS['text']],total_count=len(item),included_count=LIMITS['text'],truncated=True)
    if isinstance(item,dict):
        return {key:value(v) for key,v in item.items()}
    if isinstance(item,(list,tuple)):
        result=bounded(item,LIMITS['columns'])
        result['items']=[value(v) for v in result['items']]
        return result
    return item


def collection(items, limit):
    result=bounded(items,limit)
    result['items']=[value(i) for i in result['items']]
    return result


def table(columns, rows):
    return dict(columns=collection(columns,LIMITS['columns']),rows=collection(rows,LIMITS['rows']))


class InvestigationToolService:
    @staticmethod
    def definitions():
        return tuple(d.to_dict() for d in TOOL_REGISTRY.values())

    def execute(self, request, context, state, view):
        if not isinstance(request,ToolRequest):
            raise ToolValidationError('Expected ToolRequest')
        # Revalidate defensively and reject stale or forged views.
        request=ToolRequest(request.tool_name, request.arguments)
        try:
            if ViewService().build(context,state)!=view:
                raise ValueError('View does not match state')
        except (ValueError,KeyError) as exc:
            raise ToolValidationError('Context/state/view mismatch') from exc
        name,args=request.tool_name,request.arguments
        def denied():
            return ToolResult(name,args,'error',{},'not_visible_or_unknown')
        names=set(view.dataset_names)
        def evidence_visible(e):
            if e.dataset_name not in names:
                return False
            if e.source_type == 'correlation':
                return e.source_id in view.correlation_ids
            if e.source_type == 'analysis':
                return (e.dataset_name, e.source_id) in view.analysis_ids
            return False
        if name=='get_entity':
            i=args['entity_id']
            if i not in view.entity_ids or i not in context.entities:return denied()
            e=context.entities[i]
            relations=sorted(r for r in e.relation_ids if r in view.relation_ids)
            neighbors=sorted({endpoint for r in relations for endpoint in
                (context.relations[r].entity_a_id,context.relations[r].entity_b_id)
                if endpoint!=i and endpoint in view.entity_ids})
            occurrences=sorted((o for o in e.occurrences if o.dataset_name in names),key=lambda o:(o.dataset_name,o.column_name,o.semantic_type,o.semantic_role or '',o.value,o.row_count))
            payload=dict(entity_id=i,canonical_value=value(e.canonical_value),entity_type=e.entity_type,
                occurrences=collection([asdict(o) for o in occurrences],LIMITS['occurrences']),
                relation_ids=collection(relations,LIMITS['references']),neighbor_ids=collection(neighbors,LIMITS['references']),
                dataset_names=collection(sorted(set(e.dataset_names)&names),LIMITS['references']))
        elif name=='get_relation':
            i=args['relation_id']
            if i not in view.relation_ids or i not in context.relations:return denied()
            r=context.relations[i]
            if r.entity_a_id not in view.entity_ids or r.entity_b_id not in view.entity_ids:return denied()
            endpoints=[dict(entity_id=eid,canonical_value=value(context.entities[eid].canonical_value),entity_type=context.entities[eid].entity_type) for eid in (r.entity_a_id,r.entity_b_id)]
            occurrences=sorted((asdict(o) for o in r.occurrences if o.dataset_name in names),key=lambda o:tuple(str(o[k]) for k in sorted(o)))
            payload=dict(relation_id=i,relation_type=r.relation_type,entity_a=endpoints[0],entity_b=endpoints[1],occurrences=collection(occurrences,LIMITS['occurrences']))
        elif name=='get_correlation':
            i=args['correlation_id']
            if i not in view.correlation_ids or i not in context.correlations:return denied()
            r=context.correlations[i]
            if not {r.left_dataset,r.right_dataset}<=names:return denied()
            payload=dict(correlation_id=i,left_dataset=value(r.left_dataset),right_dataset=value(r.right_dataset),
                         left_column=value(r.left_column),right_column=value(r.right_column),metrics=asdict(r.correlation_result.summary),
                         preview=table(r.correlation_result.preview_columns,r.correlation_result.preview_rows))
        elif name=='get_finding':
            i=args['finding_id']
            if i not in view.finding_ids or i not in context.findings:return denied()
            f=context.findings[i]
            evidence=[context.evidence[e] for e in sorted(f.evidence_ids) if evidence_visible(context.evidence[e])]
            payload=dict(finding_id=i,attention_level=f.attention_level,
                         evidence_ids=collection([e.evidence_id for e in evidence],LIMITS['evidence']),
                         evidence=collection([asdict(e) for e in evidence],LIMITS['evidence']))
        elif name=='get_analysis':
            key=(args['dataset_name'],args['analysis_id'])
            if key not in view.analysis_ids or key not in context.analyses:return denied()
            a=context.analyses[key]
            payload=dict(dataset_name=value(key[0]),analysis_id=key[1],operation=a.operation,title=value(a.title),**table(a.columns,a.rows))
        elif name=='get_dataset':
            i=args['dataset_name']
            if i not in names or i not in context.datasets:return denied()
            d=context.datasets[i]
            payload=dict(dataset_name=value(i),entity_ids=collection(sorted(set(d.entity_ids)&set(view.entity_ids)),LIMITS['references']),
                         relation_ids=collection(sorted(set(d.relation_ids)&set(view.relation_ids)),LIMITS['references']),
                         finding_ids=collection(sorted(set(d.finding_ids)&set(view.finding_ids)),LIMITS['references']),
                         analysis_ids=collection(sorted(a for a in d.analysis_result_ids if (i,a) in view.analysis_ids),LIMITS['references']))
        else:
            # Search owns matching/ranking. Filter nested provenance before delegation.
            findings={i:replace(f,evidence_ids=tuple(e for e in f.evidence_ids if evidence_visible(context.evidence[e]))) for i,f in context.findings.items() if i in view.finding_ids}
            scoped=replace(context,findings=findings)
            possible=len(view.entity_ids)+len(view.dataset_names)+len(view.finding_ids)+len(view.analysis_ids)
            matches=SearchService().search(scoped,view,args['query'],max(1,possible))
            payload=dict(results=collection([asdict(r) for r in matches],args['limit']))
        return ToolResult(name,args,'success',payload)
