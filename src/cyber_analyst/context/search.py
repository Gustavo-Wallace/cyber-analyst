"""Deterministic substring search of visible metadata only."""
from dataclasses import dataclass
from .models import InvestigationContext
from .view import InvestigationView

KINDS = ('entity','dataset','finding','analysis')


class SearchError(ValueError):
    """Invalid query, limit or view references."""


@dataclass(frozen=True)
class SearchResult:
    kind: str
    target_id: str
    label: str
    dataset_name: str | None
    matched_text: str

    def __post_init__(self):
        if self.kind not in KINDS:
            raise SearchError('Unknown search kind')


@dataclass(frozen=True)
class SearchResults:
    results: tuple[SearchResult, ...]

    def __post_init__(self):
        object.__setattr__(self,'results',tuple(self.results))

    def __iter__(self):
        return iter(self.results)

    def __len__(self):
        return len(self.results)

    def by_kind(self, kind: str) -> tuple[SearchResult, ...]:
        if kind not in KINDS:
            raise SearchError('Unknown search kind')
        return tuple(r for r in self.results if r.kind == kind)


class SearchService:
    def search(self, context: InvestigationContext, view: InvestigationView,
               query: str, limit: int = 50) -> SearchResults:
        if not isinstance(query,str) or not query.strip():
            raise SearchError('Query must be nonempty')
        if isinstance(limit,bool) or not isinstance(limit,int) or limit < 1:
            raise SearchError('Limit must be a positive integer')
        query = query.strip().casefold()
        names = set(view.dataset_names)
        if not names <= context.datasets.keys():
            raise SearchError('Unknown dataset in view')
        for identifiers,index,attribute in ((view.entity_ids,context.entities,'entity_ids'),
                                            (view.relation_ids,context.relations,'relation_ids'),
                                            (view.finding_ids,context.findings,'finding_ids')):
            allowed = {i for n in names for i in getattr(context.datasets[n],attribute)}
            if not set(identifiers) <= index.keys() or not set(identifiers) <= allowed:
                raise SearchError(f'Unknown or out-of-scope {attribute}')
        for i in view.relation_ids:
            relation = context.relations[i]
            if not {relation.entity_a_id,relation.entity_b_id} <= set(view.entity_ids):
                raise SearchError('Dangling relation in view')
        for pair in view.analysis_ids:
            if (len(pair)!=2 or pair[0] not in names or pair not in context.analyses
                    or pair[1] not in context.datasets[pair[0]].analysis_result_ids):
                raise SearchError('Unknown or out-of-scope analysis')
        matches=[]
        def add(kind,identifier,label,dataset,texts):
            hits=[text for text in texts if query in text.casefold()]
            if not hits:
                return
            matched=min(hits,key=lambda t:(t.casefold()!=query,t.casefold(),t))
            item=SearchResult(kind,identifier,label,dataset,matched)
            matches.append((matched.casefold()!=query,KINDS.index(kind),label.casefold(),identifier,dataset or '',item))
        for name in view.dataset_names:
            add('dataset',name,name,name,[name])
        for identifier in view.entity_ids:
            e=context.entities[identifier]
            add('entity',identifier,e.canonical_value,None,[e.canonical_value,e.entity_type])
        for identifier in view.finding_ids:
            f=context.findings[identifier]
            if any(i not in context.evidence for i in f.evidence_ids):
                raise SearchError('Unknown finding evidence')
            evidence=[context.evidence[i] for i in f.evidence_ids]
            sources=sorted({e.dataset_name for e in evidence})
            add('finding',identifier,identifier,sources[0] if len(sources)==1 else None,
                [identifier,f.attention_level,*[e.operation for e in evidence],*sources])
        for name,identifier in view.analysis_ids:
            step=context.analyses[(name,identifier)]
            add('analysis',identifier,step.title or identifier,name,
                [identifier,step.operation,step.title,name,*step.columns])
        return SearchResults(tuple(row[-1] for row in sorted(matches,key=lambda row:row[:-1])[:limit]))
