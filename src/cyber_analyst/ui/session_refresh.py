"""Page-owned refresh scheduling for immutable investigation snapshots."""
from PySide6.QtCore import QEvent, QObject, Slot


class SessionRefresh(QObject):
    """Render the latest snapshot on show; unrelated focus changes need no work.

    The generation invalidates identical IDs from a replaced investigation.
    Only the last rendered view and this page's focus identity are retained.
    No deferred callback captures an obsolete context or result.
    """

    def __init__(self, page, session, render, focus_field=None, visibility_owner=None):
        super().__init__(page)
        self.page, self.session, self.render = page, session, render
        self.focus_field = focus_field
        self.visibility_owner = visibility_owner if visibility_owner is not None else page
        self._rendered_key = None
        self.visibility_owner.installEventFilter(self)
        session.changed.connect(self._changed)
        self._refresh()

    def _key(self):
        state = self.session.state
        focus = getattr(state.focus, self.focus_field) if state and self.focus_field else None
        return self.session.generation, self.session.view, focus

    @property
    def pending(self):
        return self._key() != self._rendered_key

    def _refresh(self):
        key = self._key()
        if key != self._rendered_key:
            previous = self._rendered_key
            # Rendering can show child widgets and deliver nested Show events.
            self._rendered_key = key
            try:
                self.render()
            except Exception:
                self._rendered_key = previous
                raise

    @Slot()
    def _changed(self):
        if self.visibility_owner.isVisible():
            self._refresh()

    def eventFilter(self, watched, event):
        if watched is self.visibility_owner and event.type() == QEvent.Type.Show:
            self._refresh()
        return super().eventFilter(watched, event)
