import pytest
from PySide6.QtCore import Qt
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
    assert page.add_button.text() == "Adicionar CSV"
    assert page.empty_label.isVisible()
    assert not page.details.isVisible()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    page.add_button.click()
    assert page.dataset is None
    assert page.empty_label.isVisible()


def test_load_from_dialog(page, tmp_path, monkeypatch):
    path = tmp_path / "events.csv"
    content = 'id,host\n1,<b>alpha</b>\n2,\n'
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    page.add_button.click()
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


def test_replace_and_preserve_after_error(page, tmp_path, monkeypatch):
    first = tmp_path / "first.csv"
    first.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    second = tmp_path / "second.csv"
    second.write_text("host\nbeta\n", encoding="utf-8")
    page.load_path(first)
    page.load_path(second)
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
    assert len(messages) == 1
    assert "inexistente" in messages[0]
    assert page.dataset is previous
    assert page.summary.text() == summary
    assert page.preview_table.item(0, 0).text() == "beta"


def test_header_only_and_error_when_empty(page, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    page.load_path(tmp_path / "missing.csv")
    assert page.dataset is None
    assert page.empty_label.isVisible()
    path = tmp_path / "header.csv"
    path.write_text("id,host\n", encoding="utf-8")
    page.load_path(path)
    assert page.preview_table.rowCount() == 0
    assert page.preview_table.columnCount() == 2
    assert page.schema_table.rowCount() == 2
    assert page.details.isVisible()
