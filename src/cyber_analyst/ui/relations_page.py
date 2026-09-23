"""Visible deterministic co-occurrences and their source provenance."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QSplitter)
from cyber_analyst.context import SearchResult


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(28)
    table.setShowGrid(False)
    return table


class RelationsPage(QWidget):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)
        title = QLabel('Relations')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.empty = QLabel()
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(self.splitter, 1)
        self.table = _table(['Entity A', 'Type', 'Relation', 'Entity B', 'Type', 'Occurrences'])
        for col in range(6):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch if col in (0, 3) else QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet('QTableWidget::item:selected { background: #253d30; color: #dce3df; } QTableWidget::item { border: none; }')
        self.table.horizontalHeader().setMinimumSectionSize(85)
        self.splitter.addWidget(self.table)
        self.panel = QWidget()
        detail_layout = QVBoxLayout(self.panel)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_layout.addWidget(self.details)
        self.endpoint_cards = QWidget()
        cards = QHBoxLayout(self.endpoint_cards)
        cards.setContentsMargins(0, 0, 0, 0)
        self.endpoint_labels = []
        self.endpoint_a = QPushButton('Focus entity')
        self.endpoint_b = QPushButton('Focus entity')
        for name, button in (('Endpoint A', self.endpoint_a), ('Endpoint B', self.endpoint_b)):
            card = QVBoxLayout()
            card.addWidget(QLabel(name))
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setMinimumWidth(0)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card.addWidget(label)
            self.endpoint_labels.append(label)
            button.setStyleSheet('QPushButton { border: 1px solid #527460; background: #253d30; padding: 4px 8px; }')
            card.addWidget(button)
            cards.addLayout(card, 1)
        detail_layout.addWidget(self.endpoint_cards)
        self.observed = QLabel()
        self.observed.setWordWrap(True)
        detail_layout.addWidget(self.observed)
        self.occurrence_title = QLabel('Occurrences')
        detail_layout.addWidget(self.occurrence_title)
        self.occurrences = _table(['Dataset', 'Endpoint A column', 'Role', 'Endpoint B column', 'Role', 'Rows'])
        self.occurrences.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        detail_layout.addWidget(self.occurrences)
        self.splitter.addWidget(self.panel)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 1)
        self.endpoint_a.clicked.connect(lambda: self._endpoint('entity_a_id'))
        self.endpoint_b.clicked.connect(lambda: self._endpoint('entity_b_id'))
        self.table.itemSelectionChanged.connect(self._select)
        self.table.itemActivated.connect(lambda _: self._select())
        self._selected = False
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        session = self.session
        ids = session.view.relation_ids if session.view is not None else ()
        focused = session.state.focus.relation_id if session.state is not None else None
        with QSignalBlocker(self.table):
            self.table.setRowCount(0)
            self.table.setRowCount(len(ids))
            for row, identifier in enumerate(ids):
                relation = session.context.relations[identifier]
                a, b = (session.context.entities[i] for i in (relation.entity_a_id, relation.entity_b_id))
                values = (a.canonical_value, a.entity_type, 'Co-occurrence' if relation.relation_type == 'co_occurrence' else relation.relation_type,
                          b.canonical_value, b.entity_type, str(len(relation.occurrences)))
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, identifier)
                    item.setToolTip(f'{value}\n{identifier}')
                    self.table.setItem(row, col, item)
                if identifier == focused:
                    self.table.setCurrentCell(row, 0)
                    self.table.selectRow(row)
        self.empty.setText('No active investigation\nLoad or run an investigation to inspect entity relationships.'
                           if session.context is None else
                           'No relations match the current investigation view.\nAdjust the active filters to reveal other relations.')
        self.empty.setVisible(not ids)
        self.splitter.setVisible(bool(ids))
        self.summary.setVisible(bool(ids))
        self.summary.setText(f'{len(ids)} visible relations | {len(session.view.entity_ids) if session.view else 0} visible entities')
        selected = focused in ids
        for widget in (self.endpoint_cards, self.observed, self.occurrence_title):
            widget.setVisible(selected)
        if selected != self._selected or not selected:
            height = max(self.splitter.height(), 400)
            self.splitter.setSizes([int(height * .65), int(height * .35)] if selected else [height, 45])
        self._selected = selected
        self.endpoint_a.setVisible(selected)
        self.endpoint_b.setVisible(selected)
        self.occurrences.setVisible(selected)
        self.occurrences.setRowCount(0)
        self.details.setText('Select a visible relation to inspect its occurrences.')
        if not selected:
            return
        relation = session.context.relations[focused]
        a, b = (session.context.entities[i] for i in (relation.entity_a_id, relation.entity_b_id))
        label = 'Co-occurrence' if relation.relation_type == 'co_occurrence' else relation.relation_type
        self.details.setText(f'Relation details\n{label}')
        self.details.setToolTip(focused)
        for widget, entity in zip(self.endpoint_labels, (a, b)):
            widget.setText(f'{entity.entity_type}\n{entity.canonical_value}')
            widget.setToolTip(f'{entity.entity_type}\n{entity.canonical_value}\n{entity.entity_id}')
            widget.setMaximumWidth(260)
        datasets = ', '.join(sorted({o.dataset_name for o in relation.occurrences}))
        count = len(relation.occurrences)
        self.observed.setText(f'Observed in\n{count} occurrence' + ('s' if count != 1 else '') + f' | {datasets}')
        self.occurrences.setMaximumHeight(30 + 28 * min(count, 4) + 18)
        self.occurrences.setRowCount(len(relation.occurrences))
        for row, occurrence in enumerate(relation.occurrences):
            values = (occurrence.dataset_name, occurrence.entity_a_column, occurrence.entity_a_role,
                      occurrence.entity_b_column, occurrence.entity_b_role, occurrence.row_count)
            for col, value in enumerate(values):
                self.occurrences.setItem(row, col, QTableWidgetItem('-' if value is None else str(value)))

    def _select(self):
        items = self.table.selectedItems()
        if items:
            self.session.focus_relation(items[0].data(Qt.ItemDataRole.UserRole))

    def _endpoint(self, attribute):
        identifier = self.session.state.focus.relation_id
        if identifier not in self.session.view.relation_ids:
            return
        entity = getattr(self.session.context.relations[identifier], attribute)
        self.session.navigate(SearchResult('entity', entity, entity, None, entity))
