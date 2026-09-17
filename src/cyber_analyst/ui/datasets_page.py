"""Datasets da sessão e coordenação do carregamento assíncrono."""

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QListWidget, QListWidgetItem, QApplication,
)

from cyber_analyst.data.dataset_collection import DatasetCollection
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.ui.csv_worker import CsvWorker


class DatasetsPage(QWidget):
    loading_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.dataset: Dataset | None = None
        self.collection = DatasetCollection()
        self._thread = None
        self._worker = None
        self._closing = False
        self._errors: list[str] = []
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)
        title = QLabel("Datasets")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        actions = QHBoxLayout()
        self.add_button = QPushButton("Adicionar CSV")
        self.add_button.setStyleSheet(
            "QPushButton { background-color: #253d30; color: #9bcbae; }"
        )
        self.add_button.clicked.connect(self.choose_csv)
        actions.addWidget(self.add_button)
        self.remove_button = QPushButton("Remover")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_selected)
        actions.addWidget(self.remove_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.empty_label = QLabel("Nenhum dataset carregado.")
        layout.addWidget(self.empty_label)
        self.loading_label = QLabel("Carregando...")
        self.loading_label.hide()
        layout.addWidget(self.loading_label)
        self.dataset_list = QListWidget()
        self.dataset_list.setStyleSheet(
            "QListWidget::item:selected { background-color: #253d30; color: #9bcbae; }"
        )
        self.dataset_list.setMaximumHeight(110)
        self.dataset_list.hide()
        self.dataset_list.currentRowChanged.connect(self._selection_changed)
        layout.addWidget(self.dataset_list)

        self.details = QScrollArea()
        self.details.setWidgetResizable(True)
        self.details.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        details_layout = QVBoxLayout(content)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(12)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(self.summary)
        details_layout.addWidget(QLabel("Schema"))
        self.schema_table = QTableWidget()
        self.preview_table = QTableWidget()
        for table in (self.schema_table, self.preview_table):
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSortingEnabled(False)
            table.setMinimumHeight(140)
            table.horizontalHeader().setDefaultSectionSize(140)
            table.setStyleSheet(
                "QHeaderView::section { background-color: #25302a; color: #dce3df; padding: 5px; }"
                "QTableWidget { gridline-color: #35443b; }"
            )
        details_layout.addWidget(self.schema_table)
        details_layout.addWidget(QLabel("Preview — até 100 linhas"))
        details_layout.addWidget(self.preview_table, 1)
        self.details.setWidget(content)
        self.details.hide()
        layout.addWidget(self.details, 1)

    def choose_csv(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Adicionar CSV(s)", "", "Arquivos CSV (*.csv)")
        if paths:
            self.load_paths(paths)

    def load_path(self, path: str | Path) -> None:
        self.load_paths([path])

    @property
    def is_loading(self) -> bool:
        return self._thread is not None

    def load_paths(self, paths: list[str | Path]) -> None:
        if self.is_loading or self._closing:
            return
        pending = []
        seen = set()
        for path in paths:
            resolved = Path(path).resolve()
            if self.collection.contains(resolved):
                for row in range(self.dataset_list.count()):
                    if self.dataset_list.item(row).data(Qt.ItemDataRole.UserRole) == resolved:
                        self.dataset_list.setCurrentRow(row)
                        break
            elif resolved not in seen:
                seen.add(resolved)
                pending.append(resolved)
        if not pending:
            return
        self._errors = []
        self.add_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.loading_label.show()
        self._thread = QThread(self)
        self._worker = CsvWorker(pending)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.loaded.connect(self._add_dataset)
        self._worker.failed.connect(self._record_error)
        self._worker.finished.connect(self._thread.quit, Qt.ConnectionType.DirectConnection)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._load_finished)
        self._thread.start()

    @Slot(object)
    def _add_dataset(self, dataset: Dataset) -> None:
        if self._closing or not self.collection.add(dataset):
            return
        item = QListWidgetItem(dataset.name)
        item.setToolTip(str(dataset.path))
        item.setData(Qt.ItemDataRole.UserRole, dataset.path.resolve())
        self.dataset_list.addItem(item)
        self.dataset_list.show()
        if self.dataset_list.currentRow() < 0:
            self.dataset_list.setCurrentRow(0)

    @Slot(str, str)
    def _record_error(self, path: str, error: str) -> None:
        self._errors.append(f"{path}\n{error}")

    @Slot()
    def _load_finished(self) -> None:
        self._thread.wait()
        self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.loading_label.hide()
        self.add_button.setEnabled(not self._closing)
        self.remove_button.setEnabled(self.dataset is not None and not self._closing)
        if self._errors and not self._closing:
            message = QMessageBox(self)
            message.setWindowTitle("Falha ao carregar CSVs")
            message.setIcon(QMessageBox.Icon.Warning)
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setText("Alguns arquivos não puderam ser carregados:\n\n" + "\n\n".join(self._errors))
            message.exec()
        self.loading_finished.emit()

    @Slot(int)
    def _selection_changed(self, row: int) -> None:
        self.remove_button.setEnabled(row >= 0 and not self.is_loading)
        if row < 0:
            self.dataset = None
            self.summary.clear()
            self.schema_table.setRowCount(0)
            self.preview_table.setRowCount(0)
            self.details.hide()
            self.empty_label.show()
            self.dataset_list.setVisible(bool(len(self.collection)))
            return
        path = self.dataset_list.item(row).data(Qt.ItemDataRole.UserRole)
        self._show_dataset(self.collection.get(path))

    def remove_selected(self) -> None:
        row = self.dataset_list.currentRow()
        if row < 0 or self.is_loading:
            return
        path = self.dataset_list.item(row).data(Qt.ItemDataRole.UserRole)
        self.collection.remove(path)
        self.dataset_list.takeItem(row)
        self.dataset_list.setCurrentRow(min(row, self.dataset_list.count() - 1))

    @Slot()
    def shutdown(self) -> None:
        self._closing = True
        if self._thread is not None:
            self._thread.requestInterruption()
            self._thread.quit()
            self._thread.wait()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def _show_dataset(self, dataset: Dataset) -> None:
        self.summary.setText(
            f"Nome: {dataset.name}\nCaminho: {dataset.path}\n"
            f"Linhas: {dataset.row_count}    Colunas: {dataset.column_count}"
        )
        self.schema_table.clear()
        self.schema_table.setColumnCount(2)
        self.schema_table.setHorizontalHeaderLabels(["Coluna", "Tipo"])
        self.schema_table.setRowCount(dataset.column_count)
        for row, (name, dtype) in enumerate(dataset.schema.items()):
            self.schema_table.setItem(row, 0, QTableWidgetItem(name))
            self.schema_table.setItem(row, 1, QTableWidgetItem(str(dtype)))

        self.preview_table.clear()
        self.preview_table.setColumnCount(dataset.preview.width)
        self.preview_table.setRowCount(dataset.preview.height)
        self.preview_table.setHorizontalHeaderLabels(dataset.preview.columns)
        for row, values in enumerate(dataset.preview.iter_rows()):
            for column, value in enumerate(values):
                self.preview_table.setItem(
                    row, column, QTableWidgetItem("" if value is None else str(value))
                )
        self.dataset = dataset
        self.empty_label.hide()
        self.details.show()
