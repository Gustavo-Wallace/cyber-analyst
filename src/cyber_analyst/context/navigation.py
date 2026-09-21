"""Validated navigation from visible search targets, without changing filters."""
from .state import StateService, StateError
from .view import ViewService
from .search import SearchResult


class NavigationError(ValueError):
    """Malformed, stale or hidden search target."""


class NavigationService:
    def focus_search_result(self, state, context, view, result):
        if not isinstance(result,SearchResult) or not isinstance(result.target_id,str) or not result.target_id:
            raise NavigationError('Invalid search target')
        # Also validates stored focus/filter references against this context.
        allowed = ViewService().build(context,state)
        svc = StateService()
        target = result.target_id
        try:
            if result.kind == 'analysis':
                if not isinstance(result.dataset_name,str) or not result.dataset_name:
                    raise NavigationError('Analysis result requires dataset_name')
                pair = (result.dataset_name,target)
                if pair not in view.analysis_ids or pair not in allowed.analysis_ids:
                    raise NavigationError('Stale or hidden analysis')
                return svc.focus_analysis(state,context,*pair)
            attr = {'entity':'entity_ids','dataset':'dataset_names','finding':'finding_ids'}.get(result.kind)
            if attr is None:
                raise NavigationError('Unknown result kind')
            if target not in getattr(view,attr) or target not in getattr(allowed,attr):
                raise NavigationError('Stale or hidden search target')
            if result.dataset_name is not None:
                if result.kind == 'dataset':
                    valid = result.dataset_name == target
                elif result.kind == 'entity':
                    valid = any(o.dataset_name == result.dataset_name for o in context.entities[target].occurrences)
                else:
                    valid = any(e.dataset_name == result.dataset_name for e in context.evidence_for(target))
                if not valid:
                    raise NavigationError('Inconsistent result dataset metadata')
            return getattr(svc,'focus_'+result.kind)(state,context,target)
        except StateError as exc:
            raise NavigationError(str(exc)) from exc
