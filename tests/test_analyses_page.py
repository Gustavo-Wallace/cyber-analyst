from threading import Event

import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.ui.main_window import MainWindow


def wait_signal(signal, busy):
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
    widget.navigation.button(2).click()
    yield widget
    widget.close()
    app.processEvents()


def add(window, tmp_path, name="events.csv"):
    path = tmp_path / name
    path.write_text("id,host\n1,a\n3,a\n5,b\n", encoding="utf-8")
    window.datasets_page.load_path(path)
    wait_signal(window.datasets_page.loading_finished, lambda: window.datasets_page.is_loading)
    return path


def analyze(page):
    page.analyze_button.click()
    assert page.status.text() == "Analisando..."
    assert not page.analyze_button.isEnabled()
    wait_signal(page.analysis_finished, lambda: page.is_analyzing)


def test_shared_collection_profile_distribution_and_switch(window, tmp_path):
    page = window.analyses_page
    assert page.collection is window.collection is window.datasets_page.collection
    assert page.selector.count() == 0
    assert not page.analyze_button.isEnabled()
    add(window, tmp_path)
    assert page.selector.count() == 1
    analyze(page)
    assert "Linhas: 3" in page.summary.text()
    assert "Colunas: 2" in page.summary.text()
    assert "Nulos: 0" in page.summary.text()
    assert page.profile_table.rowCount() == 2
    assert page.profile_table.item(0, 7).text() == "3.0"
    assert page.profile_table.item(1, 7).text() == "—"
    page.profile_table.selectRow(1)
    wait_signal(page.analysis_finished, lambda: page.is_analyzing)
    assert page.distribution_table.item(0, 0).text() == "a"
    assert page.distribution_table.item(0, 1).text() == "2"
    add(window, tmp_path, "second.csv")
    assert page.selector.currentIndex() == 0
    assert page.profile is not None
    page.selector.setCurrentIndex(1)
    assert page.profile is None
    assert not page.summary.text()
    assert not page.is_analyzing
    analyze(page)
    assert page.profile.name == "second.csv"
    window.datasets_page.dataset_list.setCurrentRow(1)
    window.datasets_page.remove_selected()
    assert page.selector.count() == 1
    assert page.profile is None
    window.datasets_page.remove_selected()
    assert page.selector.count() == 0
    assert not page.analyze_button.isEnabled()


def test_analysis_error(window, tmp_path, monkeypatch):
    page = window.analyses_page
    path = add(window, tmp_path)
    path.unlink()
    messages = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: messages.append(self.text()))
    analyze(page)
    assert messages and "arquivo original" in messages[0]
    assert page.profile is None
    assert page.analyze_button.isEnabled()


@pytest.mark.parametrize("close", [False, True])
def test_background_removal_and_shutdown(window, tmp_path, monkeypatch, close):
    from cyber_analyst.ui import analysis_worker
    page = window.analyses_page
    add(window, tmp_path)
    started, release = Event(), Event()
    threads = []
    original = analysis_worker.profile_dataset

    def controlled(dataset):
        threads.append(QThread.currentThread())
        started.set()
        assert release.wait(5)
        return original(dataset)

    monkeypatch.setattr(analysis_worker, "profile_dataset", controlled)
    page.analyze()
    try:
        assert started.wait(5)
        assert threads[0] != QApplication.instance().thread()
        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()
        window.datasets_page.remove_selected()
        assert page.selector.count() == 0
    finally:
        release.set()
    if close:
        thread = page._thread
        window.close()
        assert not thread.isRunning()
        QApplication.processEvents()
    else:
        wait_signal(page.analysis_finished, lambda: page.is_analyzing)
        assert page.profile is None
        assert not page.summary.text()
