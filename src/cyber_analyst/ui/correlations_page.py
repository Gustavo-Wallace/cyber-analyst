"""Correlação explícita de dois datasets da coleção compartilhada."""

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QFormLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from cyber_analyst.data.dataset_collection import DatasetCollection
from cyber_analyst.ui.correlation_worker import CorrelationWorker


class CorrelationsPage(QWidget):
    correlation_finished = Signal()
    result_completed = Signal(object)

    def __init__(self, collection: DatasetCollection):
        super().__init__()
        self.collection = collection
        self._thread = self._worker = None
        self._closing = False
        self._active = None
        self._pending = self._error = None
        self.result = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 32, 32, 32)
        title = QLabel("Correlações")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.dataset_a, self.dataset_b = QComboBox(), QComboBox()
        self.column_a, self.column_b = QComboBox(), QComboBox()
        for label, combo in (("Dataset A", self.dataset_a), ("Coluna A", self.column_a),
                             ("Dataset B", self.dataset_b), ("Coluna B", self.column_b)):
            combo.setMinimumWidth(0)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            form.addRow(label, combo)
        layout.addLayout(form)
        self.correlate_button = QPushButton("Correlacionar")
        layout.addWidget(self.correlate_button)
        self.status = QLabel()
        self.summary = QLabel()
        for label in (self.status, self.summary):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.preview = QTableWidget()
        self.preview.setMinimumHeight(160)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.horizontalHeader().setDefaultSectionSize(150)
        self.preview.setStyleSheet("QHeaderView::section { background-color: #25302a; color: #dce3df; padding: 5px; }")
        layout.addWidget(self.preview, 1)
        self.dataset_a.currentIndexChanged.connect(self._datasets_changed)
        self.dataset_b.currentIndexChanged.connect(self._datasets_changed)
        self.column_a.currentIndexChanged.connect(self._configuration_changed)
        self.column_b.currentIndexChanged.connect(self._configuration_changed)
        self.correlate_button.clicked.connect(self.start)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.refresh_datasets()

    @property
    def is_correlating(self):
        return self._thread is not None

    def _dataset(self, combo):
        path = combo.currentData()
        return self.collection.get(path) if path is not None and self.collection.contains(path) else None

    def _configuration(self):
        return (self._dataset(self.dataset_a), self._dataset(self.dataset_b),
                self.column_a.currentText(), self.column_b.currentText())

    @Slot()
    def refresh_datasets(self):
        for side, combo in enumerate((self.dataset_a, self.dataset_b)):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for dataset in self.collection.values():
                combo.addItem(dataset.name, dataset.path)
                combo.setItemData(combo.count() - 1, str(dataset.path), Qt.ItemDataRole.ToolTipRole)
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else min(side, combo.count() - 1))
            combo.blockSignals(False)
        if self.dataset_b.count() > 1 and self.dataset_a.currentData() == self.dataset_b.currentData():
            self.dataset_b.blockSignals(True)
            self.dataset_b.setCurrentIndex((self.dataset_a.currentIndex() + 1) % self.dataset_b.count())
            self.dataset_b.blockSignals(False)
        self._datasets_changed()

    @Slot()
    def _datasets_changed(self):
        for dataset_combo, column_combo in ((self.dataset_a, self.column_a), (self.dataset_b, self.column_b)):
            previous = column_combo.currentText()
            column_combo.blockSignals(True)
            column_combo.clear()
            dataset = self._dataset(dataset_combo)
            if dataset is not None:
                column_combo.addItems(dataset.columns)
                index = column_combo.findText(previous)
                if index >= 0:
                    column_combo.setCurrentIndex(index)
            column_combo.blockSignals(False)
        self._configuration_changed()

    @Slot()
    def _configuration_changed(self):
        self.result = None
        self.summary.clear()
        self.preview.setRowCount(0)
        self.preview.hide()
        self._update_controls()

    def _update_controls(self):
        a, b, ca, cb = self._configuration()
        valid = a is not None and b is not None and a is not b and ca in a.schema and cb in b.schema
        idle = not self.is_correlating and not self._closing
        for combo in (self.dataset_a, self.dataset_b, self.column_a, self.column_b):
            combo.setEnabled(idle and combo.count() > 0)
        self.correlate_button.setEnabled(idle and valid)
        self.status.setText("Correlacionando..." if self.is_correlating else
                            "Adicione pelo menos dois datasets." if len(self.collection) < 2 else
                            "Selecione datasets diferentes e suas colunas-chave." if not valid else
                            "Chaves textuais: trim de espaços; nulos não participam. Preview: até 100 linhas.")

    @Slot()
    def start(self):
        if not self.correlate_button.isEnabled():
            return
        self._configuration_changed()
        self._active = self._configuration()
        self._pending = self._error = None
        self._thread = QThread(self)
        self._worker = CorrelationWorker(*self._active)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.result.connect(self._receive_result)
        self._worker.failed.connect(self._receive_error)
        self._worker.finished.connect(self._thread.quit, Qt.ConnectionType.DirectConnection)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._finished)
        self._update_controls()
        self._thread.start()

    @Slot(object)
    def _receive_result(self, result):
        self._pending = result

    @Slot(str)
    def _receive_error(self, error):
        self._error = error

    @Slot()
    def _finished(self):
        self._thread.wait()
        self._thread.deleteLater()
        self._thread = self._worker = None
        current = self._configuration()
        valid = (not self._closing and current[0] is self._active[0]
                 and current[1] is self._active[1] and current[2:] == self._active[2:])
        if valid and self._error:
            message = QMessageBox(self)
            message.setWindowTitle("Não foi possível correlacionar")
            message.setIcon(QMessageBox.Icon.Warning)
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setText(self._error)
            message.exec()
        elif valid and self._pending is not None:
            self.result = self._pending
            self.result_completed.emit(self.result)
            s = self.result.summary
            self.summary.setText(
                f"A: {self.result.dataset_a.name} · B: {self.result.dataset_b.name}\n"
                f"Linhas A: {s.rows_a} · Linhas B: {s.rows_b}\n"
                f"Chaves únicas A: {s.unique_a} · Chaves únicas B: {s.unique_b}\n"
                f"Em comum: {s.common} · Somente A: {s.only_a} · Somente B: {s.only_b}\n"
                f"Linhas correlacionadas: {s.matched_rows}"
            )
            self.preview.setColumnCount(len(self.result.preview_columns))
            self.preview.setHorizontalHeaderLabels(self.result.preview_columns)
            self.preview.setRowCount(len(self.result.preview_rows))
            for row, values in enumerate(self.result.preview_rows):
                for column, value in enumerate(values):
                    self.preview.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))
            self.preview.show()
        self._pending = self._active = None
        self._update_controls()
        self.correlation_finished.emit()

    @Slot()
    def shutdown(self):
        self._closing = True
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
