"""UI session orchestration; all querying remains in domain services."""
from PySide6.QtCore import QObject, Signal
from cyber_analyst.context import ContextService, StateService, ViewService, SearchService, NavigationService
from cyber_analyst.findings.service import ATTENTION_LEVELS


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

    def focus_correlation(self, correlation_id):
        state = self._require_state()
        if correlation_id not in self.view.correlation_ids:
            raise ValueError('Stale or hidden correlation')
        self.set_state(StateService().focus_correlation(state, self.context, correlation_id))

    def focus_relation(self, relation_id):
        state = self._require_state()
        if relation_id not in self.view.relation_ids:
            raise ValueError('Stale or hidden relation')
        self.set_state(StateService().focus_relation(state, self.context, relation_id))

    @property
    def filter_options(self):
        if self.context is None:
            return ((), (), ())
        return (
            tuple(sorted(self.context.datasets)),
            tuple(sorted({entity.entity_type for entity in self.context.entities.values()})),
            tuple(sorted(ATTENTION_LEVELS)),
        )

    def _require_state(self):
        if self.state is None:
            raise ValueError('No investigation loaded')
        return self.state

    def set_dataset_scope(self, names):
        self.set_state(StateService().set_dataset_scope(self._require_state(), self.context, names))

    def set_entity_types(self, types):
        self.set_state(StateService().set_entity_types(self._require_state(), self.context, types))

    def set_attention_levels(self, levels):
        self.set_state(StateService().set_attention_levels(self._require_state(), levels))

    def clear_filters(self):
        self.set_state(StateService().clear_filters(self._require_state()))
