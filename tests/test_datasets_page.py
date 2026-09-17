import pytest
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QAbstractItemView

from cyber_analyst.ui.datasets_page import DatasetsPage


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    widget = DatasetsPage()
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def test_initial_and_cancel(page, monkeypatch):
    assert page.dataset_list.count() == 0
    assert page.add_button.isEnabled()
    assert not page.remove_button.isEnabled()
    assert page.add_button.text() == "Adicionar CSV"
    assert page.empty_label.isVisible()
    assert not page.details.isVisible()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([], ""))
    page.add_button.click()
    wait_for_load(page)
    assert page.dataset is None
    assert page.empty_label.isVisible()


def test_load_from_dialog(page, tmp_path, monkeypatch):
    path = tmp_path / "events.csv"
    content = 'id,host\n1,<b>alpha</b>\n2,\n'
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([str(path)], ""))
    page.add_button.click()
    wait_for_load(page)
    assert page.dataset.name == "events.csv"
    assert str(path) in page.summary.text()
    assert "Nome: events.csv" in page.summary.text()
    assert "Linhas: 2    Colunas: 2" in page.summary.text()
    assert page.summary.textFormat() == Qt.TextFormat.PlainText
    assert page.schema_table.item(0, 0).text() == "id"
    assert page.schema_table.item(0, 1).text() == "Int64"
    assert page.schema_table.item(1, 1).text() == "String"
    assert page.preview_table.horizontalHeaderItem(1).text() == "host"
    assert page.preview_table.item(0, 1).text() == "<b>alpha</b>"
    assert page.preview_table.item(1, 1).text() == ""
    for table in (page.schema_table, page.preview_table):
        assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
        assert not table.isSortingEnabled()
        assert table.horizontalHeader().isVisible()
    assert page.details.isVisible()
    assert not page.empty_label.isVisible()
    assert path.read_text(encoding="utf-8") == content


def test_selection_and_preserve_after_error(page, tmp_path, monkeypatch):
    first = tmp_path / "first.csv"
    first.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    second = tmp_path / "second.csv"
    second.write_text("host\nbeta\n", encoding="utf-8")
    page.load_path(first)
    wait_for_load(page)
    page.load_path(second)
    wait_for_load(page)
    page.dataset_list.setCurrentRow(1)
    assert page.dataset.name == "second.csv"
    assert "first.csv" not in page.summary.text()
    assert page.preview_table.rowCount() == 1
    assert page.preview_table.columnCount() == 1
    assert page.schema_table.rowCount() == 1
    assert page.preview_table.item(0, 0).text() == "beta"
    previous = page.dataset
    summary = page.summary.text()
    messages = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: messages.append(self.text()))
    page.load_path(tmp_path / "missing.csv")
    wait_for_load(page)
    assert len(messages) == 1
    assert "inexistente" in messages[0]
    assert page.dataset is previous
    assert page.summary.text() == summary
    assert page.preview_table.item(0, 0).text() == "beta"


def test_header_only_and_error_when_empty(page, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    page.load_path(tmp_path / "missing.csv")
    wait_for_load(page)
    assert page.dataset is None
    assert page.empty_label.isVisible()
    path = tmp_path / "header.csv"
    path.write_text("id,host\n", encoding="utf-8")
    page.load_path(path)
    wait_for_load(page)
    assert page.preview_table.rowCount() == 0
    assert page.preview_table.columnCount() == 2
    assert page.schema_table.rowCount() == 2
    assert page.details.isVisible()


def wait_for_load(page):
    if not page.is_loading:
        return
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    page.loading_finished.connect(loop.quit)
    timer.start(10000)
    loop.exec()
    page.loading_finished.disconnect(loop.quit)
    assert not page.is_loading, "Loading did not finish"


def test_multiple_selection_duplicates_and_removal(page, tmp_path, monkeypatch):
    from cyber_analyst.ui import csv_worker
    original = csv_worker.load_csv
    calls = []

    def tracked(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(csv_worker, "load_csv", tracked)
    paths = []
    for index in range(2):
        path = tmp_path / f"{index}.csv"
        path.write_text(f"id\n{index}\n", encoding="utf-8")
        paths.append(path)
    page.load_paths([*paths, paths[0]])
    assert page.is_loading
    assert not page.add_button.isEnabled()
    assert page.loading_label.isVisible()
    page.load_paths(paths)  # A segunda operação deve ser ignorada.
    wait_for_load(page)
    assert len(calls) == 2
    assert len(page.collection) == page.dataset_list.count() == 2
    assert page.dataset.path == paths[0]
    page.dataset_list.setCurrentRow(1)
    assert page.preview_table.item(0, 0).text() == "1"
    page.load_paths([paths[0]])
    assert not page.is_loading
    assert page.dataset.path == paths[0]
    assert len(calls) == 2
    page.remove_button.click()
    assert page.dataset.path == paths[1]
    assert len(page.collection) == 1
    page.remove_button.click()
    assert page.dataset is None
    assert page.empty_label.isVisible()
    assert not page.details.isVisible()
    assert not page.remove_button.isEnabled()
    assert all(path.exists() for path in paths)
    page.load_path(paths[0])
    wait_for_load(page)
    assert len(page.collection) == 1


def test_partial_failure(page, tmp_path, monkeypatch):
    paths = [tmp_path / name for name in ("first.csv", "invalid.csv", "last.csv")]
    paths[0].write_text("id\n1\n", encoding="utf-8")
    paths[1].touch()
    paths[2].write_text("id\n2\n", encoding="utf-8")
    messages = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: messages.append(self.text()))
    page.load_paths(paths)
    wait_for_load(page)
    assert [d.path for d in page.collection.values()] == [paths[0], paths[2]]
    assert len(messages) == 1
    assert "invalid.csv" in messages[0]
    assert page.add_button.isEnabled()


def test_background_thread_and_shutdown(page, tmp_path, monkeypatch):
    from threading import Event
    from PySide6.QtCore import QThread
    from cyber_analyst.ui import csv_worker

    started = Event()
    release = Event()
    threads = []
    original = csv_worker.load_csv
    path = tmp_path / "events.csv"
    path.write_text("id\n1\n", encoding="utf-8")

    def controlled(path):
        threads.append(QThread.currentThread())
        started.set()
        assert release.wait(5)
        return original(path)

    monkeypatch.setattr(csv_worker, "load_csv", controlled)
    page.load_path(path)
    assert started.wait(5)
    assert threads[0] != QApplication.instance().thread()
    # Um callback Qt deve ser atendido enquanto o worker aguarda.
    loop = QEventLoop()
    responsive = []
    QTimer.singleShot(0, lambda: (responsive.append(True), loop.quit()))
    loop.exec()
    assert responsive
    thread = page._thread
    release.set()
    page.close()
    assert not thread.isRunning()
    QApplication.processEvents()
