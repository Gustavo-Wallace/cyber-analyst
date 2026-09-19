"""Full-data lazy aggregates. Nulls are counted as a distinct value/group.

Frequencies sort by count descending then keys ascending (null last).
Daily series sort by day then group ascending (null last). Missing limits use
the catalog's safe maximum. Only bounded results are converted row by row.
"""
from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
import math

import polars as pl
from jsonschema import validate

from cyber_analyst.planning.contracts import CONTRACTS, LIMIT_MAX, response_schema, step_schema
from cyber_analyst.execution.models import AnalysisExecutionError, AnalysisExecutionResult, AnalysisStepResult


def _primitive(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)  # Preserve decimal precision.
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # Preserve NaN/Infinity explicitly, without invalid JSON.
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"Unsupported result type: {type(value).__name__}")


def _wire(step):
    contract = CONTRACTS[step.operation]
    item = asdict(step)
    item['columns'] = list(step.columns)
    item['group_by'] = list(step.group_by)
    allowed = step_schema(step.operation, contract)['properties']
    for key in ('columns', 'group_by', 'time_column', 'limit'):
        if key not in allowed:
            if item[key] not in (None, []):
                raise ValueError(f"Parameter {key} is not allowed")
            del item[key]
    validate(item, step_schema(step.operation, contract))
    return item


class AnalysisExecutionService:
    def execute(self, *, dataset, plan) -> AnalysisExecutionResult:
        try:
            if plan.dataset_name != dataset.name:
                raise ValueError('Dataset mismatch')
            wire = []
            schema = dataset.lazy_frame.collect_schema()
            signatures = set()
            ids = set()
            for step in plan.steps:
                try:
                    wire.append(_wire(step))
                    if step.id in ids:
                        raise ValueError('Duplicate step ID')
                    ids.add(step.id)
                    names = [*step.columns, *step.group_by]
                    if step.time_column is not None:
                        names.append(step.time_column)
                    if any(name not in schema for name in names):
                        raise ValueError('Referenced column does not exist')
                    contract = CONTRACTS[step.operation]
                    if contract.numeric and any(not schema[name].is_numeric() for name in step.columns):
                        raise ValueError('Numeric columns required')
                    if contract.temporal:
                        if step.time_column in step.group_by:
                            raise ValueError('Time column cannot be a grouping column')
                        if schema[step.time_column].base_type() not in (pl.Date, pl.Datetime, pl.String):
                            raise ValueError('Temporal column required')
                    signature = (step.operation, tuple(sorted(step.columns)), tuple(sorted(step.group_by)), step.time_column)
                    if signature in signatures:
                        raise ValueError('Redundant step')
                    signatures.add(signature)
                except Exception as exc:
                    raise AnalysisExecutionError(step.id, step.operation, str(exc)) from exc
            validate({'dataset_name': plan.dataset_name, 'summary': plan.summary, 'steps': wire}, response_schema())
        except AnalysisExecutionError:
            raise
        except Exception as exc:
            raise AnalysisExecutionError(None, 'plan', str(exc)) from exc
        results = []
        for step in plan.steps:
            try:
                headers, rows = self._execute_step(dataset.lazy_frame, schema, step)
                results.append(AnalysisStepResult(step.id, step.operation, step.title, tuple(headers),
                                                 tuple(tuple(_primitive(v) for v in row) for row in rows)))
            except Exception as exc:
                raise AnalysisExecutionError(step.id, step.operation, str(exc)) from exc
        return AnalysisExecutionResult(dataset.name, tuple(results))

    def _execute_step(self, frame, schema, step):
        op = step.operation
        if op in ('null_analysis', 'unique_count', 'numeric_summary'):
            expressions = []
            for index, name in enumerate(step.columns):
                column = pl.col(name)
                if op == 'null_analysis':
                    values = [column.null_count(), pl.when(pl.len() > 0).then(column.null_count() * 100.0 / pl.len()).otherwise(0.0)]
                elif op == 'unique_count':
                    values = [column.n_unique()]
                else:
                    values = [column.count(), column.null_count(), column.min(), column.max(), column.mean(), column.median(), column.std(ddof=1)]
                expressions.extend(expr.alias(f'v{index}_{j}') for j, expr in enumerate(values))
            values = frame.select(expressions).collect(engine='streaming').row(0)
            metrics = {'null_analysis': ('null_count', 'null_percentage'), 'unique_count': ('unique_count',),
                       'numeric_summary': ('count', 'null_count', 'minimum', 'maximum', 'mean', 'median', 'std')}[op]
            width = len(metrics)
            return ('column', *metrics), [(name, *values[i*width:(i+1)*width]) for i, name in enumerate(step.columns)]

        temporal = CONTRACTS[op].temporal
        names = list(step.group_by if op == 'group_count' else step.columns)
        if temporal:
            names = [step.time_column, *step.group_by]
        # Internal names avoid collisions with source columns named count/day/etc.
        keys = [f'k{i}' for i in range(len(names))]
        selected = frame.select(pl.col(name).alias(key) for name, key in zip(names, keys))
        if temporal:
            dtype = schema[step.time_column]
            if dtype == pl.String:
                # Explicit ISO date / naive ISO timestamp only. No ambiguous locale inference.
                value = pl.col('k0')
                parsed = pl.coalesce(
                    value.str.strptime(pl.Date, '%Y-%m-%d', strict=False),
                    value.str.strptime(pl.Datetime, '%Y-%m-%dT%H:%M:%S%.f', strict=False).dt.date(),
                    value.str.strptime(pl.Datetime, '%Y-%m-%d %H:%M:%S%.f', strict=False).dt.date(),
                )
                selected = selected.with_columns(parsed.alias('_day'))
                check = selected.select(
                    (pl.col('k0').is_not_null() & pl.col('_day').is_null()).sum().alias('invalid'),
                    pl.col('_day').count().alias('valid')).collect(engine='streaming').row(0)
                if check[0] or not check[1]:
                    raise ValueError('No usable temporal series or unparseable non-null temporal values')
                selected = selected.drop('k0').rename({'_day': 'k0'})
            else:
                selected = selected.with_columns(pl.col('k0').cast(pl.Date))
        result = selected.group_by(keys).agg(pl.len().alias('_count'))
        if temporal:
            result = result.sort(keys, nulls_last=True)
        else:
            result = result.sort(['_count', *keys], descending=[True, *([False]*len(keys))], nulls_last=True)
        result = result.select(*keys, '_count').limit(step.limit if step.limit is not None else LIMIT_MAX).collect(engine='streaming')
        # Output uses positional columns/rows, allowing a source dimension named count.
        return (*(['day', *step.group_by] if temporal else names), 'count'), result.rows()
