import os
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
        w.workspace.inspector_button.click();app.processEvents()
        assert not w.context_dock.isVisible()
        w.workspace.inspector_button.click();app.processEvents()
        assert w.context_dock.isVisible() and w.context_dock.widget() is inspector
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
            'Overview', 'Investigate', 'Findings', 'Data', 'Relations', 'AI Analyst', 'Settings']
        header = w.workspace.header
        assert header.session_label.text() == 'NO INVESTIGATION'
        w.set_investigation(synthetic())
        assert header.session_label.text() == 'INVESTIGATION 01'
        for button in w.navigation.buttons():
            button.click(); app.processEvents()
            assert w.pages.currentIndex() == w.navigation.id(button)
            assert header.title.text() == button.text()
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
            controls = (*w.navigation.buttons(), w.workspace.run_button, w.workspace.search,
                        w.workspace.inspector_button, *w.workspace.filters._widgets)
            for widget in controls:
                assert widget.isVisible()
                position = widget.mapTo(w, QPoint(0, 0))
                assert w.rect().contains(position)
                assert w.rect().contains(position + QPoint(widget.width()-1, widget.height()-1))
            assert w.overview_page.cards.columns == (2 if width == 640 else 6)
    finally:
        w.close()
