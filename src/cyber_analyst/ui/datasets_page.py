"""Visualização de um único CSV usando o motor de ingestão existente."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from cyber_analyst.data.csv_loader import DatasetLoadError, load_csv
from cyber_analyst.data.dataset import Dataset


class DatasetsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.dataset: Dataset | None = None
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
        actions.addStretch()
        layout.addLayout(actions)
        self.empty_label = QLabel("Nenhum dataset carregado.")
        layout.addWidget(self.empty_label)

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
        path, _ = QFileDialog.getOpenFileName(self, "Adicionar CSV", "", "Arquivos CSV (*.csv)")
        if path:
            self.load_path(path)

    def load_path(self, path: str | Path) -> None:
        try:
            dataset = load_csv(path)
        except DatasetLoadError as exc:
            message = QMessageBox(self)
            message.setWindowTitle("Não foi possível carregar o CSV")
            message.setIcon(QMessageBox.Icon.Warning)
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setText(str(exc))
            message.exec()
            return

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
