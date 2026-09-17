from threading import Event

import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QAbstractItemView

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
    widget.navigation.button(3).click()
    yield widget
    widget.close()
    app.processEvents()


def add(window, tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    page = window.datasets_page
    page.load_path(path)
    wait(page.loading_finished, lambda: page.is_loading)


def test_configuration_success_and_removal(window, tmp_path):
    page = window.correlations_page
    assert page.collection is window.collection
    assert not page.correlate_button.isEnabled()
    add(window, tmp_path, "users.csv", "id,email\n1,a\n2,b\n3,c\n")
    assert not page.correlate_button.isEnabled()
    add(window, tmp_path, "leaks.csv", "email,source\nb,leak_a\nc,leak_b\nx,leak_c\n")
    assert page.dataset_a.count() == page.dataset_b.count() == 2
    assert page.column_a.count() == page.column_b.count() == 2
    page.column_a.setCurrentText("email")
    assert page.correlate_button.isEnabled()
    page.correlate_button.click()
    assert page.is_correlating and not page.correlate_button.isEnabled()
    assert page.status.text() == "Correlacionando..."
    wait(page.correlation_finished, lambda: page.is_correlating)
    assert page.result.summary.common == 2
    assert "Em comum: 2" in page.summary.text()
    assert page.preview.rowCount() == 2
    assert page.preview.horizontalHeaderItem(0).text() == "A.id"
    assert page.preview.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    page.column_a.setCurrentText("id")
    assert page.result is None and not page.summary.text()
    page.dataset_b.setCurrentIndex(0)
    assert not page.correlate_button.isEnabled()
    page.dataset_b.setCurrentIndex(1)
    window.datasets_page.remove_selected()
    assert page.dataset_a.count() == 1
    assert not page.correlate_button.isEnabled()


def test_type_error(window, tmp_path, monkeypatch):
    add(window, tmp_path, "a.csv", "key\n1\n")
    add(window, tmp_path, "b.csv", "key\nx\n")
    page = window.correlations_page
    messages = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: messages.append(self.text()))
    page.start()
    wait(page.correlation_finished, lambda: page.is_correlating)
    assert messages and "incompatíveis" in messages[0]
    assert page.result is None
    assert page.correlate_button.isEnabled()


@pytest.mark.parametrize("close", [False, True])
def test_background_removal_shutdown(window, tmp_path, monkeypatch, close):
    from cyber_analyst.ui import correlation_worker
    add(window, tmp_path, "a.csv", "key\n1\n")
    add(window, tmp_path, "b.csv", "key\n1\n")
    page = window.correlations_page
    started, release = Event(), Event()
    threads = []
    original = correlation_worker.correlate

    def controlled(*args):
        threads.append(QThread.currentThread())
        started.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(correlation_worker, "correlate", controlled)
    page.start()
    try:
        assert started.wait(5)
        assert threads[0] != QApplication.instance().thread()
        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()
        window.datasets_page.remove_selected()
    finally:
        release.set()
    if close:
        thread = page._thread
        window.close()
        assert not thread.isRunning()
        QApplication.processEvents()
    else:
        wait(page.correlation_finished, lambda: page.is_correlating)
        assert page.result is None and not page.summary.text()
