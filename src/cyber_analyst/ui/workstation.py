"""Native workstation framing; no investigation service bindings."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QListWidget, QPlainTextEdit, QStackedWidget, QLayout
from .investigation_filters import InvestigationFilters
from .theme import SPACE, role, label


class WorkspaceHeader(QWidget):
    """Shared page identity and local session caption, independent of domain logic."""
    def __init__(self):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(SPACE['sm'])
        self.title = label('Dashboard', 'page_title')
        self.description = label('Choose one or more datasets to start an investigation.', 'caption')
        self.primary_button = role(QPushButton('Add datasets'), 'primary')
        self.session_label = label('NO INVESTIGATION', 'badge')
        self.run_status = label('Ready', 'caption')
        for widget in (self.title, self.session_label, self.run_status):
            widget.setWordWrap(False)
        self.identity = QWidget()
        row = QHBoxLayout(self.identity)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.session_label)
        row.addWidget(self.run_status)
        self.grid.addWidget(self.title, 0, 0)
        self.grid.addWidget(self.identity, 0, 1)
        self.grid.addWidget(self.primary_button, 0, 2)
        self.grid.addWidget(self.description, 1, 0, 1, 3)
        self.grid.setColumnStretch(0, 1)
        self._context = None
        self._number = 0

    def set_page(self, title):
        self.title.setText(title)
        descriptions = {
            'Dashboard': 'Explore your data, review alerts and ask AI Analyst.',
            'Investigate': 'Browse executed analyses and correlations.',
            'Findings': 'Review selected deterministic evidence and its provenance.',
            'Data': 'Browse loaded datasets and search their values.',
            'Relations': 'Explore entities and observed co-occurrences.',
            'AI Analyst': 'Ask grounded questions about the active investigation.',
            'Settings': 'Configure the local runtime and model.',
        }
        self.description.setText(descriptions[title])
        self._reflow()

    def set_investigation(self, context):
        if context is not self._context:
            self._context = context
            if context is not None:
                self._number += 1
        self.session_label.setText(f'INVESTIGATION {self._number:02}' if context is not None else 'NO INVESTIGATION')
        self.session_label.setToolTip(', '.join(context.datasets) if context is not None else 'No active investigation')
        self._reflow()

    def _reflow(self):
        compact = self.width() < max(520, self.title.sizeHint().width() + self.identity.sizeHint().width() + self.primary_button.sizeHint().width() + 2 * SPACE['sm'])
        self.grid.addWidget(self.identity, 1 if compact else 0, 0 if compact else 1)
        self.grid.addWidget(self.primary_button, 0, 1 if compact else 2)
        self.grid.addWidget(self.description, 2 if compact else 1, 0, 1, 2 if compact else 3)
        self.description.setVisible(not compact)

    def resizeEvent(self, event):
        self._reflow()
        super().resizeEvent(event)


class WorkspacePages(QStackedWidget):
    """Fit the active workspace; hidden pages must not force its scroll size."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(self.updateGeometry)

    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page else super().sizeHint()

    def minimumSizeHint(self):
        page = self.currentWidget()
        return page.minimumSizeHint() if page else super().minimumSizeHint()

    def heightForWidth(self, width):
        page = self.currentWidget()
        return page.heightForWidth(width) if page else super().heightForWidth(width)


class Workspace(QWidget):
    def __init__(self, pages, parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self)
        role(self, 'canvas')
        layout.setContentsMargins(SPACE['lg'],SPACE['sm'],SPACE['lg'],SPACE['sm'])
        layout.setSpacing(SPACE['sm'])
        self.header = WorkspaceHeader()
        layout.addWidget(self.header)
        self.run_button = self.header.primary_button
        self.run_status = self.header.run_status
        self.command_panel = role(QWidget(), 'toolbar')
        command_layout = QVBoxLayout(self.command_panel)
        command_layout.setContentsMargins(SPACE['md'],SPACE['sm'],SPACE['md'],SPACE['sm'])
        command_layout.setSpacing(SPACE['sm'])
        self.commands = QGridLayout()
        self.commands.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.search=search=QLineEdit()
        search.setMinimumWidth(0)
        search.setPlaceholderText('Load an investigation to search')
        search.setEnabled(False)
        self.inspector_button=role(QPushButton('Context'), 'secondary')
        self.inspector_button.setCheckable(True)
        self.filters_button = role(QPushButton('Filters'), 'secondary')
        self.filters_button.setCheckable(True)
        command_layout.addLayout(self.commands)
        self._compact_commands = None
        self.search_results=QListWidget()
        self.search_results.setMaximumHeight(180)
        self.search_results.hide()
        command_layout.addWidget(self.search_results)
        self.filters = InvestigationFilters()
        self.filters.set_expanded(False)
        self.filters_button.toggled.connect(self.filters.set_expanded)
        command_layout.addWidget(self.filters)
        layout.addWidget(self.command_panel)
        self.command_panel.hide()
        self._exploration_visible = True
        self._investigation_active = False
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumSize(0,0)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(pages)
        layout.addWidget(scroll,1)
        self.scroll = scroll
        self._reflow_commands()

    def _reflow_commands(self):
        compact = self.width() < 360
        if compact == self._compact_commands:
            return
        for col in range(3): self.commands.setColumnStretch(col, 0)
        self.commands.addWidget(self.search, 0, 0, 1, 2 if compact else 1)
        self.commands.addWidget(self.filters_button, 1 if compact else 0, 0 if compact else 1)
        self.commands.addWidget(self.inspector_button, 1 if compact else 0, 1 if compact else 2)
        self.commands.setColumnStretch(0, 1)
        self._compact_commands = compact

    def set_exploration_visible(self, visible):
        self._exploration_visible = visible
        self._update_exploration_visibility()

    def _update_exploration_visibility(self):
        self.command_panel.setVisible(self._exploration_visible and self._investigation_active)

    def refresh_exploration(self, session):
        active = session.context is not None
        self._investigation_active = active
        self._update_exploration_visibility()
        state = session.state
        count = sum(bool(values) for values in (state.dataset_scope, state.entity_types, state.attention_levels)) if active else 0
        self.filters_button.setText(f'Filters ({count})' if count else 'Filters')
        self.filters_button.setProperty('filterActive', bool(count))
        self.filters_button.style().unpolish(self.filters_button)
        self.filters_button.style().polish(self.filters_button)
        if not active:
            self.filters_button.setChecked(False)

    def resizeEvent(self, event):
        self._reflow_commands()
        super().resizeEvent(event)


class ContextInspector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        role(self, 'inspector')
        self.setMinimumWidth(0)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(SPACE['md'],SPACE['md'],SPACE['md'],SPACE['md'])
        heading=label('Context inspector', 'section_title')
        layout.addWidget(heading)
        self.details=role(QPlainTextEdit(), 'inspector_details')
        self.details.setReadOnly(True)
        layout.addWidget(self.details)
        self.render(None,None)

    def render(self, context, state):
        text='Select an investigation object to inspect its context.'
        if context is not None and state is not None:
            f=state.focus
            if f.entity_id is not None:
                e=context.entity(f.entity_id)
                lines=[f'{e.entity_type} / {e.canonical_value}',
                    'Datasets: '+', '.join(e.dataset_names), f'Occurrences: {len(e.occurrences)}',
                    f'Direct neighbors: {len(e.neighbor_entity_ids)}',f'Relations: {len(e.relation_ids)}']
                lines.extend(f'{o.dataset_name}.{o.column_name}: {o.value} | rows={o.row_count} | role={o.semantic_role}' for o in e.occurrences)
                text='\n'.join(lines)
            elif f.dataset_name is not None:
                d=context.dataset(f.dataset_name)
                text=f'{d.dataset_name}\nEntities: {len(d.entity_ids)}\nRelations: {len(d.relation_ids)}\nFindings: {len(d.finding_ids)}\nAnalyses: {len(d.analysis_result_ids)}'
            elif f.finding_id is not None:
                finding=context.findings[f.finding_id]
                lines=[finding.finding_id,'Attention: '+finding.attention_level]
                lines.extend(f'{e.evidence_id}\nDataset: {e.dataset_name}\nOperation: {e.operation}' for e in context.evidence_for(f.finding_id))
                text='\n'.join(lines)
            elif f.analysis is not None:
                a=f.analysis;step=context.analyses[(a.dataset_name,a.analysis_id)]
                text=f'{a.dataset_name}\n{a.analysis_id}\nOperation: {step.operation}\n{step.title}\nColumns: '+', '.join(step.columns)
            elif f.correlation_id is not None:
                c = context.correlations[f.correlation_id]
                m = c.correlation_result.summary
                text = (f'{c.left_dataset}.{c.left_column}\n<-> {c.right_dataset}.{c.right_column}\n'
                        f'Common keys: {m.common}\nMatched rows: {m.matched_rows}\n'
                        f'Left-only keys: {m.only_a}\nRight-only keys: {m.only_b}')
            elif f.relation_id is not None:
                relation = context.relations[f.relation_id]
                a = context.entities[relation.entity_a_id]
                b = context.entities[relation.entity_b_id]
                label = 'Co-occurrence' if relation.relation_type == 'co_occurrence' else relation.relation_type
                count = len(relation.occurrences)
                lines = [label, f'{a.entity_type}: {a.canonical_value}',
                         f'<-> {b.entity_type}: {b.canonical_value}', '',
                         f'{count} occurrence' + ('s' if count != 1 else '') + ' | ' +
                         ', '.join(sorted({o.dataset_name for o in relation.occurrences}))]
                text = '\n'.join(lines)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap if context is not None and state is not None and state.focus.relation_id is not None else QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.details.setToolTip(state.focus.relation_id or '' if state is not None else '')
        self.details.setPlainText(text)
