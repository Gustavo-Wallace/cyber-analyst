"""Presentation of committed joins; no correlation execution."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem, QSplitter
from cyber_analyst.context import SearchResult
from .investigation_analysis_page import table, text
from .investigation_overview import CountBars

class InvestigationCorrelationPage(QWidget):
    def __init__(self, session):
        super().__init__()
        self.session = session
        layout = QVBoxLayout(self)
        title = QLabel('Automatic correlations')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        self.message = QLabel()
        layout.addWidget(self.message)
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)
        self.selector = table(['Left dataset','Left column','Right dataset','Right column','Common keys','Matched rows'])
        splitter.addWidget(self.selector)
        self.panel = QWidget()
        detail = QVBoxLayout(self.panel)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        detail.addWidget(self.summary)
        buttons = QHBoxLayout()
        self.left = QPushButton('Focus left dataset')
        self.right = QPushButton('Focus right dataset')
        buttons.addWidget(self.left);buttons.addWidget(self.right)
        detail.addLayout(buttons)
        self.overlap = CountBars('Key overlap', 'No overlap metrics.')
        detail.addWidget(self.overlap)
        self.preview_label = QLabel()
        detail.addWidget(self.preview_label)
        self.preview = table([])
        detail.addWidget(self.preview)
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(0,1);splitter.setStretchFactor(1,2)
        self.left.clicked.connect(lambda:self._dataset('left_dataset'))
        self.right.clicked.connect(lambda:self._dataset('right_dataset'))
        self.selector.itemSelectionChanged.connect(self._select)
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        s=self.session
        ids=s.view.correlation_ids if s.view else ()
        focus=s.state.focus.correlation_id if s.state else None
        with QSignalBlocker(self.selector):
            self.selector.setRowCount(0);self.selector.setRowCount(len(ids))
            for row,identifier in enumerate(ids):
                c=s.context.correlations[identifier];m=c.correlation_result.summary
                for col,value in enumerate((c.left_dataset,c.left_column,c.right_dataset,c.right_column,m.common,m.matched_rows)):
                    item=QTableWidgetItem(str(value));item.setData(Qt.ItemDataRole.UserRole,identifier);item.setToolTip(str(value)+'\n'+identifier)
                    self.selector.setItem(row,col,item)
                if focus==identifier:self.selector.setCurrentCell(row,0);self.selector.selectRow(row)
        self.message.setText('No active investigation.' if s.context is None else
            'Focused correlation is hidden by filters.' if focus and focus not in ids else
            f'{len(ids)} visible automatic correlations' if ids else 'No correlations in the current investigation view.')
        self.selector.setVisible(bool(ids))
        self.panel.setVisible(focus in ids)
        self.preview.setRowCount(0)
        if focus not in ids:return
        c=s.context.correlations[focus];result=c.correlation_result;m=result.summary
        self.summary.setText(f'{c.left_dataset}.{c.left_column}\n<-> {c.right_dataset}.{c.right_column}\n'
            f'Common keys: {m.common} | Matched rows: {m.matched_rows}\nLeft-only keys: {m.only_a} | Right-only keys: {m.only_b}')
        self.summary.setToolTip(focus)
        self.overlap.render((('Common',m.common),('Left only',m.only_a),('Right only',m.only_b)))
        self.preview_label.setText(f'Committed preview: {len(result.preview_rows)} rows (may be bounded)' if result.preview_rows else 'No matched preview rows.')
        self.preview.setVisible(bool(result.preview_rows))
        self.preview.setColumnCount(len(result.preview_columns));self.preview.setHorizontalHeaderLabels(result.preview_columns)
        self.preview.setRowCount(len(result.preview_rows))
        for row,values in enumerate(result.preview_rows):
            for col,value in enumerate(values):
                item=QTableWidgetItem(text(value));item.setToolTip(text(value));self.preview.setItem(row,col,item)

    def _select(self):
        items=self.selector.selectedItems()
        if items:self.session.focus_correlation(items[0].data(Qt.ItemDataRole.UserRole))

    def _dataset(self,side):
        s=self.session;identifier=s.state.focus.correlation_id
        if identifier not in s.view.correlation_ids:return
        name=getattr(s.context.correlations[identifier],side)
        s.navigate(SearchResult('dataset',name,name,name,name))
