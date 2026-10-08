"""Small immutable display specs selected solely from visible, completed results.

No dataset access, engine calls or new analytical buckets/statistics. Numeric
histograms display existing exact-value frequencies, never reconstructed samples.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date
import json
import math
from cyber_analyst.analyst import AnalystReference
from .presentation_labels import human_label

MAX_VISUALS = 6
MAX_ANALYSIS_VISUALS = 3
MAX_CATEGORIES = 10
MAX_TIME_POINTS = 48
ATTENTION_ORDER = ('high', 'medium', 'low', 'informational')
FREQUENCY_OPERATIONS = ('column_distribution', 'top_values', 'group_count', 'cross_tab')


@dataclass(frozen=True)
class VisualTarget:
    page: str
    reference: AnalystReference | None = None
    filter_value: str | None = None


@dataclass(frozen=True)
class VisualPoint:
    label: str
    value: int | float
    color_key: str
    target: VisualTarget | None = None


@dataclass(frozen=True)
class VisualSeries:
    name: str
    points: tuple[VisualPoint, ...]


@dataclass(frozen=True)
class DashboardVisual:
    key: str
    kind: str
    title: str
    subtitle: str
    series: tuple[VisualSeries, ...]
    target: VisualTarget | None = None
    attention: bool = False


def category_text(value):
    if isinstance(value, (tuple, list)):
        return ' | '.join(category_text(v) for v in value)
    if value is None:
        return '(null)'
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _number(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def _chart_number(value):
    return _number(value) and abs(value) <= 2**53


def categorical_visual(key, title, subtitle, points, *, composition=True, attention=False, target=None):
    points = tuple(points)
    if not points:
        return None
    if any(not _number(p.value) or p.value < 0 for p in points):
        return None
    count = len(points)
    chartable = all(_chart_number(p.value) for p in points)
    kind = ('ranked_list' if count == 1 or not chartable or not any(p.value for p in points)
            else 'donut' if composition and 2 <= count <= 6 and sum(p.value > 0 for p in points) >= 2
            else 'horizontal_bar')
    if count > MAX_CATEGORIES:
        subtitle += f' Showing {MAX_CATEGORIES} of {count} returned categories; remaining categories are not displayed.'
    return DashboardVisual(key, kind, title, subtitle,
        (VisualSeries('Count', points[:MAX_CATEGORIES]),), target, attention)


def analysis_visual(dataset_name, step):
    """Interpret the result shape, not source values or inferred security meaning."""
    if not step.rows or not step.columns or any(len(r) != len(step.columns) for r in step.rows):
        return None
    target = VisualTarget('analyses', AnalystReference('analysis', step.step_id, dataset_name))
    key = 'analysis:' + dataset_name + ':' + step.step_id
    if step.operation in ('numeric_summary', 'unique_count', 'null_analysis'):
        if step.columns[0] != 'column':
            return None
        metrics = ('minimum', 'maximum', 'mean', 'median') if step.operation == 'numeric_summary' else (
            'null_count', 'null_percentage') if step.operation == 'null_analysis' else ('unique_count',)
        points = tuple(VisualPoint(human_label(str(row[0])) + ' | ' + human_label(metric), row[i], metric)
            for row in step.rows for i, metric in enumerate(step.columns)
            if metric in metrics and _number(row[i]))
        if not points:
            return None
        subtitle = dataset_name + ' | Executed statistics, unchanged.'
        if len(points) > 8:
            subtitle += f' Showing 8 of {len(points)} statistics; open the analysis for all values.'
        title = {'numeric_summary': 'Numeric summary', 'null_analysis': 'Missing values', 'unique_count': 'Distinct values'}[step.operation]
        return DashboardVisual(key, 'metrics', title, subtitle, (VisualSeries('Statistics', points[:8]),), target)
    if step.operation not in (*FREQUENCY_OPERATIONS, 'time_series_count') or len(step.columns) < 2 or step.columns[-1] != 'count':
        return None
    if any(not _chart_number(row[-1]) or row[-1] < 0 for row in step.rows):
        return None
    points = tuple(VisualPoint(category_text(row[:-1]), row[-1], category_text(row[:-1])) for row in step.rows)
    if len({p.label for p in points}) != len(points):
        return None  # Do not collapse distinct keys into ambiguous display categories.
    columns = ' | '.join(human_label(c) for c in step.columns[:-1])
    subtitle = dataset_name + ' | Executed aggregates; the source result may be limited.'
    if step.operation == 'time_series_count':
        if step.columns != ('day', 'count') or len(points) < 3:
            return None  # Sparse/grouped/ambiguous temporal rows stay in the explorer.
        try:
            days = tuple(date.fromisoformat(row[0]) for row in step.rows)
        except (ValueError, TypeError):
            return None
        if days != tuple(sorted(set(days))):
            return None
        if len(points) > MAX_TIME_POINTS:
            subtitle += f' Showing the first {MAX_TIME_POINTS} of {len(points)} returned days.'
        return DashboardVisual(key, 'line', 'Rows by day', subtitle,
            (VisualSeries('Rows', points[:MAX_TIME_POINTS]),), target)
    numeric = len(step.columns) == 2 and all(_chart_number(row[0]) for row in step.rows)
    if numeric and len(points) >= 6 and len(points) <= MAX_CATEGORIES:
        ordered = tuple(sorted(points, key=lambda p: float(p.label)))
        return DashboardVisual(key, 'histogram', columns + ' frequency',
            subtitle + ' Exact numeric values; no new bins or inferred samples.', (VisualSeries('Count', ordered),), target)
    if numeric and len(points) < 6:
        return DashboardVisual(key, 'metrics', columns + ' frequencies',
            subtitle + ' Too few distinct numeric values for a histogram.', (VisualSeries('Count', points),), target)
    title = ('Top ' + columns.lower() if step.operation == 'top_values' or len(points) > MAX_CATEGORIES
             else columns + (' combinations' if len(step.columns) > 2 else ' distribution'))
    ordered = tuple(sorted(points, key=lambda p: (-p.value, p.label.casefold(), p.label)))
    return categorical_visual(key, title, subtitle, ordered,
        composition=step.operation == 'column_distribution' and not numeric, target=target)


def select_visuals(context, view):
    """At most six panels: attention, identifiers, up to three analyses, matches,
    then dataset coverage if space remains. Frequency-equivalent scopes occur once.
    """
    visuals = []
    attention = Counter(context.findings[i].attention_level for i in view.finding_ids)
    item = categorical_visual('attention', 'Alert distribution', 'Investigation attention, not vulnerability severity.',
        (VisualPoint(level, attention[level], level, VisualTarget('findings', filter_value=level))
         for level in ATTENTION_ORDER if attention[level]), attention=True)
    if item:
        visuals.append(item)
    types = Counter(context.entities[i].entity_type for i in view.entity_ids)
    item = categorical_visual('identifier_types', 'Identifier types', 'Identifiers visible in the current view.',
        (VisualPoint(kind, count, kind, VisualTarget('entities', filter_value=kind))
         for kind, count in sorted(types.items(), key=lambda p: (-p[1], p[0]))))
    if item:
        visuals.append(item)
    operation_order = ('time_series_count', 'column_distribution', 'top_values', 'group_count',
                       'cross_tab', 'numeric_summary', 'null_analysis', 'unique_count')
    selected_scopes, per_dataset, selected_kinds = set(), Counter(), set()
    candidates = []
    for name, step_id in sorted(view.analysis_ids):
        step = context.analyses[name, step_id]
        family = 'frequency' if step.operation in FREQUENCY_OPERATIONS else step.operation
        scope = (name, family, tuple(sorted(step.columns[:-1])) if family == 'frequency' else
                 tuple(str(row[0]) for row in step.rows) if step.operation in ('numeric_summary', 'null_analysis', 'unique_count')
                 else step.columns)
        item = analysis_visual(name, step)
        if item:
            priority = {'line': 0, 'histogram': 1, 'donut': 2, 'horizontal_bar': 2,
                        'metrics': 3, 'ranked_list': 4}[item.kind]
            if item.kind == 'metrics' and step.operation in FREQUENCY_OPERATIONS:
                priority = 5  # Sparse numeric frequencies offer less than executed summary statistics.
            candidates.append((priority, operation_order.index(step.operation), name, step_id, scope, item))
    analysis_count = 0
    canonical = {}
    for candidate in sorted(candidates):
        canonical.setdefault(candidate[4], candidate)
    candidates = tuple(canonical.values())
    # Favor different useful result shapes before filling with another chart of
    # the same kind. This is presentation variety, not a security relevance score.
    for allow_repeated_kind in (False, True):
        for _, _, name, _, scope, item in sorted(candidates):
            if scope in selected_scopes or per_dataset[name] >= 2:
                continue
            if not allow_repeated_kind and item.kind in selected_kinds:
                continue
            visuals.append(item)
            selected_scopes.add(scope)
            selected_kinds.add(item.kind)
            per_dataset[name] += 1
            analysis_count += 1
            if analysis_count == MAX_ANALYSIS_VISUALS:
                break
        if analysis_count == MAX_ANALYSIS_VISUALS:
            break
    if view.correlation_ids and len(visuals) < MAX_VISUALS:
        matches = sorted(view.correlation_ids, key=lambda i: (
            -context.correlations[i].correlation_result.summary.common,
            -context.correlations[i].correlation_result.summary.matched_rows, i))
        points = tuple(VisualPoint(
            f'{context.correlations[i].left_dataset}.{context.correlations[i].left_column} <-> '
            f'{context.correlations[i].right_dataset}.{context.correlations[i].right_column}',
            context.correlations[i].correlation_result.summary.common, i,
            VisualTarget('correlations', AnalystReference('correlation', i))) for i in matches[:3])
        visuals.append(DashboardVisual('matches', 'ranked_list', 'Data matches',
            'Common keys in executed equality matches. Open a match for row counts and provenance.' +
            (f' Showing 3 of {len(matches)} matches.' if len(matches) > 3 else ''), (VisualSeries('Common keys', points),)))
    if view.dataset_names and len(visuals) < MAX_VISUALS:
        series = []
        for name, attribute, ids in (('Identifiers', 'entity_ids', view.entity_ids),
                                    ('Connections', 'relation_ids', view.relation_ids),
                                    ('Alerts', 'finding_ids', view.finding_ids)):
            visible = set(ids)
            points = tuple(VisualPoint(dataset, len(visible.intersection(getattr(context.datasets[dataset], attribute))),
                name, VisualTarget('datasets', AnalystReference('dataset', dataset))) for dataset in view.dataset_names[:6])
            series.append(VisualSeries(name, points))
        if any(p.value for s in series for p in s.points):
            visuals.append(DashboardVisual('coverage', 'vertical_bar', 'Dataset coverage',
                'Visible identifiers, connections and alerts by source.' +
                (f' Showing 6 of {len(view.dataset_names)} datasets.' if len(view.dataset_names) > 6 else ''), tuple(series)))
    return tuple(visuals[:MAX_VISUALS])
