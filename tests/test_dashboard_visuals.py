"""Selection is deterministic and only reads completed, visible results."""
from dataclasses import replace
from datetime import date, timedelta
import pytest
from cyber_analyst.context import ContextService, InvestigationState, ViewService
from cyber_analyst.execution.models import AnalysisStepResult
from cyber_analyst.ui.dashboard_visuals import (
    analysis_visual, categorical_visual, select_visuals, VisualPoint, MAX_VISUALS, category_text,
)
from cyber_analyst.ui.theme import DATA_PALETTE, ATTENTION_COLORS, data_color, data_colors
from test_investigation_context import synthetic
from test_investigation_ui import window


def step(op='column_distribution', columns=('department', 'count'), rows=(('IT', 3), ('HR', 2)), identifier='s'):
    return AnalysisStepResult(identifier, op, 'Executed result', columns, rows)


@pytest.mark.parametrize('count,kind', [(1, 'ranked_list'), (2, 'donut'), (6, 'donut'),
                                     (7, 'horizontal_bar'), (30, 'horizontal_bar')])
def test_categorical_selection_and_explicit_top_n(count, kind):
    p = tuple(VisualPoint(f'category {i}', count-i, str(i)) for i in range(count))
    spec = categorical_visual('a', 'Categories', '', p)
    assert spec.kind == kind
    assert spec.series[0].points == p[:10]
    assert ('Showing 10 of 30' in spec.subtitle) == (count == 30)


def test_numeric_histogram_uses_exact_existing_frequencies_only():
    rows = tuple((i / 2, i+1) for i in range(6))
    source = step(columns=('score', 'count'), rows=rows)
    spec = analysis_visual('data', source)
    assert spec.kind == 'histogram'
    assert [p.value for p in spec.series[0].points] == [r[-1] for r in rows]
    assert [p.label for p in spec.series[0].points] == [str(r[0]) for r in rows]
    assert 'no new bins' in spec.subtitle
    assert source.rows is rows
    assert analysis_visual('data', replace(source, rows=rows[:2])).kind == 'metrics'
    summary = analysis_visual('data', step('numeric_summary', ('column', 'mean', 'minimum', 'maximum'),
                                           (('score', 1.234567891234, 1, 5),)))
    assert summary.kind == 'metrics'
    assert summary.series[0].points[0].value == 1.234567891234


@pytest.mark.parametrize('rows,columns,kind', [
    ((('2026-01-01', 1), ('2026-01-02', 2), ('2026-01-03', 3)), ('day','count'), 'line'),
    ((('2026-01-01', 1), ('2026-01-02', 2)), ('day','count'), None),
    ((('yesterday', 1), ('today', 2), ('tomorrow', 3)), ('day','count'), None),
    ((('2026-01-03', 3), ('2026-01-02', 2), ('2026-01-01', 1)), ('day','count'), None),
    ((('2026-01-01', 'ana', 1),), ('day','user','count'), None),
])
def test_temporal_eligibility(rows, columns, kind):
    spec = analysis_visual('data', step('time_series_count', columns, rows))
    assert (spec.kind if spec else None) == kind


def test_dense_daily_series_and_time_truncation():
    rows = tuple(((date(2026,1,1) + timedelta(days=i)).isoformat(), i) for i in range(60))
    spec = analysis_visual('data', step('time_series_count', ('day','count'), rows))
    assert spec.kind == 'line'
    assert len(spec.series[0].points) == 48
    assert '48 of 60' in spec.subtitle


def test_readable_categories_and_safety_fallbacks():
    assert category_text(('ana',)) == 'ana'
    assert category_text(('ana','yes')) == 'ana | yes'
    assert category_text(None) == '(null)'
    assert analysis_visual('data', step(rows=())) is None
    assert analysis_visual('data', step(rows=(('ana', float('nan')),))) is None
    assert analysis_visual('data', step('unknown')) is None
    assert analysis_visual('data', step(rows=(('ana', -1),))) is None
    assert analysis_visual('data', step(rows=(('ana', 0),))).kind == 'ranked_list'
    assert analysis_visual('data', step(rows=((None, 1),))).series[0].points[0].label == '(null)'


def test_composition_requires_multiple_nonzero_categories():
    spec = analysis_visual('data', step(rows=(('present', 3), ('absent', 0))))
    assert spec.kind == 'horizontal_bar'
    assert [(p.label, p.value) for p in spec.series[0].points] == [('present', 3), ('absent', 0)]


def test_clipped_axis_categories_remain_distinct_with_original_values(window):
    from cyber_analyst.ui.chart_factory import VisualPanel
    from PySide6.QtCore import Qt
    source = step(rows=tuple((f'long-category-with-common-prefix-{i}', 6-i) for i in range(6)))
    spec = replace(analysis_visual('data', source), kind='vertical_bar')
    panel = VisualPanel(spec)
    try:
        chart = panel.chart_view.chart()
        categories = chart.axes(Qt.Orientation.Horizontal)[0].categories()
        assert len(categories) == len(set(categories)) == 6
        assert all('...' in name for name in categories)
        assert tuple(p.label for p in spec.series[0].points) == tuple(str(r[0]) for r in source.rows)
        assert [chart.series()[0].barSets()[0].at(i) for i in range(6)] == list(range(6, 0, -1))
    finally:
        panel.deleteLater()


def context_with_steps(steps):
    r = synthetic()
    return replace(r, datasets=tuple(replace(d, analysis_execution=replace(d.analysis_execution, results=steps)) for d in r.datasets))


def test_attention_entities_and_deterministic_palette():
    c = ContextService().build(synthetic()); v = ViewService().build(c, InvestigationState())
    specs = select_visuals(c, v)
    assert [s.key for s in specs[:2]] == ['attention', 'identifier_types']
    assert specs[0].kind == 'donut'
    assert [(p.label, p.value) for p in specs[0].series[0].points] == [('medium',1),('low',1)]
    assert specs[1].kind == 'donut'
    assert set(ATTENTION_COLORS) == {'high','medium','low','informational'}
    assert data_color('username') == data_color('username')
    assert data_color('arbitrary') in DATA_PALETTE
    assert len({data_color(k) for k in ('username','email','ip_address','hostname','cve')}) == 5
    keys = ('IT','Finance','HR','Operations')
    assert len(set(data_colors(keys).values())) == 4
    assert data_colors(keys) == data_colors(reversed(keys))


def test_bounded_selection_equivalent_scopes_and_order():
    steps = tuple(step(op, identifier=op) for op in ('column_distribution','top_values','group_count')) + (
        step(columns=('result','count'), identifier='other'),
        step('numeric_summary', ('column','mean'), (('cost',3.14),), identifier='summary'),)
    r = context_with_steps(steps)
    c = ContextService().build(r); v = ViewService().build(c, InvestigationState())
    first = select_visuals(c, v)
    assert first == select_visuals(c, v)
    assert len(first) <= MAX_VISUALS
    assert len([s for s in first if s.key.startswith('analysis:')]) <= 3
    for name in c.datasets:
        keys = [s.key for s in first if s.key.startswith('analysis:' + name + ':')]
        assert not any('top_values' in k or 'group_count' in k for k in keys)
    reordered = replace(r, datasets=tuple(reversed(r.datasets)))
    assert select_visuals(ContextService().build(reordered), v) == first


def test_sparse_empty_and_grouped_coverage():
    r = synthetic()
    c = ContextService().build(r); v = ViewService().build(c, InvestigationState())
    assert next(s for s in select_visuals(c, v) if s.key == 'coverage').kind == 'vertical_bar'
    empty = replace(v, dataset_names=(), entity_ids=(), relation_ids=(), finding_ids=(), analysis_ids=(), correlation_ids=())
    assert select_visuals(c, empty) == ()


def test_filters_remove_hidden_data_and_existing_results_are_preserved(window, monkeypatch):
    import duckdb
    import polars as pl
    from cyber_analyst.data import csv_loader
    from cyber_analyst.execution.service import AnalysisExecutionService
    def forbidden(*a, **k): raise AssertionError('No execution or dataset read during rendering')
    monkeypatch.setattr(duckdb, 'connect', forbidden)
    monkeypatch.setattr(pl.LazyFrame, 'collect_schema', forbidden)
    monkeypatch.setattr(csv_loader, 'load_csv', forbidden)
    monkeypatch.setattr(AnalysisExecutionService, 'execute', forbidden)
    r = context_with_steps((step(),))
    window.set_investigation(r)
    p = window.overview_page; s = window.investigation_session
    before = (s.result, s.context, s.view, s.state)
    widgets = tuple(p.visual_panels.values())
    p.refresh()
    assert tuple(p.visual_panels.values()) == widgets
    assert all(a is b for a,b in zip(before, (s.result,s.context,s.view,s.state)))
    s.set_dataset_scope(('remote_access',))
    assert all('directory' not in spec.key for spec in p.visual_specs if spec.key.startswith('analysis:'))
    s.set_entity_types(('username',))
    assert p.entity_chart.counts == (('username',1),)
    s.set_attention_levels(('high',))
    assert 'attention' not in p.visual_panels
    assert s.result is r
    assert s.context.analyses['directory','s'] is r.datasets[1].analysis_execution.results[0]


def test_native_renderers_and_interactions_use_existing_navigation(window):
    r = context_with_steps((step(),))
    window.set_investigation(r)
    p = window.overview_page
    attention = p.visual_panels['attention']
    assert attention.chart_view.chart().series()[0].slices()[0].value() == 1
    attention.chart_view.chart().series()[0].slices()[0].clicked.emit()
    assert window.pages.currentWidget() is window.findings_page
    assert window.investigation_session.state.attention_levels == ('medium',)
    assert window.navigation.checkedId() == 0
    window.investigation_session.clear_filters()
    p.visual_panels['identifier_types'].activate_point(2)
    assert window.pages.currentWidget() is window.relations_tabs
    assert window.investigation_session.state.entity_types == ('username',)
    window.investigation_session.clear_filters()
    key = next(k for k in p.visual_panels if k.startswith('analysis:directory:'))
    p.visual_panels[key].open_button.click()
    assert window.investigation_session.state.focus.analysis.dataset_name == 'directory'
    assert window.pages.currentWidget() is window.investigation_tabs
    assert not window.context_dock.isVisible()


@pytest.mark.parametrize('source,kind', [
    (step(rows=tuple((f'category {i}', 20-i) for i in range(12))), 'horizontal_bar'),
    (step(columns=('value','count'), rows=tuple((i,i+1) for i in range(6))), 'histogram'),
    (step('numeric_summary', ('column','mean'), (('price',1.234567891234),)), 'metrics'),
    (step('time_series_count', ('day','count'), tuple((f'2026-01-0{i}',i) for i in range(1,4))), 'line'),
    (step('time_series_count', ('day','count'), tuple(((date(2026,1,1)+timedelta(days=i)).isoformat(),i+1) for i in range(14))), 'line'),
])
def test_factory_preserves_chart_values_and_shapes(window, source, kind):
    from cyber_analyst.ui.chart_factory import VisualPanel
    from PySide6.QtWidgets import QLabel
    spec = analysis_visual('data', source)
    panel = VisualPanel(spec)
    try:
        assert spec.kind == kind
        if kind == 'horizontal_bar':
            assert panel.bars.points == spec.series[0].points
        elif kind == 'metrics':
            assert '1.234567891234' in [label.text() for label in panel.findChildren(QLabel)]
        else:
            series = panel.chart_view.chart().series()[0]
            if kind == 'histogram':
                assert [series.barSets()[0].at(i) for i in range(6)] == [i+1 for i in range(6)]
            else:
                assert [p.y() for p in series.points()] == [row[-1] for row in source.rows]
    finally:
        panel.deleteLater()


def test_coverage_uses_visible_counts_and_dataset_navigation(window):
    window.set_investigation(synthetic())
    panel = window.overview_page.visual_panels['coverage']
    assert panel.spec.kind == 'vertical_bar'
    assert [p.value for p in panel.spec.series[0].points] == [2,2]
    panel.activate_point(0)
    assert window.investigation_session.state.focus.dataset_name == 'directory'
    assert window.pages.currentWidget() is window.overview_page


def test_stale_chart_cannot_reveal_hidden_category(window):
    window.set_investigation(synthetic())
    p = window.overview_page
    old = p.entity_chart
    window.investigation_session.set_entity_types(('username',))
    state = window.investigation_session.state
    with pytest.raises(ValueError, match='no longer visible'):
        p._visual_activate(old.spec.series[0].points[0].target)  # email, now hidden
    assert window.investigation_session.state is state


def test_presentation_variety_does_not_replace_equivalent_scope(window):
    sources = (step(identifier='composition'),
        step('group_count', ('user','status','count'), (('ana','yes',3),('bruno','no',1)), 'grouped'),
        step('numeric_summary', ('column','mean'), (('cost',2.5),), 'summary'))
    window.set_investigation(context_with_steps(sources))
    kinds = [s.kind for s in window.overview_page.visual_specs if s.key.startswith('analysis:')]
    assert kinds == ['donut','horizontal_bar','metrics']

