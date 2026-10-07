"""Session-local transcript; every submitted question is a stateless request."""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QComboBox, QScrollArea, QToolButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy,
)
from cyber_analyst.analyst import AnalystRequest
from cyber_analyst.ai.models import AIProviderError, AIStructuredOutputError
from cyber_analyst.ai.runtime import LlamaRuntimeError
from .analyst_runner import AnalystSnapshot


def plain_label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class QuestionInput(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.submitted.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


def error_message(error):
    seen, current, chain = set(), error, []
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or getattr(current, 'original', None)
    if any(isinstance(e, TimeoutError) for e in chain):
        return 'The local AI request timed out. You can submit another question.'
    if any(isinstance(e, AIStructuredOutputError) for e in chain):
        return 'The local AI response did not satisfy the structured contract. You can submit another question.'
    if any(isinstance(e, AIProviderError) for e in chain):
        return 'The local AI provider is unavailable. Check the runtime in Settings.'
    if any(isinstance(e, (LlamaRuntimeError, ValueError)) for e in chain):
        return 'Unable to run this request. Check the selected scope and local runtime/model in Settings.'
    return 'The Analyst request could not be completed. You can submit another question.'


def reference_label(reference, snapshot):
    c, v, r = snapshot.context, snapshot.view, reference
    if r.kind == 'entity' and r.target_id in v.entity_ids:
        return c.entities[r.target_id].canonical_value
    if r.kind == 'analysis' and (r.dataset_name, r.target_id) in v.analysis_ids:
        return c.analyses[(r.dataset_name, r.target_id)].title
    if r.kind == 'dataset' and r.target_id in v.dataset_names:
        return r.target_id
    if r.kind == 'finding' and r.target_id in v.finding_ids:
        return c.findings[r.target_id].attention_level
    if r.kind == 'correlation' and r.target_id in v.correlation_ids:
        item = c.correlations[r.target_id]
        return f'{item.left_dataset}.{item.left_column} <-> {item.right_dataset}.{item.right_column}'
    if r.kind == 'relation' and r.target_id in v.relation_ids:
        return c.relations[r.target_id].relation_type
    return ''


class Exchange(QWidget):
    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 12)
        names = ', '.join(snapshot.view.dataset_names)
        self.snapshot_label = plain_label(f'Investigation {snapshot.investigation_number} | {names} | {snapshot.request.scope}')
        layout.addWidget(self.snapshot_label)
        layout.addWidget(plain_label('You'))
        self.question = plain_label(snapshot.request.question)
        layout.addWidget(self.question)
        layout.addWidget(plain_label('AI Analyst'))
        self.answer = QPlainTextEdit('Running...')
        self.answer.setReadOnly(True)
        self.answer.setMinimumHeight(65)
        self.answer.setMaximumHeight(300)
        layout.addWidget(self.answer)
        self.references = QTableWidget(0, 4)
        self.references.setHorizontalHeaderLabels(['Kind', 'Label / value', 'Identity', 'Dataset'])
        self.references.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.references.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.references.verticalHeader().hide()
        self.references.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.references.horizontalHeader().setStretchLastSection(True)
        self.references.setMaximumHeight(160)
        self.references.hide()
        layout.addWidget(self.references)
        self.limitations = plain_label('')
        self.limitations.hide()
        layout.addWidget(self.limitations)
        self.diagnostic_button = QToolButton()
        self.diagnostic_button.setText('Execution details')
        self.diagnostic_button.setCheckable(True)
        layout.addWidget(self.diagnostic_button)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumHeight(150)
        self.diagnostics.hide()
        layout.addWidget(self.diagnostics)
        self.diagnostic_button.toggled.connect(self.diagnostics.setVisible)

    def render(self, outcome):
        response = outcome.response
        # Exact backend text, without Markdown/HTML interpretation or rewriting.
        self.answer.setPlainText('\n\n'.join((response.summary, *(o.text for o in response.observations))))
        refs = tuple(dict.fromkeys(r for o in response.observations for r in o.references))
        self.references.setRowCount(len(refs))
        for row, ref in enumerate(refs):
            for col, text in enumerate((ref.kind, reference_label(ref, self.snapshot), ref.target_id, ref.dataset_name or '')):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.references.setItem(row, col, item)
        self.references.setVisible(bool(refs))
        self.references.setMaximumHeight(min(160, self.references.horizontalHeader().sizeHint().height()
                                              + self.references.verticalHeader().defaultSectionSize() * len(refs) + 2))
        self.limitations.setText('Limitations\n' + '\n'.join(response.limitations) if response.limitations else '')
        self.limitations.setVisible(bool(response.limitations))
        self._diagnostics(outcome.diagnostics)

    def render_error(self, error):
        self.answer.setPlainText(error_message(error))
        self._diagnostics(getattr(error, 'diagnostics', ()))

    def _diagnostics(self, diagnostics):
        self.diagnostics.setPlainText('\n'.join(f'{key}: {value}' for key, value in diagnostics)
                                      or 'Detailed diagnostics are unavailable for this request.')


class AnalystPage(QWidget):
    def __init__(self, session, runner, parent=None):
        super().__init__(parent)
        self.session, self.runner = session, runner
        self.exchanges = []
        self._active_exchange = None
        self._context = None
        self._investigation_number = 0
        self._blocked = False
        layout = QVBoxLayout(self)
        title = plain_label('AI Analyst')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        layout.addWidget(plain_label('Answers use the active investigation. Questions are independent; history is not sent.'))
        self.empty = plain_label('No active investigation. Load or run an investigation to ask questions.')
        layout.addWidget(self.empty)
        self.conversation = QScrollArea()
        self.conversation.setWidgetResizable(True)
        self.conversation.setMinimumSize(0, 0)
        self.conversation.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.transcript = QWidget()
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.addStretch()
        self.conversation.setWidget(self.transcript)
        layout.addWidget(self.conversation, 1)
        controls = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItem('Visible investigation', 'visible_investigation')
        self.scope.addItem('Current focus', 'current_focus')
        self.language = QComboBox()
        self.language.addItem('English', 'en')
        self.language.addItem('Português (Brasil)', 'pt-BR')
        for combo in (self.scope, self.language):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls.addWidget(self.scope)
        controls.addWidget(self.language)
        self.clear_button = QPushButton('Clear conversation')
        layout.addLayout(controls)
        self.question = QuestionInput()
        self.question.setPlaceholderText('Ask a factual question (Ctrl+Enter to send)')
        self.question.setMinimumHeight(42)
        self.question.setMaximumHeight(70)
        layout.addWidget(self.question)
        footer = QHBoxLayout()
        self.status = plain_label('')
        footer.addWidget(self.status, 1)
        footer.addWidget(self.clear_button)
        self.send_button = QPushButton('Send')
        footer.addWidget(self.send_button)
        layout.addLayout(footer)
        self.send_button.clicked.connect(self.submit)
        self.question.submitted.connect(self.submit)
        self.question.textChanged.connect(self.refresh_controls)
        self.clear_button.clicked.connect(self.clear_conversation)
        session.changed.connect(self._session_changed)
        runner.changed.connect(self.refresh_controls)
        runner.succeeded.connect(self._succeeded)
        runner.failed.connect(self._failed)
        self._session_changed()

    def _session_changed(self):
        if self.session.context is not self._context:
            self._context = self.session.context
            if self._context is not None:
                self._investigation_number += 1
        self.empty.setVisible(self.session.context is None)
        self.refresh_controls()

    def set_execution_blocked(self, blocked):
        self._blocked = blocked
        self.refresh_controls()

    def refresh_controls(self):
        configured = callable(getattr(self.runner.pipeline, 'answer', None))
        ready = self.session.context is not None and configured and not self.runner.running and not self._blocked
        for control in (self.question, self.scope, self.language):
            control.setEnabled(ready)
        self.send_button.setEnabled(ready and bool(self.question.toPlainText().strip()))
        self.clear_button.setEnabled(bool(self.exchanges) and not self.runner.running)
        self.status.setText('Running Analyst request...' if self.runner.running else
                            'No active investigation' if self.session.context is None else
                            'Configure local AI in Settings' if not configured else
                            'Waiting for investigation to finish' if self._blocked else 'Ready')

    def submit(self):
        if not self.send_button.isEnabled():
            return
        try:
            request = AnalystRequest(self.question.toPlainText(), self.language.currentData(), self.scope.currentData())
            snapshot = AnalystSnapshot(request, self.session.context, self.session.state, self.session.view,
                                       self._investigation_number)
            exchange = Exchange(snapshot)
            self.exchanges.append(exchange)
            self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, exchange)
            self._active_exchange = exchange
            self.runner.start(snapshot)
            self.question.clear()
            QTimer.singleShot(0, self._scroll_to_latest)
        except ValueError as exc:
            self.status.setText(str(exc))

    def _succeeded(self, snapshot, result):
        if self._active_exchange is not None and self._active_exchange.snapshot is snapshot:
            self._active_exchange.render(result)
            self._active_exchange = None
            QTimer.singleShot(0, self._scroll_to_latest)

    def _failed(self, snapshot, error):
        if self._active_exchange is not None and self._active_exchange.snapshot is snapshot:
            self._active_exchange.render_error(error)
            self._active_exchange = None
            QTimer.singleShot(0, self._scroll_to_latest)

    def _scroll_to_latest(self):
        bar = self.conversation.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_conversation(self):
        if self.runner.running:
            return
        for exchange in self.exchanges:
            self.transcript_layout.removeWidget(exchange)
            exchange.deleteLater()
        self.exchanges.clear()
        self.refresh_controls()
