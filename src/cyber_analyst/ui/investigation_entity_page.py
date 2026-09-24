"""Entity pivots over existing context only; no inferred associations."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidgetItem, QSplitter
from cyber_analyst.context import SearchResult
from .investigation_analysis_page import table, text


class InvestigationEntityPage(QWidget):
    def __init__(self, session):
        super().__init__()
        self.session = session
        layout = QVBoxLayout(self)
        title = QLabel('Entities')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)
        self.selector = table(['Value','Type','Datasets','Relations'])
        splitter.addWidget(self.selector)
        self.panel = QWidget()
        detail = QVBoxLayout(self.panel)
        self.identity = QLabel()
        self.identity.setTextFormat(Qt.TextFormat.PlainText)
        self.identity.setWordWrap(True)
        self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail.addWidget(self.identity)
        detail.addWidget(QLabel('Committed occurrences (activate a row to focus its dataset)'))
        self.occurrences = table(['Dataset','Column','Semantic type','Semantic role','Value','Rows'])
        detail.addWidget(self.occurrences)
        self.relation_summary = QLabel()
        detail.addWidget(self.relation_summary)
        self.neighbors = table(['Neighbor','Neighbor type','Relation','Datasets','Occurrences'])
        detail.addWidget(self.neighbors)
        self.findings = QLabel('No directly linked findings available.')
        self.analyses = QLabel('No directly linked analyses available.')
        detail.addWidget(self.findings);detail.addWidget(self.analyses)
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(0,1);splitter.setStretchFactor(1,2)
        self.selector.itemSelectionChanged.connect(self._select)
        self.neighbors.itemActivated.connect(self._neighbor)
        self.occurrences.itemActivated.connect(self._dataset)
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        s = self.session
        ids = s.view.entity_ids if s.view else ()
        focus = s.state.focus.entity_id if s.state else None
        with QSignalBlocker(self.selector):
            self.selector.setRowCount(0);self.selector.setRowCount(len(ids))
            for row, identifier in enumerate(ids):
                e = s.context.entities[identifier]
                values = (e.canonical_value,e.entity_type,', '.join(e.dataset_names),
                          str(len(set(e.relation_ids).intersection(s.view.relation_ids))))
                for col,value in enumerate(values):
                    item=QTableWidgetItem(value);item.setToolTip(value+'\n'+identifier)
                    item.setData(Qt.ItemDataRole.UserRole,identifier);self.selector.setItem(row,col,item)
                if identifier==focus:self.selector.setCurrentCell(row,0);self.selector.selectRow(row)
        self.message.setText('No active investigation.' if s.context is None else
            'Focused entity is hidden by filters.' if focus and focus not in ids else
            'No entities in the current investigation view.' if not ids else
            f'{len(ids)} visible entities' + ('' if focus in ids else ' | Select an entity.'))
        self.selector.setVisible(bool(ids));self.panel.setVisible(focus in ids)
        self.occurrences.setRowCount(0);self.neighbors.setRowCount(0)
        if focus not in ids:return
        e=s.context.entities[focus]
        self.identity.setText(f'{e.canonical_value}\n{e.entity_type}\n'
            f'Committed occurrences: {len(e.occurrences)} | Datasets: {len(e.dataset_names)}\n'
            f'Direct relations: {len(e.relation_ids)} | Direct neighbors: {len(e.neighbor_entity_ids)}')
        self.identity.setToolTip(e.entity_id)
        self.occurrences.setRowCount(len(e.occurrences))
        for row,o in enumerate(e.occurrences):
            for col,value in enumerate((o.dataset_name,o.column_name,o.semantic_type,o.semantic_role,o.value,o.row_count)):
                item=QTableWidgetItem(text(value));item.setToolTip(text(value));item.setData(Qt.ItemDataRole.UserRole,o.dataset_name)
                self.occurrences.setItem(row,col,item)
        relations=tuple(i for i in e.relation_ids if i in s.view.relation_ids)
        self.relation_summary.setText(f'{len(relations)} visible direct relations (activate a neighbor to focus)' if relations else 'No visible direct relations.')
        self.neighbors.setVisible(bool(relations));self.neighbors.setRowCount(len(relations))
        for row,i in enumerate(relations):
            r=s.context.relations[i]
            neighbor=r.entity_b_id if r.entity_a_id==focus else r.entity_a_id
            n=s.context.entities[neighbor]
            values=(n.canonical_value,n.entity_type,'Co-occurrence' if r.relation_type=='co_occurrence' else r.relation_type,
                    ', '.join(sorted({o.dataset_name for o in r.occurrences})),str(len(r.occurrences)))
            for col,value in enumerate(values):
                item=QTableWidgetItem(value);item.setToolTip(value+'\n'+i);item.setData(Qt.ItemDataRole.UserRole,neighbor)
                self.neighbors.setItem(row,col,item)

    def _navigate(self, kind, identifier):
        self.session.navigate(SearchResult(kind,identifier,identifier,None,identifier))

    def _select(self):
        items=self.selector.selectedItems()
        if items:self._navigate('entity',items[0].data(Qt.ItemDataRole.UserRole))

    def _neighbor(self,item):
        self._navigate('entity',item.data(Qt.ItemDataRole.UserRole))

    def _dataset(self,item):
        name=item.data(Qt.ItemDataRole.UserRole)
        if name not in self.session.view.dataset_names:
            self.message.setText('This occurrence belongs to a dataset hidden by the current scope.')
            return
        self._navigate('dataset',name)
