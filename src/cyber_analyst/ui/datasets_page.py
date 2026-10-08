"""Simple source-data explorer using the committed loader and bounded previews."""

from pathlib import Path
from html import escape

from PySide6.QtCore import Qt, QThread, Signal, Slot, QSize
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QMessageBox, QGridLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QListWidget, QListWidgetItem, QApplication, QLineEdit, QComboBox,
    QToolButton, QHeaderView, QSizePolicy,
)

from cyber_analyst.data.dataset_collection import DatasetCollection
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.ui.csv_worker import CsvWorker
from .data_search_worker import DataSearchRunner
from .count_labels import count_label
from .theme import SPACE, label, role, table_style

MAX_PREVIEW_ROWS = 100


def value_item(value):
    text = '' if value is None else str(value)
    item = QTableWidgetItem(text)
    item.setToolTip('<qt>' + escape(text).replace('\n', '<br>') + '</qt>' if value is not None else '(null)')
    item.setData(Qt.ItemDataRole.UserRole, value)
    return item


class DatasetsPage(QWidget):
    loading_finished = Signal()
    collection_changed = Signal()

    def __init__(self, collection: DatasetCollection | None = None) -> None:
        super().__init__()
        self.dataset: Dataset | None = None
        self.collection = collection if collection is not None else DatasetCollection()
        self._thread = None
        self._worker = None
        self._closing = False
        self._errors: list[str] = []
        self._session = None
        self._search_token = 0
        self._search_result = None
        self._searching = False
        self._collection_snapshot = ()
        self.search_runner = DataSearchRunner()
        self.search_runner.completed.connect(self._search_completed)
        self.search_runner.failed.connect(self._search_failed)
        self.destroyed.connect(self.search_runner.shutdown)
        self.destroyed.connect(self.search_runner.deleteLater)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE['md'], SPACE['sm'], SPACE['md'], SPACE['md'])
        layout.setSpacing(SPACE['sm'])
        title = label('Data', 'page_title')
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        actions = QHBoxLayout()
        actions.addWidget(label('Browse your datasets or find a value.', 'caption'), 1)
        self.add_button = QPushButton('Add datasets')
        role(self.add_button, 'primary')
        self.add_button.clicked.connect(self.choose_csv)
        actions.addWidget(self.add_button)
        layout.addLayout(actions)
        self.loading_label = label('Loading datasets...', 'caption')
        self.loading_label.hide()
        layout.addWidget(self.loading_label)
        self.empty_state = QWidget()
        empty = QVBoxLayout(self.empty_state)
        empty.addStretch()
        self.empty_label = label('Add datasets', 'section_title')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(self.empty_label)
        supporting = label('Choose CSV files to browse your data and start an investigation.', 'caption')
        supporting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(supporting)
        empty.addStretch()
        layout.addWidget(self.empty_state, 1)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACE['sm'])
        collection_header = QHBoxLayout()
        self.readiness = label('', 'caption')
        collection_header.addWidget(self.readiness, 1)
        self.remove_button = QPushButton('Unload selected')
        self.remove_button.setToolTip('Remove from this session; the source file is not deleted.')
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_selected)
        collection_header.addWidget(self.remove_button)
        body.addLayout(collection_header)
        self.dataset_list = QListWidget()
        self.dataset_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.dataset_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.dataset_list.setMinimumHeight(52)
        self.dataset_list.setMaximumHeight(112)
        self.dataset_list.currentRowChanged.connect(self._selection_changed)
        body.addWidget(self.dataset_list)

        self.search_controls = QWidget()
        self.search_grid = QGridLayout(self.search_controls)
        self.search_grid.setContentsMargins(0, 0, 0, 0)
        self.search_grid.setSpacing(SPACE['sm'])
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText('Search dataset values')
        self.search_field.setClearButtonEnabled(True)
        self.search_field.setMinimumWidth(0)
        self.search_field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.search_field.returnPressed.connect(self.search_data)
        self.search_field.textChanged.connect(self._query_changed)
        self.search_scope = QComboBox()
        self.search_scope.addItems(('All datasets', 'Selected dataset'))
        self.search_scope.setToolTip('Search raw values in all loaded datasets or only the selected dataset.')
        self.search_scope.currentIndexChanged.connect(self._query_changed)
        self.search_button = QPushButton('Search')
        self.search_button.clicked.connect(self.search_data)
        self._layout_search(False)
        body.addWidget(self.search_controls)
        self.search_status = label('', 'caption')
        self.search_status.hide()
        body.addWidget(self.search_status)
        self.hits_table = QTableWidget(0, 4)
        self.hits_table.setHorizontalHeaderLabels(('Dataset', 'Row', 'Column', 'Matching value'))
        self._configure_table(self.hits_table)
        self.hits_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.hits_table.setColumnWidth(1, 60)
        self.hits_table.setColumnWidth(2, 140)
        self.hits_table.setMaximumHeight(184)
        self.hits_table.setMinimumHeight(100)
        self.hits_table.itemClicked.connect(self._open_hit)
        self.hits_table.itemActivated.connect(self._open_hit)
        self.hits_table.hide()
        body.addWidget(self.hits_table)

        self.details = QWidget()
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(SPACE['sm'])
        self.summary = label('', 'section_title')
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(self.summary)
        preview_header = QHBoxLayout()
        self.preview_label = label('', 'caption')
        preview_header.addWidget(self.preview_label, 1)
        self.preview_button = QPushButton('Show preview')
        self.preview_button.clicked.connect(self._reset_preview)
        self.preview_button.hide()
        preview_header.addWidget(self.preview_button)
        details_layout.addLayout(preview_header)
        self.schema_table = QTableWidget()
        self.preview_table = QTableWidget()
        for table in (self.schema_table, self.preview_table):
            self._configure_table(table)
        self.preview_table.setMinimumHeight(140)
        self.preview_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        details_layout.addWidget(self.preview_table, 1)
        self.schema_toggle = QToolButton()
        self.schema_toggle.setText('Column details')
        self.schema_toggle.setCheckable(True)
        self.schema_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.schema_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.schema_toggle.toggled.connect(self._toggle_schema)
        details_layout.addWidget(self.schema_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.schema_table.setMaximumHeight(150)
        self.schema_table.hide()
        details_layout.addWidget(self.schema_table)
        details_layout.addStretch()
        body.addWidget(self.details, 1)
        layout.addWidget(self.body, 1)
        self.body.hide()
        self.refresh_collection()

    @staticmethod
    def _configure_table(table):
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.horizontalHeader().setDefaultSectionSize(160)
        table.horizontalHeader().setStretchLastSection(True)
        table_style(table)

    def _layout_search(self, compact):
        self.search_grid.addWidget(self.search_field, 0, 0, 1, 2 if compact else 1)
        self.search_grid.addWidget(self.search_scope, 1 if compact else 0, 0 if compact else 1)
        self.search_grid.addWidget(self.search_button, 1 if compact else 0, 1 if compact else 2)
        self.search_grid.setColumnStretch(0, 1)

    def resizeEvent(self, event):
        self._layout_search(self.width() < 650)
        self.dataset_list.setMaximumHeight(60 if self.width() < 650 else 112)
        super().resizeEvent(event)

    def minimumSizeHint(self):
        return QSize(0, 0)

    def bind_session(self, session):
        self._session = session
        session.changed.connect(self._update_readiness)
        self._update_readiness()

    def _update_readiness(self):
        datasets = self.collection.values()
        suffix = 'loaded' if self._session is not None and self._session.result is not None else 'ready'
        self.readiness.setText(count_label(len(datasets), 'dataset') + ' | ' +
                               count_label(sum(d.row_count for d in datasets), 'row', number_format=',') + ' ' + suffix)

    def _append_item(self, dataset):
        text = dataset.name + '\n' + count_label(dataset.row_count, 'row', number_format=',') + ' | ' + count_label(dataset.column_count, 'column')
        item = QListWidgetItem(text)
        item.setSizeHint(QSize(0, 46))
        item.setToolTip(escape(str(dataset.path)))
        item.setData(Qt.ItemDataRole.UserRole, dataset.path.resolve())
        self.dataset_list.addItem(item)

    def refresh_collection(self):
        """Reflect the shared collection without new loads/invalidation semantics."""
        datasets = self.collection.values()
        if len(datasets) == len(self._collection_snapshot) and all(
            current is previous for current, previous in zip(datasets, self._collection_snapshot)
        ):
            return
        self._collection_snapshot = datasets
        selected = self.dataset.path.resolve() if self.dataset else None
        previous_row = self.dataset_list.currentRow()
        self._invalidate_search()
        self.dataset_list.blockSignals(True)
        self.dataset_list.clear()
        for dataset in datasets:
            self._append_item(dataset)
        paths = [d.path.resolve() for d in datasets]
        row = paths.index(selected) if selected in paths else min(max(0, previous_row), len(paths)-1)
        self.dataset_list.setCurrentRow(row)
        self.dataset_list.blockSignals(False)
        self._selection_changed(row)
        self._update_readiness()

    def _toggle_schema(self, checked):
        self.schema_table.setVisible(checked)
        self.schema_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def choose_csv(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add datasets', '', 'CSV files (*.csv)')
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
        self.refresh_collection()
        self.collection_changed.emit()

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
        if self.search_scope.currentIndex() == 1:
            self._invalidate_search()
        self.remove_button.setEnabled(row >= 0 and not self.is_loading)
        if row < 0:
            self.dataset = None
            self.summary.clear()
            self.schema_table.setRowCount(0)
            self.preview_table.setRowCount(0)
            self.details.hide()
            self.body.setVisible(bool(len(self.collection)))
            self.empty_state.setVisible(not len(self.collection))
            return
        path = self.dataset_list.item(row).data(Qt.ItemDataRole.UserRole)
        self._show_dataset(self.collection.get(path))

    def remove_selected(self) -> None:
        row = self.dataset_list.currentRow()
        if row < 0 or self.is_loading:
            return
        path = self.dataset_list.item(row).data(Qt.ItemDataRole.UserRole)
        self.collection.remove(path)
        self.refresh_collection()
        self.collection_changed.emit()

    @Slot()
    def shutdown(self) -> None:
        self._closing = True
        self.search_runner.shutdown()
        if self._thread is not None:
            self._thread.requestInterruption()
            self._thread.quit()
            self._thread.wait()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def _show_dataset(self, dataset: Dataset) -> None:
        self.summary.setText(
            dataset.name + '\n' + count_label(dataset.row_count, 'row', number_format=',') + ' | ' +
            count_label(dataset.column_count, 'column')
        )
        self.summary.setToolTip(escape(str(dataset.path)))
        self.schema_table.clear()
        self.schema_table.setColumnCount(2)
        self.schema_table.setHorizontalHeaderLabels(['Column', 'Type'])
        self.schema_table.setRowCount(dataset.column_count)
        for row, (name, dtype) in enumerate(dataset.schema.items()):
            self.schema_table.setItem(row, 0, value_item(name))
            self.schema_table.setItem(row, 1, value_item(str(dtype)))
        self.dataset = dataset
        self._reset_preview()
        self.empty_state.hide()
        self.body.show()
        self.details.show()
        self._update_readiness()

    def _render_rows(self, columns, rows, row_indices):
        self.preview_table.clear()
        self.preview_table.setColumnCount(len(columns))
        self.preview_table.setRowCount(len(rows))
        self.preview_table.setHorizontalHeaderLabels(columns)
        self.preview_table.setVerticalHeaderLabels([str(i+1) for i in row_indices])
        self.preview_table.setMaximumHeight(max(140, min(480,
            self.preview_table.horizontalHeader().sizeHint().height() +
            self.preview_table.verticalHeader().defaultSectionSize()*len(rows) + 20)))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.preview_table.setItem(row, column, value_item(value))

    def _reset_preview(self):
        if self.dataset is None:
            return
        preview = self.dataset.preview.head(MAX_PREVIEW_ROWS)
        self._render_rows(tuple(preview.columns), tuple(preview.iter_rows()), range(preview.height))
        self.preview_label.setText(f'Showing first {preview.height:,} of {self.dataset.row_count:,} rows'
                                  if preview.height < self.dataset.row_count else count_label(preview.height, 'row', number_format=',') + ' shown')
        self.preview_button.hide()

    def _invalidate_search(self):
        self._search_token += 1
        self.search_runner.cancel()
        self._search_result = None
        self._searching = False
        self.hits_table.clearContents()
        self.hits_table.setRowCount(0)
        self.hits_table.hide()
        self.search_status.hide()
        self._reset_preview()

    def _query_changed(self, *args):
        self._invalidate_search()

    def search_data(self):
        if self._closing or self.is_loading:
            return
        self._invalidate_search()
        query = self.search_field.text().strip()
        if not query:
            return
        datasets = self.collection.values() if self.search_scope.currentIndex() == 0 else (
            (self.dataset,) if self.dataset is not None else ())
        if not datasets:
            return
        self._searching = True
        self.search_status.setText('Searching dataset values...')
        self.search_status.show()
        self.search_runner.submit(self._search_token, datasets, query)

    @Slot(int, object)
    def _search_completed(self, token, result):
        if self._closing or token != self._search_token:
            return
        self._searching = False
        self._search_result = result
        self.search_status.setText(count_label(len(result.hits), 'result') + ' shown' +
                                   (' | more matches available' if result.truncated else ''))
        self.search_status.show()
        if self.search_scope.currentIndex() == 1:
            rows = result.rows
            self._render_rows(tuple(self.dataset.columns), tuple(r.values for r in rows), tuple(r.row_index for r in rows))
            self.preview_label.setText(count_label(len(rows), 'matching row') + ' shown' +
                                      (' | more matches available' if result.truncated else ''))
            self.preview_button.show()
        else:
            self.hits_table.setRowCount(len(result.hits))
            self.hits_table.setMaximumHeight(max(100, min(184,
                self.hits_table.horizontalHeader().sizeHint().height() +
                self.hits_table.verticalHeader().defaultSectionSize()*len(result.hits) + 12)))
            for row, hit in enumerate(result.hits):
                for col, value in enumerate((hit.row.dataset_name, hit.row.row_index+1, hit.column_name, hit.value)):
                    item = value_item(value)
                    item.setData(Qt.ItemDataRole.UserRole + 1, hit)
                    if col == 0:
                        item.setToolTip(escape(str(hit.row.dataset_path)))
                    elif col == 1:
                        item.setToolTip('Source row, excluding header (one-based).')
                    self.hits_table.setItem(row, col, item)
            self.hits_table.setVisible(bool(result.hits))

    @Slot(int, str)
    def _search_failed(self, token, error):
        if self._closing or token != self._search_token:
            return
        self._searching = False
        self.search_status.setText('Search failed: ' + error)
        self.search_status.show()

    def _open_hit(self, item):
        hit = item.data(Qt.ItemDataRole.UserRole + 1)
        if self._search_result is None or hit not in self._search_result.hits or not self.collection.contains(hit.row.dataset_path):
            return
        for row in range(self.dataset_list.count()):
            if self.dataset_list.item(row).data(Qt.ItemDataRole.UserRole) == hit.row.dataset_path:
                self.dataset_list.setCurrentRow(row)
                break
        self._render_rows(hit.row.columns, (hit.row.values,), (hit.row.row_index,))
        self.preview_label.setText(f'Search match | source row {hit.row.row_index+1:,} of {self.dataset.row_count:,}')
        self.preview_button.show()
        column = hit.row.columns.index(hit.column_name)
        self.preview_table.setCurrentCell(0, column)
        self.preview_table.scrollToItem(self.preview_table.item(0, column))
