"""Aggregate full-data values before normalizing distinct identifiers in Python."""
from hashlib import sha256
import json

import polars as pl

from .models import Entity, EntityOccurrence, EntityResult

from .normalization import SUPPORTED_TYPES, canonical_value


class EntityService:
    def extract(self, *, datasets, understandings) -> EntityResult:
        datasets, understandings = tuple(datasets), tuple(understandings)
        by_name = {d.name: d for d in datasets}
        semantic_by_name = {u.dataset_name: u for u in understandings}
        if len(by_name) != len(datasets):
            raise ValueError('Entity extraction: duplicate dataset names')
        if len(semantic_by_name) != len(understandings):
            raise ValueError('Entity extraction: duplicate understanding dataset names')
        missing = sorted(set(by_name) - set(semantic_by_name))
        unexpected = sorted(set(semantic_by_name) - set(by_name))
        if missing or unexpected:
            raise ValueError(f'Entity extraction: missing understandings {missing}; unexpected understandings {unexpected}')
        pairs = tuple((by_name[name], semantic_by_name[name]) for name in sorted(by_name))
        for dataset, understanding in pairs:
            names = [c.name for c in understanding.columns]
            if (understanding.dataset_name != dataset.name or understanding.dataset_path != dataset.path
                    or len(names) != len(set(names)) or set(names) != set(dataset.columns)
                    or dataset.lazy_frame.collect_schema() != dataset.schema):
                raise ValueError(f'Incompatible understanding/schema: {dataset.name}')
        entities = {}
        for dataset, understanding in pairs:
            for column in understanding.columns:
                kind = column.semantic_type
                if kind not in SUPPORTED_TYPES:
                    continue
                try:
                    # Python visits only distinct aggregated values, never source rows.
                    counts = (dataset.lazy_frame.select(pl.col(column.name).cast(pl.String).alias('raw'))
                              .filter(pl.col('raw').is_not_null())
                              .group_by('raw').agg(pl.len().cast(pl.UInt64).alias('row_count')).collect())
                    canonical = [canonical_value(value, kind) for value in counts['raw'].to_list()]
                    normalized = (counts.with_columns(pl.Series('value', canonical, dtype=pl.String))
                                  .filter(pl.col('value').is_not_null())
                                  .group_by('value').agg(pl.col('row_count').sum()).sort('value'))
                    for value, count in normalized.select('value', 'row_count').iter_rows():
                        occurrence = EntityOccurrence(dataset.name, column.name, kind,
                                                      column.semantic_role, value, count)
                        entities.setdefault((kind, value), []).append(occurrence)
                except Exception as exc:
                    raise ValueError(f'Entity extraction failed: {dataset.name}.{column.name} ({kind})') from exc
        result = []
        for (kind, value), occurrences in sorted(entities.items()):
            identity = json.dumps([kind, value], ensure_ascii=False, separators=(',', ':'))
            result.append(Entity('entity_' + sha256(identity.encode('utf-8')).hexdigest(), kind, value,
                                 tuple(sorted(occurrences, key=lambda o: (o.dataset_name, o.column_name)))))
        return EntityResult(tuple(result))
