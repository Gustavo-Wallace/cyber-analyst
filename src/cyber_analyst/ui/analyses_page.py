"""Perfil e distribuições sob demanda dos datasets da sessão."""

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from cyber_analyst.analysis.models import DatasetProfile
from cyber_analyst.data.dataset_collection import DatasetCollection
from cyber_analyst.ui.analysis_worker import AnalysisWorker


class AnalysesPage(QWidget):
    analysis_finished = Signal()
    profile_completed = Signal(object, object)

    def __init__(self, collection: DatasetCollection) -> None:
        super().__init__()
        self.collection = collection
        self._thread = None
        self._worker = None
        self._closing = False
        self._active_dataset = None
        self._result = None
        self._error = None
        self.profile = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        title = QLabel("Análises")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        actions = QHBoxLayout()
        self.selector = QComboBox()
        self.selector.setMinimumWidth(0)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.analyze_button = QPushButton("Analisar")
        actions.addWidget(self.selector, 1)
        actions.addWidget(self.analyze_button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.profile_table = QTableWidget(0, 10)
        self.profile_table.setHorizontalHeaderLabels([
            "Coluna", "Tipo", "Nulos", "Nulos %", "Únicos", "Mínimo", "Máximo",
            "Média", "Mediana", "Desvio padrão",
        ])
        self.column_label = QLabel("Selecione uma coluna para consultar os top valores.")
        self.column_label.setTextFormat(Qt.TextFormat.PlainText)
        self.column_label.setWordWrap(True)
        self.distribution_table = QTableWidget(0, 3)
        self.distribution_table.setHorizontalHeaderLabels(["Valor", "Contagem", "%"])
        for table in (self.profile_table, self.distribution_table):
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.horizontalHeader().setDefaultSectionSize(120)
            table.setStyleSheet("QHeaderView::section { background-color: #25302a; color: #dce3df; padding: 5px; }")
        layout.addWidget(self.profile_table, 2)
        layout.addWidget(self.column_label)
        layout.addWidget(self.distribution_table, 1)
        self.selector.currentIndexChanged.connect(self._selection_changed)
        self.analyze_button.clicked.connect(self.analyze)
        self.profile_table.itemSelectionChanged.connect(self._column_selected)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.refresh_datasets()

    @property
    def is_analyzing(self) -> bool:
        return self._thread is not None

    def selected_dataset(self):
        path = self.selector.currentData()
        return self.collection.get(path) if path is not None and self.collection.contains(path) else None

    @Slot()
    def refresh_datasets(self) -> None:
        previous = self.selected_dataset()
        previous_path = self.selector.currentData()
        self.selector.blockSignals(True)
        self.selector.clear()
        for dataset in self.collection.values():
            self.selector.addItem(dataset.name, dataset.path)
            self.selector.setItemData(self.selector.count() - 1, str(dataset.path), Qt.ItemDataRole.ToolTipRole)
        index = self.selector.findData(previous_path)
        if index >= 0:
            self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)
        if previous is not self.selected_dataset() or self.profile is None:
            self._selection_changed()
        self._update_controls()

    def _update_controls(self) -> None:
        enabled = not self.is_analyzing and not self._closing
        self.selector.setEnabled(enabled and self.selector.count() > 0)
        self.analyze_button.setEnabled(enabled and self.selected_dataset() is not None)
        self.profile_table.setEnabled(enabled)

    @Slot()
    def _selection_changed(self) -> None:
        self.profile = None
        self.summary.clear()
        self.profile_table.setRowCount(0)
        self.distribution_table.setRowCount(0)
        self.profile_table.hide()
        self.distribution_table.hide()
        self.column_label.hide()
        self.status.setText("Analisando..." if self.is_analyzing else
                            "Clique em Analisar para gerar o perfil." if self.selected_dataset() else
                            "Adicione um dataset na página Datasets primeiro.")
        self._update_controls()

    @Slot()
    def analyze(self) -> None:
        dataset = self.selected_dataset()
        if dataset is not None and not self.is_analyzing:
            self._selection_changed()
            self._start(dataset)

    @Slot()
    def _column_selected(self) -> None:
        row = self.profile_table.currentRow()
        if self.profile is None or row < 0 or self.is_analyzing:
            return
        dataset = self.selected_dataset()
        if dataset is not None:
            column = self.profile.columns[row].name
            self.column_label.setText(f"Top valores: {column} (nulos incluídos)")
            self.distribution_table.setRowCount(0)
            self.distribution_table.show()
            self._start(dataset, column)

    def _start(self, dataset, column=None) -> None:
        self._active_dataset = dataset
        self._result = self._error = None
        self._thread = QThread(self)
        self._worker = AnalysisWorker(dataset, column)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.result.connect(self._receive_result)
        self._worker.failed.connect(self._receive_error)
        self._worker.finished.connect(self._thread.quit, Qt.ConnectionType.DirectConnection)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._finished)
        self.status.setText("Analisando...")
        self._update_controls()
        self._thread.start()

    @Slot(object)
    def _receive_result(self, result) -> None:
        self._result = result

    @Slot(str)
    def _receive_error(self, error: str) -> None:
        self._error = error

    @Slot()
    def _finished(self) -> None:
        self._thread.wait()
        self._thread.deleteLater()
        self._thread = self._worker = None
        valid = not self._closing and self.selected_dataset() is self._active_dataset
        if valid and self._error:
            message = QMessageBox(self)
            message.setWindowTitle("Não foi possível analisar")
            message.setIcon(QMessageBox.Icon.Warning)
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setText(self._error)
            message.exec()
        elif valid and isinstance(self._result, DatasetProfile):
            self.profile = self._result
            self.profile_completed.emit(self._active_dataset, self.profile)
            self.summary.setText(f"{self.profile.name}\nLinhas: {self.profile.row_count}    "
                                 f"Colunas: {self.profile.column_count}    Nulos: {self.profile.null_count}")
            self.profile_table.setRowCount(len(self.profile.columns))
            for row, column in enumerate(self.profile.columns):
                values = (column.name, column.dtype, column.null_count, column.null_percentage,
                          column.unique_count, column.minimum, column.maximum, column.mean,
                          column.median, column.std)
                for col, value in enumerate(values):
                    self.profile_table.setItem(row, col, QTableWidgetItem("—" if value is None else str(value)))
            self.profile_table.show()
            self.column_label.setText("Selecione uma coluna para consultar os top valores.")
            self.column_label.show()
        elif valid and self._result is not None:
            self.distribution_table.setRowCount(len(self._result.values))
            for row, frequency in enumerate(self._result.values):
                for col, value in enumerate((frequency.value, frequency.count, frequency.percentage)):
                    self.distribution_table.setItem(row, col, QTableWidgetItem("(nulo)" if value is None else str(value)))
        self._result = self._active_dataset = None
        self.status.setText("Perfil calculado. Únicos incluem nulos; desvio padrão amostral." if self.profile else
                            "Clique em Analisar para gerar o perfil." if self.selected_dataset() else
                            "Adicione um dataset na página Datasets primeiro.")
        self._update_controls()
        self.analysis_finished.emit()

    @Slot()
    def shutdown(self) -> None:
        self._closing = True
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)
