import os
import pytest
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from cyber_analyst.ui.main_window import MainWindow


def test_shell_no_backend_calls_and_inspector(monkeypatch):
    from cyber_analyst.ai import LlamaRuntime, AIService
    from cyber_analyst.analysis import exploratory
    def forbidden(*a,**k):raise AssertionError('backend call at construction')
    monkeypatch.setattr(LlamaRuntime,'start',forbidden)
    monkeypatch.setattr(AIService,'generate_structured',forbidden)
    monkeypatch.setattr(exploratory,'profile_dataset',forbidden)
    app=QApplication.instance() or QApplication([])
    w=MainWindow()
    try:
        assert (w.width(),w.height())==(1100,720)
        w.show();app.processEvents()
        inspector=w.context_dock.widget()
        assert not w.context_dock.isVisible()
        assert not w.workspace.inspector_button.isChecked()
        w.workspace.inspector_button.click();app.processEvents()
        assert w.context_dock.isVisible()
        w.workspace.inspector_button.click();app.processEvents()
        assert not w.context_dock.isVisible() and w.context_dock.widget() is inspector
        w.context_dock.close();app.processEvents()
        assert not w.workspace.inspector_button.isChecked()
        w.workspace.inspector_button.click();app.processEvents()
        assert w.context_dock.widget() is inspector
        assert w.pages.widget(0) is w.overview_page
        assert w.overview_page.currentWidget() is w.dashboard_page
        assert w.pages.widget(3) is w.datasets_page
        assert w.investigate_page.widget(0) is w.analyses_page
        assert w.investigate_page.widget(1) is w.correlations_page
        w.resize(640,400);app.processEvents()
        assert w.width()==640 and w.height()==400
        assert w.workspace.width()>0
    finally:w.close()


def test_navigation_header_and_session_identity():
    from test_investigation_context import synthetic
    from PySide6.QtWidgets import QPushButton
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    try:
        w.show(); app.processEvents()
        sidebar = [w.sidebar.layout().itemAt(i).widget() for i in range(w.sidebar.layout().count())]
        assert [b.text() for b in sidebar if isinstance(b, QPushButton)] == [
            'Dashboard', 'Data', 'AI Analyst', 'Settings']
        header = w.workspace.header
        assert header.session_label.text() == 'NO INVESTIGATION'
        w.set_investigation(synthetic())
        assert header.session_label.text() == 'INVESTIGATION 01'
        for button in w.navigation.buttons():
            button.click(); app.processEvents()
            assert w.pages.currentIndex() == w.navigation.id(button)
            assert header.title.text() == button.text()
            selected = 0 if w.navigation.id(button) in (1, 2, 4) else w.navigation.id(button)
            assert w.navigation.checkedId() == selected
        assert all(w.navigation.button(i).isHidden() for i in (1, 2, 4))
        w.investigation_session.clear_filters()
        assert header.session_label.text() == 'INVESTIGATION 01'
        w.set_investigation(synthetic())
        assert header.session_label.text() == 'INVESTIGATION 02'
        w.investigation_session.clear()
        assert header.session_label.text() == 'NO INVESTIGATION'
    finally:
        w.close()


def test_empty_overview_fits_after_replacing_completed_investigation():
    from PySide6.QtCore import QPoint
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    try:
        w.show(); w.set_investigation(synthetic())
        w.resize(640, 400)
        w.investigation_session.clear()
        for _ in range(3): app.processEvents()
        viewport = w.workspace.scroll.viewport()
        caption = w.dashboard_page.empty_caption
        assert caption.isVisible()
        assert viewport.rect().contains(caption.mapTo(viewport, QPoint(0, caption.height()-1)))
        assert w.workspace.scroll.verticalScrollBar().maximum() == 0
    finally:
        w.close()


def test_primary_controls_accessible_at_desktop_sizes():
    from PySide6.QtCore import QPoint
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    try:
        w.show(); w.set_investigation(synthetic())
        for width, height in ((1920,1080), (1366,768), (640,400)):
            w.resize(width, height)
            for _ in range(3): app.processEvents()
            assert (w.width(), w.height()) == (width, height)
            controls = (*(w.navigation.button(i) for i in (0, 3, 6, 5)),
                        w.workspace.run_button, w.workspace.search,
                        w.workspace.inspector_button, w.workspace.filters_button)
            for widget in controls:
                assert widget.isVisible()
                position = widget.mapTo(w, QPoint(0, 0))
                assert w.rect().contains(position)
                assert w.rect().contains(position + QPoint(widget.width()-1, widget.height()-1))
            assert w.overview_page.cards.columns >= (3 if width == 640 else 6)
            for kind, button in w.overview_page.metric_buttons.items():
                assert button.rect().contains(w.overview_page.metrics[kind].geometry())
        w.workspace.filters_button.click()
        app.processEvents()
        assert all(control.isVisible() for control in w.workspace.filters._widgets)
    finally:
        w.close()


def test_exploration_collapsed_active_filters_and_lifecycle():
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    try:
        w.show(); app.processEvents()
        assert w.pages.currentWidget() is w.overview_page
        assert w.workspace.header.title.text() == 'Dashboard'
        assert not w.workspace.command_panel.isVisible()
        assert w.dashboard_page.primary_button.text() == 'Add datasets'
        w.set_investigation(synthetic()); app.processEvents()
        assert w.workspace.command_panel.isVisible()
        assert w.workspace.search.placeholderText() == 'Search investigation'
        assert not w.workspace.filters.controls_panel.isVisible()
        s = w.investigation_session
        s.set_dataset_scope(('remote_access',))
        assert w.workspace.filters_button.text() == 'Filters (1)'
        assert w.workspace.filters.active_summary.isVisible()
        assert w.workspace.filters.active_summary.text() == 'Datasets: remote_access'
        w.workspace.search.setText('email')
        assert w.workspace.search_results.count() == 0
        w.workspace.filters_button.click(); app.processEvents()
        assert w.workspace.filters.controls_panel.isVisible()
        w.workspace.filters.clear_button.click()
        assert w.workspace.filters_button.text() == 'Filters'
        assert not w.workspace.filters.active_summary.isVisible()
        s.clear(); app.processEvents()
        assert not w.workspace.command_panel.isVisible()
        assert not w.workspace.filters_button.isChecked()
    finally:
        w.close()


def test_data_hides_exploration_without_changing_filters_focus_or_controls():
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    try:
        w.show(); w.set_investigation(synthetic())
        session = w.investigation_session
        session.set_dataset_scope(('remote_access',))
        session.set_entity_types(('username',))
        session.set_attention_levels(('medium',))
        session.navigate(next(iter(session.search('ana'))))
        w.workspace.search.setText('ana')
        w.workspace.filters_button.click()
        w.workspace.inspector_button.click()
        app.processEvents()
        before = (session.result, session.context, session.state, session.view)
        inspector = w.context_dock.widget()
        details = w.context_inspector.details.toPlainText()
        w.navigation.button(3).click(); app.processEvents()
        assert not w.workspace.command_panel.isVisible()
        assert not w.workspace.filters.isVisible()
        assert all(a is b for a, b in zip(before, (
            session.result, session.context, session.state, session.view)))
        assert w.workspace.search.text() == 'ana'
        assert w.workspace.filters_button.isChecked()
        assert w.context_dock.isVisible() and w.context_dock.widget() is inspector
        assert w.context_inspector.details.toPlainText() == details
        w.navigation.button(0).click(); app.processEvents()
        assert w.workspace.command_panel.isVisible()
        assert w.workspace.filters.controls_panel.isVisible()
        assert w.workspace.filters_button.text() == 'Filters (3)'
        assert all(a is b for a, b in zip(before, (
            session.result, session.context, session.state, session.view)))
        w.workspace.search.setText('username')
        assert w.workspace.search_results.count() == 1
    finally:
        w.close()


@pytest.mark.parametrize('destination', [3, 5])
def test_investigation_updates_do_not_reveal_toolbar_on_data_or_settings(destination):
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    try:
        w.show(); w.navigation.button(destination).click()
        w.set_investigation(synthetic()); app.processEvents()
        assert not w.workspace.command_panel.isVisible()
        w.investigation_session.set_dataset_scope(('remote_access',))
        assert not w.workspace.command_panel.isVisible()
        w.set_investigation(synthetic())
        assert not w.workspace.command_panel.isVisible()
        w.navigation.button(0).click(); app.processEvents()
        assert w.workspace.command_panel.isVisible()
        w.investigation_session.clear()
        assert not w.workspace.command_panel.isVisible()
        w.navigation.button(3).click(); w.navigation.button(0).click()
        assert not w.workspace.command_panel.isVisible()
    finally:
        w.close()


@pytest.mark.parametrize('destination', [0, 1, 2, 4, 3, 6])
def test_settings_hides_shell_actions_and_restores_destination_without_mutating_state(destination):
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow(investigation_pipeline=object())
    try:
        w.show(); w.set_investigation(synthetic())
        for entry in w.investigation_session.result.datasets:
            w.collection.add(entry.dataset)
        w._collection_changed()
        session = w.investigation_session
        session.set_dataset_scope(('remote_access',))
        session.set_entity_types(('username',))
        session.navigate(next(iter(session.search('ana'))))
        w.workspace.search.setText('ana')
        w.workspace.filters_button.setChecked(True)
        w.workspace.inspector_button.setChecked(True)
        app.processEvents()
        before = (session.result, session.context, session.state, session.view)
        details = w.context_inspector.details.toPlainText()
        apply_action = w.settings_page.apply_button
        w.navigation.button(5).click(); app.processEvents()
        assert not w.workspace.search.isVisible()
        assert not w.workspace.filters_button.isVisible()
        assert not w.workspace.inspector_button.isVisible()
        assert w.workspace.run_button.isHidden()
        assert apply_action.isVisible() and apply_action.isEnabled()
        assert apply_action.text() == 'Apply settings'
        assert w.context_dock.isVisible() and w.context_inspector.details.toPlainText() == details
        # Runner/session refreshes must not expose hidden Settings shell controls.
        w._update_run_controls(); w._investigation_changed(); app.processEvents()
        assert w.workspace.run_button.isHidden() and w.workspace.command_panel.isHidden()
        assert all(a is b for a,b in zip(before, (session.result,session.context,session.state,session.view)))
        w.navigation.button(destination).click(); app.processEvents()
        assert w.settings_page.apply_button is apply_action
        assert w.workspace.run_button.isVisible() and w.workspace.run_button.text() == 'Analyze again'
        assert w.workspace.command_panel.isVisible() == (destination != 3)
        assert w.workspace.search.isVisible() == (destination not in (3,6))
        assert w.workspace.filters_button.isVisible() == (destination != 3)
        assert w.workspace.inspector_button.isVisible() == (destination != 3)
        assert w.workspace.filters_button.isChecked() and w.workspace.inspector_button.isChecked()
        assert w.workspace.search.text() == 'ana'
        assert all(a is b for a,b in zip(before, (session.result,session.context,session.state,session.view)))
        assert w.context_inspector.details.toPlainText() == details
    finally:
        w.close()


def test_analyst_hides_only_search_and_preserves_investigation_controls():
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    try:
        w.show(); w.set_investigation(synthetic())
        session = w.investigation_session
        session.set_dataset_scope(('remote_access',))
        w.workspace.search.setText('ana')
        w.workspace.filters_button.click()
        before = (session.result, session.context, session.state, session.view)
        w.navigation.button(6).click(); app.processEvents()
        assert w.workspace.search.isHidden() and w.workspace.search_results.isHidden()
        assert w.workspace.filters_button.isVisible() and w.workspace.inspector_button.isVisible()
        assert w.workspace.filters.controls_panel.isVisible()
        assert w.analyst_page.question.isVisible()
        w.workspace.search.setText('username')
        assert w.workspace.search_results.isHidden()
        session.clear_filters()
        assert w.workspace.search.isHidden()
        session.set_dataset_scope(('remote_access',))
        after_filtering = (session.result, session.context, session.state, session.view)
        w.navigation.button(0).click(); app.processEvents()
        assert w.workspace.search.isVisible() and w.workspace.search.text() == 'username'
        assert w.workspace.filters.controls_panel.isVisible()
        assert all(a is b for a, b in zip(after_filtering, (
            session.result, session.context, session.state, session.view)))
        assert session.result is before[0] and session.context is before[1]
        assert session.state == before[2] and session.view == before[3]
    finally:
        w.close()


def test_primary_workflow_has_one_empty_page_action():
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow(investigation_pipeline=object())
    try:
        w.show(); app.processEvents()
        assert w.workspace.run_button.isHidden()
        assert w.dashboard_page.primary_button.isVisible()
        assert w.dashboard_page.primary_button.text() == 'Add datasets'
        w.dashboard_page.primary_button.click(); app.processEvents()
        assert w.workspace.run_button.isHidden() and w.datasets_page.add_button.isVisible()
        for entry in synthetic().datasets:
            w.collection.add(entry.dataset)
        w._collection_changed()
        assert not w.workspace.run_button.isHidden() and w.workspace.run_button.text() == 'Analyze'
        w.navigation.button(0).click()
        assert w.workspace.run_button.isHidden() and w.dashboard_page.primary_button.text() == 'Analyze'
        w.set_investigation(synthetic())
        assert not w.workspace.run_button.isHidden() and w.workspace.run_button.text() == 'Analyze again'
    finally:
        w.close()


@pytest.mark.parametrize('kind,destination,tab', [
    ('analyses', 1, 0), ('correlations', 1, 1), ('findings', 2, None),
    ('entities', 4, 0), ('relations', 4, 1),
])
def test_dashboard_metrics_reveal_registered_details(kind, destination, tab):
    from test_investigation_context import synthetic
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    try:
        w.set_investigation(synthetic())
        before = w.investigation_session.state
        w.navigation.button(3).click()
        assert w.workspace.command_panel.isHidden()
        w.overview_page.metric_buttons[kind].click()
        assert w.pages.currentIndex() == destination
        assert w.navigation.checkedId() == 0
        assert not w.workspace.command_panel.isHidden()
        assert all(w.navigation.button(i).isHidden() for i in (1, 2, 4))
        if tab is not None:
            tabs = w.investigation_tabs if destination == 1 else w.relations_tabs
            assert tabs.currentIndex() == tab
        assert w.investigation_session.state is before
        w.navigation.button(0).click()
        assert w.pages.currentWidget() is w.overview_page
        assert not w.workspace.command_panel.isHidden()
    finally:
        w.close()
