"""UI session orchestration; all querying remains in domain services."""
from PySide6.QtCore import QObject, Signal
from cyber_analyst.context import ContextService, StateService, ViewService, SearchService, NavigationService


class InvestigationSession(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = self.context = self.state = self.view = None

    def load(self, result):
        context = ContextService().build(result)
        state = StateService().initial(context)
        view = ViewService().build(context,state)
        self.result,self.context,self.state,self.view = result,context,state,view
        self.changed.emit()

    def clear(self):
        self.result = self.context = self.state = self.view = None
        self.changed.emit()

    def set_state(self, state):
        if self.context is None:
            raise ValueError('No investigation loaded')
        view = ViewService().build(self.context,state)
        self.state,self.view = state,view
        self.changed.emit()

    def search(self, query):
        if self.context is None:
            raise ValueError('No investigation loaded')
        return SearchService().search(self.context,self.view,query)

    def navigate(self, result):
        if self.context is None:
            raise ValueError('No investigation loaded')
        self.set_state(NavigationService().focus_search_result(self.state,self.context,self.view,result))

    def clear_focus(self):
        if self.state is not None:
            self.set_state(StateService().clear_focus(self.state))
