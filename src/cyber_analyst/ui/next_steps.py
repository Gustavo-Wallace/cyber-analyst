"""Native, read-only recommendation actions; current view authorizes every click."""
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy

from cyber_analyst.analyst import AnalystReference
from cyber_analyst.context.next_steps import NextStepsService
from .analyst_references import REFERENCE_UNAVAILABLE
from .theme import SPACE, label, role

class NextStepButton(QPushButton):
    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return QSize(0, self.sizeHint().height())


class NextStepsWidget(QWidget):
    navigated = Signal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.steps, self.buttons = (), ()
        role(self, 'panel')
        box = QVBoxLayout(self)
        box.setContentsMargins(SPACE['lg'], SPACE['md'], SPACE['lg'], SPACE['md'])
        box.setSpacing(SPACE['sm'])
        box.addWidget(label('Recommended next steps', 'section_title'))
        box.addWidget(label('Places to review in the current view.', 'caption'))
        self.items = QVBoxLayout()
        self.items.setSpacing(SPACE['xs'])
        box.addLayout(self.items)
        self.unavailable = label(REFERENCE_UNAVAILABLE, 'caption', 'warning')
        self.unavailable.hide()
        box.addWidget(self.unavailable)
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        for button in self.buttons:
            self.items.removeWidget(button)
            button.hide()
            button.deleteLater()
        context = self.session.context
        self.steps = NextStepsService().build(context, self.session.view) if context is not None else ()
        self.buttons = tuple(self._button(step, context) for step in self.steps)
        for button in self.buttons:
            self.items.addWidget(button)
        self.unavailable.hide()
        self.setVisible(bool(self.steps))

    def _button(self, step, context):
        button = role(NextStepButton(), 'highlight')
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box = QVBoxLayout(button)
        box.setContentsMargins(SPACE['sm'], SPACE['xs'], SPACE['sm'], SPACE['xs'])
        box.setSpacing(2)
        for text, kind, tone in ((step.title, 'body', 'cyan'), (step.supporting_label, 'caption', None)):
            text_label = label(text, kind, tone)
            text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            box.addWidget(text_label)
        button.setAccessibleName(step.title)
        button.setToolTip(step.title + '\n' + step.supporting_label + '\n' + step.target_id)
        button.clicked.connect(lambda checked=False: self.activate(step, context))
        return button

    def activate(self, step, context):
        reference = AnalystReference(step.target_kind, step.target_id)
        try:
            if context is not self.session.context:
                raise ValueError('Previous investigation')
            self.session.navigate_reference(reference)
        except ValueError:
            self.unavailable.show()
            self.show()
            return
        self.unavailable.hide()
        self.navigated.emit(reference)
