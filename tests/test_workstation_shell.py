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
        assert w.pages.widget(0) is w.dashboard_page
        assert w.pages.widget(3) is w.datasets_page
        assert w.investigate_page.widget(0) is w.analyses_page
        assert w.investigate_page.widget(1) is w.correlations_page
        w.resize(640,400);app.processEvents()
        assert w.width()==640 and w.height()==400
        assert w.workspace.width()>0
    finally:w.close()
