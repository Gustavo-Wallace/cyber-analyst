"""Native filter controls; immutable state transitions belong to the session."""
from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QToolButton, QMenu, QPushButton, QLabel, QLayout
from .theme import SPACE, role
from .count_labels import count_label


class FilterMenu(QToolButton):
    selection_changed = Signal(tuple)

    def __init__(self, label, all_label, parent=None):
        super().__init__(parent)
        self.label, self.all_label = label, all_label
        self.actions_by_value = {}
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setMenu(QMenu(self))

    def refresh(self, options, selected, active):
        if tuple(self.actions_by_value) != options:
            self.menu().clear()
            self.actions_by_value = {}
            self.menu().addAction(self.all_label, lambda: self.selection_changed.emit(()))
            self.menu().addSeparator()
            for value in options:
                action = self.menu().addAction(value)
                action.setCheckable(True)
                action.triggered.connect(self._select)
                self.actions_by_value[value] = action
        for value, action in self.actions_by_value.items():
            with QSignalBlocker(action):
                action.setChecked(value in selected)
        self.setEnabled(active)
        suffix = str(len(selected)) if selected else 'All'
        self.setText(f'{self.label}: {suffix}' if active else f'{self.label}: —')
        self.setToolTip(', '.join(selected) if selected else self.all_label if active else 'No active investigation')
        self.setProperty('filterActive', bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

    def _select(self):
        self.selection_changed.emit(tuple(value for value, action in self.actions_by_value.items() if action.isChecked()))


class InvestigationFilters(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.controls = QGridLayout()
        self.controls.setSpacing(SPACE['sm'])
        self.controls.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.controls.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.datasets = FilterMenu('Dataset', 'All datasets')
        self.entities = FilterMenu('Entities', 'All types')
        self.attention = FilterMenu('Attention', 'All levels')
        self.clear_button = QPushButton('Clear filters')
        self._widgets = (self.datasets, self.entities, self.attention, self.clear_button)
        for widget in self._widgets:
            widget.setEnabled(False)
        layout.addLayout(self.controls)
        self._columns = 0
        self._reflow()
        self.summary = role(QLabel('No active investigation'), 'caption')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        for control in (self.datasets, self.entities, self.attention):
            control.refresh((), (), False)

    def _reflow(self):
        columns = 2 if self.width() < 390 else 4
        if columns == self._columns:
            return
        for index in range(4): self.controls.setColumnStretch(index, 0)
        for index, widget in enumerate(self._widgets):
            self.controls.addWidget(widget, index // columns, index % columns)
        self._columns = columns
        self.updateGeometry()

    def resizeEvent(self, event):
        self._reflow()
        super().resizeEvent(event)

    def bind(self, session):
        self.session = session
        self.datasets.selection_changed.connect(session.set_dataset_scope)
        self.entities.selection_changed.connect(session.set_entity_types)
        self.attention.selection_changed.connect(session.set_attention_levels)
        self.clear_button.clicked.connect(session.clear_filters)
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        session = self.session
        active = session.state is not None
        selected = (session.state.dataset_scope, session.state.entity_types, session.state.attention_levels) if active else ((), (), ())
        for control, options, values in zip((self.datasets, self.entities, self.attention), session.filter_options, selected):
            control.refresh(options, values, active)
        self.clear_button.setEnabled(active)
        view = session.view
        self.summary.setText(
            ' · '.join((count_label(len(view.dataset_names), 'dataset'),
                        count_label(len(view.entity_ids), 'entity', 'entities'),
                        count_label(len(view.relation_ids), 'relation'),
                        count_label(len(view.finding_ids), 'finding')))
            if active else 'No active investigation'
        )
