"""References authorize against the current session/view, never their history."""
from dataclasses import replace
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from cyber_analyst.analyst import AnalystReference, AnalystObservation
from cyber_analyst.context import NavigationService, StateService, InvestigationFocus
from cyber_analyst.ui.analyst_page import REFERENCE_UNAVAILABLE
from test_analyst_page import setup, send, wait
from test_investigation_context import synthetic
from test_investigation_correlation_page import correlated


def answer(setup, references, result=None):
    app, provider, window, page = setup
    window.set_investigation(result or correlated())
    provider.response = replace(provider.response, observations=(AnalystObservation(
        'Exact committed answer text.', tuple(references), ('fact_stable',)),))
    provider.release.set()
    send(window, page)
    wait(app, lambda: not window.analyst_runner.running)
    return page.exchanges[-1]


@pytest.mark.parametrize('reference,destination,tab,focus', [
    (AnalystReference('entity', 'ana'), 4, 0, InvestigationFocus(entity_id='ana')),
    (AnalystReference('relation', 'r1'), 4, 1, InvestigationFocus(relation_id='r1')),
    (AnalystReference('finding', 'f1'), 2, None, InvestigationFocus(finding_id='f1')),
    (AnalystReference('analysis', 'count', 'directory'), 1, 0, None),
    (AnalystReference('correlation', 'candidate_one'), 1, 1, InvestigationFocus(correlation_id='candidate_one')),
    (AnalystReference('dataset', 'directory'), 0, None, InvestigationFocus(dataset_name='directory')),
])
def test_reference_uses_existing_navigation_and_reveals_object(setup, monkeypatch, reference, destination, tab, focus):
    app, provider, w, page = setup
    exchange = answer(setup, [reference])
    svc = StateService if reference.kind in ('relation', 'correlation') else NavigationService
    name = 'focus_' + reference.kind if svc is StateService else 'focus_search_result'
    original = getattr(svc, name)
    calls = []
    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(svc, name, spy)
    before = w.investigation_session.state
    text = exchange.answer.toPlainText()
    exchange.references.items[0].open_button.click()
    s = w.investigation_session
    assert calls
    # Showing an existing selector may re-emit its already focused selection.
    assert all((args[-1] if svc is StateService else args[-1].target_id) == reference.target_id
               for args, _ in calls)
    assert w.pages.currentIndex() == destination
    assert w.navigation.button(destination).isChecked()
    assert (s.state.dataset_scope, s.state.entity_types, s.state.attention_levels) == (
        before.dataset_scope, before.entity_types, before.attention_levels)
    if focus is not None:
        assert s.state.focus == focus
    else:
        assert s.state.focus.analysis.dataset_name == 'directory'
        assert s.state.focus.analysis.analysis_id == 'count'
        assert w.analysis_explorer.selector.selectedItems()[0].data(Qt.ItemDataRole.UserRole) == ('directory', 'count')
    if destination == 4:
        assert w.relations_tabs.currentIndex() == tab
    if destination == 1:
        assert w.investigation_tabs.currentIndex() == tab
    if reference.kind == 'dataset':
        assert w.overview_page.coverage.selectedItems()[0].text() == 'directory'
    assert exchange.answer.toPlainText() == text
    assert w.context_inspector.details.toPlainText() != 'Select an investigation object to inspect its context.'
    w.navigation.button(6).click()
    assert page.exchanges == [exchange]


@pytest.mark.parametrize('reference', [
    AnalystReference('entity', 'email'), AnalystReference('relation', 'r1'),
    AnalystReference('finding', 'f1'), AnalystReference('analysis', 'count', 'directory'),
    AnalystReference('correlation', 'candidate_one'), AnalystReference('dataset', 'directory'),
])
def test_hidden_reference_does_not_broaden_filters_and_can_become_visible_again(setup, reference):
    app, provider, w, page = setup
    exchange = answer(setup, [reference])
    item = exchange.references.items[0]
    text = exchange.answer.toPlainText()
    s = w.investigation_session
    s.set_dataset_scope(['remote_access'])
    before, view = s.state, s.view
    assert item.open_button.isEnabled()  # Rechecked on activation, not filter refresh.
    item.open_button.click()
    assert s.state is before and s.view is view and s.state.dataset_scope == ('remote_access',)
    assert w.pages.currentWidget() is page
    assert exchange.reference_status.text() == REFERENCE_UNAVAILABLE
    assert exchange.answer.toPlainText() == text
    s.clear_filters()
    item.open_button.click()
    assert not exchange.reference_status.isVisible()
    assert w.pages.currentWidget() is not page


@pytest.mark.parametrize('reference', [AnalystReference('entity', 'missing'),
    AnalystReference('finding', 'missing'), AnalystReference('analysis', 'count'),
    AnalystReference('analysis', 'missing', 'directory'), AnalystReference('correlation', 'missing'),
    AnalystReference('relation', 'missing'), AnalystReference('dataset', 'missing')])
def test_unknown_or_malformed_reference_uses_same_unavailable_message(setup, reference):
    app, provider, w, page = setup
    exchange = answer(setup, [reference])
    state = w.investigation_session.state
    exchange.references.items[0].open_button.click()
    assert exchange.reference_status.text() == REFERENCE_UNAVAILABLE
    assert w.investigation_session.state is state and w.pages.currentWidget() is page


def test_replacement_preserves_history_but_old_identical_ids_cannot_navigate(setup):
    app, provider, w, page = setup
    exchange = answer(setup, [AnalystReference('entity', 'ana')])
    text = exchange.answer.toPlainText()
    w.set_investigation(correlated())
    s = w.investigation_session
    state = s.state
    assert 'Previous investigation' in exchange.snapshot_label.text()
    assert not exchange.references.items[0].open_button.isEnabled()
    # Identity gate also protects against a queued activation emitted before replacement.
    exchange.reference_requested.emit(exchange, AnalystReference('entity', 'ana'))
    assert s.state is state and exchange.reference_status.text() == REFERENCE_UNAVAILABLE
    assert exchange.answer.toPlainText() == text
    send(w, page, 'New snapshot question')
    wait(app, lambda: not w.analyst_runner.running)
    current = page.exchanges[-1]
    assert current.snapshot.context is s.context and current.current
    assert current.references.items[0].open_button.isEnabled()
    assert 'Previous investigation' not in current.snapshot_label.text()
    assert provider.calls[-1][1] is s.context
    s.clear()
    assert all(not e.current for e in page.exchanges)
    assert all(not i.open_button.isEnabled() for e in page.exchanges for i in e.references.items)


def test_replacement_during_running_request_marks_late_answer_stale(setup):
    app, provider, w, page = setup
    send(w, page)
    wait(app, lambda: bool(provider.calls))
    old = page.exchanges[0]
    w.set_investigation(synthetic())
    provider.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    assert old.outcome_status == 'answered' and not old.current
    assert 'Previous investigation' in old.snapshot_label.text()
    assert not old.references.items[0].open_button.isEnabled()


@pytest.mark.parametrize('reference,filters', [
    (AnalystReference('entity', 'email'), {'entity_types': ['username']}),
    (AnalystReference('finding', 'f1'), {'attention_levels': ['high']}),
])
def test_type_and_attention_filters_authorize_at_click_time(setup, reference, filters):
    app, provider, w, page = setup
    exchange = answer(setup, [reference])
    s = w.investigation_session
    for name, values in filters.items():
        getattr(s, 'set_' + name)(values)
    state = s.state
    exchange.references.items[0].open_button.click()
    assert exchange.reference_status.text() == REFERENCE_UNAVAILABLE
    assert s.state is state


@pytest.mark.parametrize('reference', [AnalystReference('entity', 'email'),
    AnalystReference('relation', 'r1'), AnalystReference('correlation', 'candidate_one')])
def test_cached_view_cannot_authorize_against_current_filters(setup, reference):
    app, provider, w, page = setup
    exchange = answer(setup, [reference])
    s = w.investigation_session
    old_view = s.view
    s.set_dataset_scope(['remote_access'])
    state = s.state
    s.view = old_view
    exchange.references.items[0].open_button.click()
    assert s.state is state and exchange.reference_status.text() == REFERENCE_UNAVAILABLE


def test_analysis_reference_composite_identity_and_full_id_metadata(setup):
    app, provider, w, page = setup
    long_id = 'analysis_' + 'a' * 64
    r = synthetic()
    entry = r.datasets[1]
    execution = replace(entry.analysis_execution, results=(replace(entry.analysis_execution.results[0], step_id=long_id),))
    r = replace(r, datasets=(r.datasets[0], replace(entry, analysis_execution=execution)))
    exchange = answer(setup, [AnalystReference('analysis', long_id, 'directory'),
                             AnalystReference('analysis', 'count', 'remote_access')], r)
    item = exchange.references.items[0]
    assert item.reference.target_id == item.identity.toolTip() == long_id
    assert len(item.identity.text()) < len(long_id) and item.identity.text().endswith('...')
    item.open_button.click()
    focus = w.investigation_session.state.focus.analysis
    assert (focus.dataset_name, focus.analysis_id) == ('directory', long_id)
    w.navigation.button(6).click()
    exchange.references.items[1].open_button.click()
    focus = w.investigation_session.state.focus.analysis
    assert (focus.dataset_name, focus.analysis_id) == ('remote_access', 'count')


def test_clearing_history_preserves_nonempty_focus_and_filters(setup):
    app, provider, w, page = setup
    exchange = answer(setup, [AnalystReference('entity', 'ana')])
    exchange.references.items[0].open_button.click()
    s = w.investigation_session
    s.set_dataset_scope(['remote_access'])
    s.set_entity_types(['username'])
    s.set_attention_levels(['high'])
    state, view = s.state, s.view
    w.navigation.button(6).click()
    page.clear_button.click()
    assert not page.exchanges and s.state is state and s.view is view
    assert s.state.focus.entity_id == 'ana'


def test_clear_disabled_while_running_and_running_question_remains_readable(setup):
    app, provider, w, page = setup
    send(w, page, 'Readable submitted question')
    wait(app, lambda: bool(provider.calls))
    e = page.exchanges[0]
    assert e.question.text() == 'Readable submitted question'
    assert e.question.isEnabled() and e.answer.isEnabled() and e.answer.isReadOnly()
    assert e.outcome_status == 'running' and e.result_status.text() == 'Running request'
    assert not page.clear_button.isEnabled()
    state = w.investigation_session.state
    page.clear_conversation()
    assert page.exchanges == [e] and w.analyst_runner.running
    provider.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    page.clear_button.click()
    assert not page.exchanges and w.investigation_session.state is state


def test_keyboard_focus_returns_after_completion_when_page_stays_active(setup):
    app, provider, w, page = setup
    w.set_investigation(synthetic())
    w.activateWindow()
    page.question.setFocus()
    page.question.setPlainText('Keyboard question')
    QTest.keyClick(page.question, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    wait(app, lambda: bool(provider.calls))
    assert page.question.toPlainText() == ''
    provider.release.set()
    wait(app, lambda: page.question.hasFocus())


@pytest.mark.parametrize('return_to_analyst', [False, True])
def test_completion_does_not_steal_focus_after_navigating_away(setup, return_to_analyst):
    app, provider, w, page = setup
    w.activateWindow()
    send(w, page)
    wait(app, lambda: bool(provider.calls))
    w.navigation.button(0).click()
    if return_to_analyst:
        w.navigation.button(6).click()
    w.workspace.search.setFocus()
    provider.release.set()
    wait(app, lambda: not w.analyst_runner.running)
    app.processEvents()
    assert w.pages.currentWidget() is (page if return_to_analyst else w.overview_page)
    assert w.workspace.search.hasFocus() and not page.question.hasFocus()


def test_source_frames_and_files_unchanged_by_navigation(setup, tmp_path, monkeypatch):
    from cyber_analyst.data import csv_loader
    def forbidden(*args, **kwargs): raise AssertionError('CSV reread')
    monkeypatch.setattr(csv_loader, 'load_csv', forbidden)
    r = synthetic()
    datasets = []
    for entry in r.datasets:
        path = tmp_path / entry.dataset.name
        path.write_bytes(b'value\nana\n')
        datasets.append(replace(entry, dataset=replace(entry.dataset, path=path)))
    r = replace(r, datasets=tuple(datasets))
    previews = [d.dataset.preview.clone() for d in r.datasets]
    plans = [d.dataset.lazy_frame.explain() for d in r.datasets]
    exchange = answer(setup, [AnalystReference('entity', 'ana')], r)
    exchange.references.items[0].open_button.click()
    for entry, frame, plan in zip(r.datasets, previews, plans):
        assert entry.dataset.preview.equals(frame)
        assert entry.dataset.lazy_frame.explain() == plan
        assert entry.dataset.path.read_bytes() == b'value\nana\n'
