"""Factual same-row relations; Python processes aggregated raw pairs only."""
from hashlib import sha256
from itertools import combinations
import json
import polars as pl

from cyber_analyst.entities.normalization import SUPPORTED_TYPES, canonical_value
from .models import Relation, RelationOccurrence, RelationResult


class RelationService:
    def extract(self, *, datasets, understandings, entities) -> RelationResult:
        datasets, understandings = tuple(datasets), tuple(understandings)
        by_name = {d.name:d for d in datasets}
        semantics = {u.dataset_name:u for u in understandings}
        if len(by_name) != len(datasets):
            raise ValueError('Relation extraction: duplicate dataset names')
        if len(semantics) != len(understandings):
            raise ValueError('Relation extraction: duplicate understanding names')
        if set(by_name) != set(semantics):
            raise ValueError(f'Relation extraction: missing understandings {sorted(set(by_name)-set(semantics))}; unexpected understandings {sorted(set(semantics)-set(by_name))}')
        lookup = {(e.entity_type,e.canonical_value):e.entity_id for e in entities.entities}
        merged = {}
        for name in sorted(by_name):
            dataset, understanding = by_name[name], semantics[name]
            names = [c.name for c in understanding.columns]
            if (understanding.dataset_path != dataset.path or len(names) != len(set(names))
                    or set(names) != set(dataset.columns) or dataset.lazy_frame.collect_schema() != dataset.schema):
                raise ValueError(f'Relation extraction: incompatible understanding/schema: {name}')
            columns = sorted((c for c in understanding.columns if c.semantic_type in SUPPORTED_TYPES), key=lambda c:c.name)
            for left, right in combinations(columns, 2):
                try:
                    counts = (dataset.lazy_frame.select(pl.col(left.name).cast(pl.String).alias('a'),
                                                       pl.col(right.name).cast(pl.String).alias('b'))
                              .filter(pl.col('a').is_not_null() & pl.col('b').is_not_null())
                              .group_by('a','b').agg(pl.len().cast(pl.UInt64).alias('count')).collect())
                    # Never iterate source rows: these are distinct raw-pair aggregates.
                    for raw_a, raw_b, count in counts.iter_rows():
                        a = lookup.get((left.semantic_type,canonical_value(raw_a,left.semantic_type)))
                        b = lookup.get((right.semantic_type,canonical_value(raw_b,right.semantic_type)))
                        if a is None or b is None or a == b:
                            continue
                        ca, cb = left, right
                        if a > b:
                            a, b, ca, cb = b, a, right, left
                        context = (name,ca.name,cb.name,ca.semantic_role,cb.semantic_role)
                        occurrences = merged.setdefault((a,b),{})
                        occurrences[context] = occurrences.get(context,0) + count
                except Exception as exc:
                    raise ValueError(f'Relation extraction failed: {name} ({left.name}, {right.name})') from exc
        result = []
        for (a,b), occurrences in sorted(merged.items()):
            identity = json.dumps(['co_occurrence',a,b],ensure_ascii=False,separators=(',',':'))
            result.append(Relation('relation_'+sha256(identity.encode('utf-8')).hexdigest(),
                'co_occurrence',a,b,tuple(RelationOccurrence(*context,count) for context,count in
                    sorted(occurrences.items(),key=lambda item:item[0][:3]))))
        return RelationResult(tuple(result))
