"""Read-only presentation of visible findings and original evidence."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QPlainTextEdit, QSplitter,
)
from cyber_analyst.context import SearchResult


class FindingsPage(QWidget):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)
        title = QLabel('Findings')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty, 1)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(self.splitter, 1)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Attention', 'Dataset', 'Operation', 'Finding ID'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(60)
        for column, width in enumerate((85, 145, 160)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.splitter.addWidget(self.table)
        self.evidence_panel = QWidget()
        evidence_layout = QVBoxLayout(self.evidence_panel)
        evidence_layout.setContentsMargins(0, 6, 0, 0)
        evidence_layout.addWidget(QLabel('Evidence'))
        self.neutral = QLabel('Select a visible finding to inspect its evidence.')
        self.neutral.setWordWrap(True)
        evidence_layout.addWidget(self.neutral)
        self.provenance = QLabel()
        self.provenance.setTextFormat(Qt.TextFormat.PlainText)
        self.provenance.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.provenance.setWordWrap(True)
        evidence_layout.addWidget(self.provenance)
        self.payload_title = QLabel('Deterministic payload')
        evidence_layout.addWidget(self.payload_title)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.details.setMinimumHeight(50)
        evidence_layout.addWidget(self.details, 1)
        self.splitter.addWidget(self.evidence_panel)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 1)
        self._showing_evidence = False
        self.table.itemSelectionChanged.connect(self._select)
        self.table.itemActivated.connect(lambda _: self._select())
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        session = self.session
        ids = session.view.finding_ids if session.view is not None else ()
        focused = session.state.focus.finding_id if session.state is not None else None
        with QSignalBlocker(self.table):
            self.table.clearContents()
            self.table.setRowCount(len(ids))
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            for row, identifier in enumerate(ids):
                finding = session.context.findings[identifier]
                evidence = session.context.evidence_for(identifier)
                values = (finding.attention_level,
                          ', '.join(dict.fromkeys(e.dataset_name for e in evidence)),
                          ', '.join(dict.fromkeys(e.operation for e in evidence)),
                          identifier if len(identifier) <= 24 else identifier[:21] + '...')
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, identifier)
                    item.setToolTip(identifier if column == 3 else value)
                    self.table.setItem(row, column, item)
                if identifier == focused:
                    self.table.setCurrentCell(row, 0)
                    self.table.selectRow(row)
        active = session.context is not None
        counts = {}
        for identifier in ids:
            level = session.context.findings[identifier].attention_level
            counts[level] = counts.get(level, 0) + 1
        badges = '   '.join(f'{level.title()} {counts[level]}' for level in
                            ('high', 'medium', 'low', 'informational') if level in counts)
        self.summary.setText(f'{len(ids)} visible findings   {badges}')
        self.summary.setVisible(bool(ids))
        self.empty.setText(
            'No active investigation\nLoad or run an investigation to review evidence-backed findings.'
            if not active else
            'No findings match the current investigation view.\nAdjust the active filters to reveal other findings.')
        self.empty.setVisible(not ids)
        self.splitter.setVisible(bool(ids))
        self.table.setEnabled(active)
        selected = focused in ids
        self.neutral.setVisible(not selected)
        for widget in (self.provenance, self.payload_title, self.details):
            widget.setVisible(selected)
        self.provenance.clear()
        self.details.clear()
        if selected:
            finding = session.context.findings[focused]
            evidence = session.context.evidence_for(focused)[0]
            self.provenance.setText('\n'.join([
                f'Finding: {focused}', f'Attention: {finding.attention_level}',
                f'Evidence ID: {evidence.evidence_id}', f'Dataset: {evidence.dataset_name}',
                f'Source type: {evidence.source_type}', f'Operation: {evidence.operation}']))
            self.details.setPlainText(evidence.payload)
        if selected != self._showing_evidence or not selected:
            height = max(self.splitter.height(), 300)
            self.splitter.setSizes([int(height * .65), int(height * .35)] if selected else [height, 50])
        self._showing_evidence = selected

    def _select(self):
        items = self.table.selectedItems()
        if not items:
            return
        identifier = items[0].data(Qt.ItemDataRole.UserRole)
        self.session.navigate(SearchResult('finding', identifier, identifier, None, identifier))
