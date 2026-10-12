"""Refresh ownership, visibility and generation invalidation; no engine calls."""
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt

from cyber_analyst.analyst import AnalystReference
from test_investigation_context import synthetic
from test_investigation_correlation_page import correlated
from test_investigation_ui import window


def observe(monkeypatch, page):
    calls = []
    render = page._session_refresh.render

    def measured():
        calls.append(page.session.generation)
        render()

    monkeypatch.setattr(page._session_refresh, 'render', measured)
    return calls


@pytest.mark.parametrize('attribute,destination,ids_field,table_field', [
    ('entity_page', 'entities', 'entity_ids', 'selector'),
    ('relations_page', 'relations', 'relation_ids', 'table'),
    ('findings_page', 'findings', 'finding_ids', 'table'),
    ('analysis_explorer', 'analyses', 'analysis_ids', 'selector'),
    ('correlation_explorer', 'correlations', 'correlation_ids', 'selector'),
])
def test_hidden_updates_coalesce_and_navigation_renders_latest(window, monkeypatch,
        attribute, destination, ids_field, table_field):
    page = getattr(window, attribute)
    calls = observe(monkeypatch, page)
    session = window.investigation_session
    window.set_investigation(correlated())
    session.set_dataset_scope(('remote_access',))
    session.set_entity_types(('username',))
    session.set_attention_levels(('medium',))
    assert calls == [] and page._session_refresh.pending
    assert getattr(page, table_field).rowCount() == 0
    snapshot = (session.context, session.state, session.view)
    window._open_dashboard_detail(destination)
    assert calls == [session.generation] and not page._session_refresh.pending
    table = getattr(page, table_field)
    actual = tuple(table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(table.rowCount()))
    assert actual == getattr(session.view, ids_field)
    assert all(a is b for a, b in zip(snapshot, (session.context, session.state, session.view)))
    window._show_page(3)
    window._open_dashboard_detail(destination)
    assert len(calls) == 1  # Showing an unchanged page reuses its rendered snapshot.


def test_hidden_dashboard_and_analyst_recommendations_refresh_on_show(window, monkeypatch):
    window._show_page(3)
    dashboard = window.overview_page
    counts = observe(monkeypatch, dashboard)
    recommendations = observe(monkeypatch, window.analyst_page.next_steps)
    window.set_investigation(synthetic())
    window.investigation_session.set_dataset_scope(('remote_access',))
    assert not counts and not recommendations
    window._show_page(0)
    assert len(counts) == 1
    assert tuple(int(label.text()) for label in dashboard.metrics.values()) == (1, 2, 1, 1, 1, 0)
    window._show_page(6)
    assert len(recommendations) == 1
    assert window.analyst_page.next_steps.steps == dashboard.next_steps.steps


def test_dashboard_does_not_reconstruct_on_focus_only_changes(window, monkeypatch):
    window.set_investigation(synthetic())
    page = window.overview_page
    calls = observe(monkeypatch, page)
    next_steps = observe(monkeypatch, page.next_steps)
    panels = tuple(page.visual_panels.values())
    buttons = page.finding_highlights.buttons
    for kind, identifier in [('entity', 'ana'), ('finding', 'f1'), ('dataset', 'directory')]:
        window.investigation_session.navigate_reference(AnalystReference(kind, identifier))
    assert not calls and not next_steps
    assert panels == tuple(page.visual_panels.values()) and buttons == page.finding_highlights.buttons
    assert 'directory' in window.context_inspector.details.toPlainText()


@pytest.mark.parametrize('destination,attribute,table_field,kind,targets', [
    ('entities', 'entity_page', 'selector', 'entity', ('ana', 'email')),
    ('relations', 'relations_page', 'table', 'relation', ('r1', 'r2')),
])
def test_visible_focus_reuses_table_items_and_updates_details(window, destination,
        attribute, table_field, kind, targets):
    window.set_investigation(synthetic())
    window._open_dashboard_detail(destination)
    page = getattr(window, attribute)
    table = getattr(page, table_field)
    item = table.item(0, 0)
    session = window.investigation_session
    for identifier in (*targets, targets[0]):
        session.navigate_reference(AnalystReference(kind, identifier))
        assert table.item(0, 0) is item
        assert table.selectedItems()[0].data(Qt.ItemDataRole.UserRole) == identifier
        assert getattr(session.state.focus, kind + '_id') == identifier
    assert page.occurrences.rowCount() > 0


def test_replacement_invalidates_identical_ids_and_clear_is_deferred(window):
    first = synthetic()
    window.set_investigation(first)
    window._open_dashboard_detail('entities')
    page = window.entity_page
    item = page.selector.item(0, 0)
    window._show_page(3)
    entities = tuple(replace(e, canonical_value='new ana') if e.entity_id == 'ana' else e
                     for e in first.entities.entities)
    newer = replace(first, entities=replace(first.entities, entities=entities))
    window.set_investigation(newer)
    assert page._session_refresh.pending
    window._open_dashboard_detail('entities')
    assert page.selector.item(0, 0) is not item
    assert page.selector.item(0, 0).text() == 'new ana'
    assert window.investigation_session.result is newer
    window._show_page(3)
    window.investigation_session.clear()
    assert page._session_refresh.pending
    window._show_page(4)
    window.relations_tabs.setTabVisible(0, True)
    window.relations_tabs.setCurrentWidget(page)
    assert page.selector.rowCount() == 0 and 'No active investigation' in page.message.text()


def test_hidden_focused_finding_is_not_replaced_and_stale_action_is_rejected(window):
    window.set_investigation(synthetic())
    session = window.investigation_session
    session.navigate_reference(AnalystReference('finding', 'f1'))
    old = window.overview_page.next_steps
    old_context = session.context
    step = next(s for s in old.steps if s.target_id == 'f1')
    window._show_page(3)
    session.set_attention_levels(('medium',))
    focus = session.state.focus
    window._open_dashboard_detail('findings')
    assert session.state.focus is focus
    assert window.findings_page.table.rowCount() == 1
    assert not window.findings_page.table.selectedItems()
    assert 'f1' in window.context_inspector.details.toPlainText()
    old.activate(step, old_context)
    assert session.state.focus is focus and not old.unavailable.isHidden()
    session.clear_filters()
    assert window.findings_page.table.rowCount() == 2
    assert window.findings_page.table.selectedItems()[0].data(Qt.ItemDataRole.UserRole) == 'f1'
