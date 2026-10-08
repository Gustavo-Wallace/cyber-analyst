"""Deterministic actions are visible facts, never AI recommendations or authority."""
from dataclasses import replace, FrozenInstanceError

import pytest
from cyber_analyst.context import ContextService, InvestigationState, ViewService, StateService
from cyber_analyst.context.next_steps import NextStepsService, MAX_RECOMMENDED_STEPS
from cyber_analyst.entities import EntityResult
from cyber_analyst.relations import RelationResult
from cyber_analyst.findings.models import Finding, FindingResult
from test_investigation_context import synthetic
from test_investigation_correlation_page import correlated
from test_investigation_ui import window


def build(result, state=None):
    context = ContextService().build(result)
    return NextStepsService().build(context, ViewService().build(context, state or InvestigationState()))


def test_attention_ranking_stable_ids_and_maximum():
    result = synthetic()
    levels = ('low', 'medium', 'high', 'informational', 'high', 'medium', 'low')
    evidence = tuple(replace(result.findings.evidence[0], evidence_id=f'e{i}', source_id=f'step{i}') for i in range(7))
    findings = tuple(Finding(f'f{i}', level, (f'e{i}',)) for i, level in enumerate(levels))
    result = replace(result, findings=FindingResult(findings, evidence), entities=EntityResult(()), relations=RelationResult(()))
    steps = build(result)
    assert len(steps) == MAX_RECOMMENDED_STEPS == 4
    assert [s.target_id for s in steps] == ['f2', 'f4', 'f1', 'f5']
    assert all(s.kind == 'review_alert' and s.target_kind == 'finding' for s in steps)
    assert [s.rank for s in steps] == [1, 2, 3, 4]
    assert steps == build(replace(result, findings=FindingResult(findings[::-1], evidence[::-1])))
    with pytest.raises(FrozenInstanceError):
        steps[0].title = 'changed'


def test_findings_before_matches_before_connected_identifiers():
    steps = build(correlated())
    assert [(s.target_kind, s.target_id) for s in steps] == [
        ('finding', 'f2'), ('finding', 'f1'), ('correlation', 'candidate_one'), ('entity', 'ana')]
    assert steps[2].title == 'Review value <-> value data match'
    assert steps[3].supporting_label == 'username | 2 visible connections'
    assert steps[3].source_ids == ('r1', 'r2')


def many_findings(result):
    evidence = tuple(replace(result.findings.evidence[i % 2], evidence_id=f'e{i}', source_id=f'step{i}')
                     for i in range(6))
    findings = tuple(Finding(f'f{i}', 'high', (f'e{i}',)) for i in range(6))
    return replace(result, findings=FindingResult(findings, evidence))


def test_two_alerts_match_and_identifier_preferred_over_more_alerts():
    steps = build(many_findings(correlated()))
    assert [(s.target_kind, s.target_id) for s in steps] == [
        ('finding', 'f0'), ('finding', 'f1'), ('correlation', 'candidate_one'), ('entity', 'ana')]
    assert len(steps) == MAX_RECOMMENDED_STEPS
    # Original candidate rank remains intact, even when earlier alerts are omitted.
    assert [s.rank for s in steps] == [1, 2, 7, 8]


def test_first_pass_diversity_then_fill_from_original_pool():
    steps = build(many_findings(synthetic()))
    assert [(s.target_kind, s.target_id) for s in steps] == [
        ('finding', 'f0'), ('finding', 'f1'), ('entity', 'ana'), ('finding', 'f2')]
    assert [s.rank for s in steps] == [1, 2, 7, 3]
    assert len({s.step_id for s in steps}) == MAX_RECOMMENDED_STEPS


def test_one_alert_does_not_manufacture_a_second_alert_or_match():
    result = synthetic()
    result = replace(result, findings=replace(result.findings, findings=result.findings.findings[:1]))
    steps = build(result)
    assert [(s.target_kind, s.target_id) for s in steps] == [
        ('finding', 'f1'), ('entity', 'ana'), ('entity', 'email'), ('entity', 'ip')]
    assert not any(s.target_kind == 'correlation' for s in steps)


def test_filter_changes_recompute_diversity_without_hidden_targets():
    context = ContextService().build(many_findings(correlated()))
    service, state = StateService(), InvestigationState()
    state = service.set_dataset_scope(state, context, ('remote_access',))
    view = ViewService().build(context, state)
    steps = NextStepsService().build(context, view)
    assert [(s.target_kind, s.target_id) for s in steps] == [
        ('finding', 'f1'), ('finding', 'f3'), ('entity', 'ip'), ('finding', 'f5')]
    assert all(s.target_id in view.finding_ids if s.target_kind == 'finding' else s.target_id in view.entity_ids
               for s in steps)
    state = service.set_entity_types(state, context, ('username',))
    steps = NextStepsService().build(context, ViewService().build(context, state))
    assert [s.target_id for s in steps] == ['f1', 'f3', 'f5']
    assert all(s.target_kind == 'finding' for s in steps)


def test_diversity_keeps_step_identity_provenance_and_repeatability():
    result = many_findings(correlated())
    selected = build(result)
    single_category_results = (
        replace(result, entities=EntityResult(()), relations=RelationResult(()),
                correlation_execution=replace(result.correlation_execution, results=())),
        replace(result, findings=FindingResult(())),
    )
    original_by_id = {s.step_id: s for r in single_category_results for s in build(r)}
    for step in selected:
        original = original_by_id[step.step_id]
        assert (step.target_kind, step.target_id, step.title, step.supporting_label, step.source_ids) == (
            original.target_kind, original.target_id, original.title, original.supporting_label, original.source_ids)
    assert selected == build(result)
    reordered = replace(result, findings=replace(result.findings,
        findings=result.findings.findings[::-1], evidence=result.findings.evidence[::-1]),
        entities=replace(result.entities, entities=result.entities.entities[::-1]),
        relations=replace(result.relations, relations=result.relations.relations[::-1]))
    assert selected == build(reordered)


def test_dashboard_and_analyst_refresh_the_same_diverse_selection(window):
    window.set_investigation(many_findings(correlated()))
    dashboard, analyst = window.overview_page.next_steps, window.analyst_page.next_steps
    assert [s.target_kind for s in dashboard.steps] == ['finding', 'finding', 'correlation', 'entity']
    assert dashboard.steps == analyst.steps
    session = window.investigation_session
    session.set_dataset_scope(('remote_access',))
    assert [s.target_kind for s in dashboard.steps] == ['finding', 'finding', 'entity', 'finding']
    assert dashboard.steps == analyst.steps
    session.clear_filters()
    assert [s.target_kind for s in dashboard.steps] == ['finding', 'finding', 'correlation', 'entity']
    assert dashboard.steps == analyst.steps


def test_near_duplicates_from_same_evidence_or_reversed_match_avoided():
    result = correlated()
    first = result.findings.findings[0]
    item = result.correlation_execution.results[0]
    reversed_match = replace(item, proposal_id='candidate_reverse', left_dataset=item.right_dataset,
                            right_dataset=item.left_dataset, left_column=item.right_column, right_column=item.left_column,
                            correlation_result=replace(item.correlation_result,
                                dataset_a=item.correlation_result.dataset_b, dataset_b=item.correlation_result.dataset_a,
                                column_a=item.right_column, column_b=item.left_column))
    result = replace(result, findings=replace(result.findings, findings=result.findings.findings + (
        replace(first, finding_id='duplicate', attention_level='high'),)),
        correlation_execution=replace(result.correlation_execution, results=(item, reversed_match)))
    steps = build(result)
    assert len([s for s in steps if s.target_kind == 'finding']) == 2
    assert len([s for s in steps if s.target_kind == 'correlation']) == 1
    assert len({s.step_id for s in steps}) == len(steps)


def test_filters_control_all_recommendation_sources_and_connection_counts():
    result = correlated()
    context = ContextService().build(result)
    service = StateService()
    state = service.set_dataset_scope(InvestigationState(), context, ('remote_access',))
    state = service.set_attention_levels(state, ('high',))
    steps = NextStepsService().build(context, ViewService().build(context, state))
    assert [s.target_id for s in steps] == ['ip', 'ana']
    assert all('1 visible connection' in s.supporting_label for s in steps)
    assert all(s.source_ids == ('r2',) for s in steps)
    state = service.set_entity_types(state, context, ('username',))
    steps = NextStepsService().build(context, ViewService().build(context, state))
    assert [(s.target_kind, s.target_id) for s in steps] == [('dataset', 'remote_access')]


def test_dataset_fallback_only_with_executed_visible_analyses():
    result = replace(synthetic(), entities=EntityResult(()), relations=RelationResult(()), findings=FindingResult(()))
    assert [s.target_id for s in build(result)] == ['directory', 'remote_access']
    result = replace(result, datasets=tuple(replace(d, analysis_execution=replace(d.analysis_execution, results=()))
                                           for d in result.datasets))
    assert build(result) == ()


def test_no_fake_recommendations_and_rendering_is_read_only(window):
    page = window.overview_page
    assert not page.next_steps.steps and not window.analyst_page.next_steps.steps
    result = correlated()
    window.set_investigation(result)
    session = window.investigation_session
    before = (session.result, session.context, session.state, session.view)
    for _ in range(3):
        page.next_steps.refresh()
        window.analyst_page.next_steps.refresh()
    assert all(a is b for a, b in zip(before, (session.result, session.context, session.state, session.view)))
    assert page.next_steps.steps == window.analyst_page.next_steps.steps == build(result)
    session.clear()
    assert not page.next_steps.steps and not window.analyst_page.next_steps.steps


@pytest.mark.parametrize('kind,destination', [('finding', 2), ('correlation', 1), ('entity', 4), ('dataset', 0)])
def test_recommendation_click_reuses_session_navigation(window, monkeypatch, kind, destination):
    result = correlated()
    if kind == 'dataset':
        result = replace(synthetic(), entities=EntityResult(()), relations=RelationResult(()), findings=FindingResult(()))
    window.set_investigation(result)
    widget = window.overview_page.next_steps
    index = next(i for i, step in enumerate(widget.steps) if step.target_kind == kind)
    step = widget.steps[index]
    session = window.investigation_session
    original = session.navigate_reference
    calls = []
    def spy(reference):
        calls.append(reference)
        return original(reference)
    monkeypatch.setattr(session, 'navigate_reference', spy)
    filters = (session.state.dataset_scope, session.state.entity_types, session.state.attention_levels)
    widget.buttons[index].click()
    assert calls[0].kind == kind and calls[0].target_id == step.target_id
    assert window.pages.currentIndex() == destination
    assert getattr(session.state.focus, kind + '_id' if kind != 'dataset' else 'dataset_name') == step.target_id
    assert (session.state.dataset_scope, session.state.entity_types, session.state.attention_levels) == filters


def test_hidden_old_recommendation_is_not_authorization(window):
    window.set_investigation(correlated())
    widget, session = window.overview_page.next_steps, window.investigation_session
    step = next(s for s in widget.steps if s.target_id == 'f1')
    original_context = session.context
    session.set_dataset_scope(('remote_access',))
    assert all(s.target_id != 'f1' for s in widget.steps)
    before = (session.state, session.view)
    widget.activate(step, original_context)
    assert widget.unavailable.text() == 'Not available in the current view.'
    assert not widget.unavailable.isHidden()
    assert (session.state, session.view) == before
    assert session.state is before[0] and window.pages.currentWidget() is window.overview_page
    session.clear_filters()
    window.set_investigation(correlated())
    before = session.state
    widget.activate(step, original_context)
    assert session.state is before


def test_filtered_dashboard_updates_and_strong_targets_restore(window):
    window.set_investigation(correlated())
    widget, session = window.overview_page.next_steps, window.investigation_session
    session.set_dataset_scope(('remote_access',))
    assert all(s.target_kind != 'correlation' for s in widget.steps)
    assert all(s.target_id not in ('f1', 'email') for s in widget.steps)
    session.set_attention_levels(('high',))
    assert all(s.target_kind != 'finding' for s in widget.steps)
    session.set_entity_types(('username',))
    assert [s.target_kind for s in widget.steps] == ['dataset']
    session.clear_filters()
    assert widget.steps == build(correlated())


def test_dataset_derived_action_labels_remain_plain_text(window):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    result = synthetic()
    result = replace(result, findings=FindingResult(()), entities=replace(result.entities, entities=tuple(
        replace(e, canonical_value='<b>ana</b> & data') if e.entity_id == 'ana' else e
        for e in result.entities.entities)))
    window.set_investigation(result)
    widget = window.overview_page.next_steps
    index = next(i for i, step in enumerate(widget.steps) if step.target_id == 'ana')
    assert widget.steps[index].title == 'Inspect <b>ana</b> & data'
    labels = widget.buttons[index].findChildren(QLabel)
    assert labels[0].text() == widget.steps[index].title
    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)


def test_readable_recommendation_operations_preserve_source_and_navigation(window):
    from PySide6.QtWidgets import QLabel
    from cyber_analyst.ui.presentation_labels import human_label, finding_supporting_label
    assert human_label('column_distribution') == 'Column distribution'
    assert human_label('group_count') == 'Group count'
    assert finding_supporting_label('High attention | column_distribution, group_count | raw_column') == (
        'High attention | Column distribution, Group count | raw_column')
    window.set_investigation(synthetic())
    widget = window.overview_page.next_steps
    index = next(i for i, step in enumerate(widget.steps) if step.target_id == 'f1')
    step = widget.steps[index]
    button = widget.buttons[index]
    assert 'Unique count' in button.findChildren(QLabel)[1].text()
    assert 'unique_count' in step.supporting_label and 'unique_count' in button.toolTip()
    before = window.investigation_session.result
    button.click()
    assert window.investigation_session.state.focus.finding_id == 'f1'
    assert window.investigation_session.result is before
