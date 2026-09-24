"""Native workstation framing; no investigation service bindings."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QListWidget, QListWidgetItem, QPlainTextEdit
from .investigation_filters import InvestigationFilters


class Workspace(QWidget):
    def __init__(self, pages, parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        run_area = QHBoxLayout()
        self.run_button = QPushButton('Run investigation')
        self.run_status = QLabel('Ready')
        run_area.addWidget(self.run_button)
        run_area.addWidget(self.run_status)
        run_area.addStretch()
        layout.addLayout(run_area)
        commands=QHBoxLayout()
        self.search=search=QLineEdit()
        search.setPlaceholderText('Load an investigation to search')
        search.setEnabled(False)
        commands.addWidget(search,1)
        self.inspector_button=QPushButton('Context')
        self.inspector_button.setCheckable(True)
        commands.addWidget(self.inspector_button)
        layout.addLayout(commands)
        self.search_results=QListWidget()
        self.search_results.setMaximumHeight(180)
        self.search_results.hide()
        layout.addWidget(self.search_results)
        self.filters = InvestigationFilters()
        layout.addWidget(self.filters)
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
        self.details=QPlainTextEdit()
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
