"""Native workstation framing; no investigation service bindings."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea


class Workspace(QWidget):
    def __init__(self, pages, parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        commands=QHBoxLayout()
        search=QLineEdit()
        search.setPlaceholderText('Search investigation (coming soon)')
        search.setEnabled(False)
        commands.addWidget(search,1)
        self.inspector_button=QPushButton('Context')
        self.inspector_button.setCheckable(True)
        commands.addWidget(self.inspector_button)
        layout.addLayout(commands)
        toolbar=QLabel('Investigation context | Filters will be available here')
        toolbar.setWordWrap(True)
        toolbar.setObjectName('contextToolbar')
        layout.addWidget(toolbar)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumSize(0,0)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(pages)
        layout.addWidget(scroll,1)


class ContextInspector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        layout=QVBoxLayout(self)
        label=QLabel('Context inspector')
        label.setWordWrap(True)
        layout.addWidget(label)
        description=QLabel('Select an investigation object to inspect its context in a future block.')
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addStretch()
