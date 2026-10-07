"""Native reference actions; labels are submission metadata, never previews."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSizePolicy
from .theme import role


class ReferenceItem(QWidget):
    activated = Signal(object)

    def __init__(self, reference, label, context_label, parent=None):
        super().__init__(parent)
        self.reference = reference
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.label = QLabel(' | '.join(value for value in (reference.kind, label, context_label) if value))
        self.identity = QLabel(reference.target_id if len(reference.target_id) <= 44 else reference.target_id[:41] + '...')
        for widget in (self.label, self.identity):
            widget.setTextFormat(Qt.TextFormat.PlainText)
            widget.setWordWrap(True)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.addWidget(widget)
        self.label.setToolTip(label)
        self.identity.setToolTip(reference.target_id)
        row.addLayout(text, 1)
        self.open_button = QPushButton('Open')
        role(self.open_button, 'secondary')
        row.addWidget(self.open_button)
        self.open_button.clicked.connect(lambda: self.activated.emit(self.reference))


class ReferenceList(QWidget):
    activated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = ()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._layout.addWidget(QLabel('References'))
        self.hide()

    def render(self, references):
        for item in self.items:
            self._layout.removeWidget(item)
            item.deleteLater()
        self.items = tuple(ReferenceItem(ref, label, context, self) for ref, label, context in references)
        for item in self.items:
            self._layout.addWidget(item)
            item.activated.connect(self.activated)
        self.setVisible(bool(self.items))

    def set_current(self, current):
        for item in self.items:
            item.open_button.setEnabled(current)
