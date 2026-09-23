"""Native in-memory configuration; application composition is delegated."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog
from cyber_analyst.app.config import RuntimeConfig, discover_paths

class SettingsPage(QWidget):
    def __init__(self, apply_config, parent=None):
        super().__init__(parent)
        self.apply_config = apply_config
        layout = QVBoxLayout(self)
        title = QLabel('Local AI')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        self.executable = QLineEdit()
        self.model = QLineEdit()
        for label, field, pattern in [('llama-server', self.executable, 'llama-server (llama-server.exe)'), ('Model', self.model, 'GGUF model (*.gguf)')]:
            layout.addWidget(QLabel(label))
            row = QHBoxLayout()
            row.addWidget(field)
            button = QPushButton('Browse')
            button.clicked.connect(lambda checked=False, f=field, p=pattern: self._browse(f,p))
            row.addWidget(button)
            layout.addLayout(row)
        self.status = QLabel('Not configured')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.apply_button = QPushButton('Apply')
        self.apply_button.clicked.connect(self.apply)
        layout.addWidget(self.apply_button)
        layout.addStretch()
        executable, model = discover_paths()
        self.executable.setText(str(executable) if executable else '')
        self.model.setText(str(model) if model else '')
        self.executable.textEdited.connect(lambda: self.status.setText('Not configured (unapplied changes)'))
        self.model.textEdited.connect(lambda: self.status.setText('Not configured (unapplied changes)'))

    def _browse(self, field, pattern):
        path, _ = QFileDialog.getOpenFileName(self, 'Select local file', field.text(), pattern)
        if path:
            field.setText(path)
            self.status.setText('Not configured (unapplied changes)')

    def apply(self):
        try:
            config = RuntimeConfig(Path(self.executable.text().strip()), Path(self.model.text().strip()))
            config.validate()
            self.apply_config(config)
        except Exception as exc:
            self.status.setText(f'Invalid: {exc}')
            return
        self.status.setText('Valid')
