import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QAbstractItemView

from cyber_analyst.ui.main_window import MainWindow


def wait(signal, busy):
    if not busy():
        return
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    signal.connect(loop.quit)
    timer.start(10000)
    loop.exec()
    signal.disconnect(loop.quit)
    assert not busy(), "Operation timed out"


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    widget = MainWindow()
    widget.show()
    yield widget
    widget.close()
    app.processEvents()


def test_empty(window):
    dashboard = window.dashboard_page
    assert window.pages.currentWidget() is dashboard
    assert dashboard.empty_label.isVisible()
    assert not dashboard.body.isVisible()
    assert dashboard.dataset_table.rowCount() == 0


def test_session_flow(window, tmp_path, monkeypatch):
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    first.write_text("id,value\n1,a\n2,\n3,c\n", encoding="utf-8")
    second.write_text("id\n2\n4\n", encoding="utf-8")
    data = window.datasets_page
    data.load_paths([first, second])
    wait(data.loading_finished, lambda: data.is_loading)
    dashboard = window.dashboard_page
    assert not dashboard.empty_label.isVisible()
    assert dashboard.kpis["datasets"].text() == "2"
    assert dashboard.kpis["rows"].text() == "5"
    assert dashboard.kpis["columns"].text() == "3"
    assert dashboard.kpis["largest"].text() == "first.csv\n3 linhas"
    assert dashboard.dataset_table.rowCount() == 2
    assert dashboard.dataset_table.item(1, 3).text() == str(second)
    assert dashboard.dataset_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert [dashboard.bar_set.at(i) for i in range(dashboard.bar_set.count())] == [3, 2]
    assert len(dashboard.category_axis.categories()) == 2
    assert "Nenhuma análise" in dashboard.analysis_label.text()
    assert "Nenhuma correlação" in dashboard.correlation_label.text()

    analysis = window.analyses_page
    analysis.analyze()
    wait(analysis.analysis_finished, lambda: analysis.is_analyzing)
    assert window.session_results.last_analysis.profile is analysis.profile
    assert "first.csv" in dashboard.analysis_label.text()
    assert "Nulos: 1" in dashboard.analysis_label.text()
    assert "Colunas analisadas: 2" in dashboard.analysis_label.text()
    analysis.selector.setCurrentIndex(1)
    assert "first.csv" in dashboard.analysis_label.text()

    correlation = window.correlations_page
    correlation.start()
    wait(correlation.correlation_finished, lambda: correlation.is_correlating)
    assert window.session_results.last_correlation is correlation.result
    assert "Em comum: 1" in dashboard.correlation_label.text()
    assert "Somente A: 2" in dashboard.correlation_label.text()
    assert "Somente B: 1" in dashboard.correlation_label.text()

    # Remover arquivos do disco não impede o Dashboard de usar apenas metadados.
    first.unlink()
    second.unlink()
    dashboard.refresh()
    assert dashboard.kpis["rows"].text() == "5"
    data.remove_selected()
    assert dashboard.dataset_table.rowCount() == 1
    assert dashboard.bar_set.count() == 1 and dashboard.bar_set.at(0) == 2
    assert window.session_results.last_analysis is None
    assert window.session_results.last_correlation is None
    assert "Nenhuma análise" in dashboard.analysis_label.text()
    assert "Nenhuma correlação" in dashboard.correlation_label.text()
    data.remove_selected()
    assert dashboard.empty_label.isVisible()
    assert not dashboard.body.isVisible()


def test_ties_and_zero_rows(window, tmp_path):
    paths = []
    for name in ("first.csv", "second.csv"):
        path = tmp_path / name
        path.write_text("id\n", encoding="utf-8")
        paths.append(path)
    data = window.datasets_page
    data.load_paths(paths)
    wait(data.loading_finished, lambda: data.is_loading)
    dashboard = window.dashboard_page
    assert dashboard.kpis["largest"].text() == "first.csv\n0 linhas"
    assert dashboard.kpis["rows"].text() == "0"
    assert dashboard.bar_set.count() == 2
    assert [dashboard.bar_set.at(i) for i in range(2)] == [0, 0]
