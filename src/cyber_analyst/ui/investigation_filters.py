"""Native filter controls; immutable state transitions belong to the session."""
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QMenu, QPushButton, QLabel


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

    def _select(self):
        self.selection_changed.emit(tuple(value for value, action in self.actions_by_value.items() if action.isChecked()))


class InvestigationFilters(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.setSpacing(2)
        self.datasets = FilterMenu('Dataset', 'All datasets')
        self.entities = FilterMenu('Entities', 'All types')
        self.attention = FilterMenu('Attention', 'All levels')
        self.clear_button = QPushButton('Clear filters')
        for widget in (self.datasets, self.entities, self.attention, self.clear_button):
            controls.addWidget(widget)
            widget.setEnabled(False)
        layout.addLayout(controls)
        self.summary = QLabel('No active investigation')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        for control in (self.datasets, self.entities, self.attention):
            control.refresh((), (), False)

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
            f'{len(view.dataset_names)} datasets · {len(view.entity_ids)} entities · '
            f'{len(view.relation_ids)} relations · {len(view.finding_ids)} findings'
            if active else 'No active investigation'
        )
