"""Read-only overview of the current investigation view."""
from collections import Counter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QProgressBar)
from cyber_analyst.findings.service import ATTENTION_LEVELS


class CountBars(QWidget):
    def __init__(self, title, empty_text):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(QLabel(title))
        self.empty = QLabel(empty_text)
        self.layout.addWidget(self.empty)
        self.rows = QWidget()
        self.grid = QGridLayout(self.rows)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.rows)
        self.counts = ()

    def render(self, counts):
        self.counts = tuple(counts)
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        self.empty.setVisible(not self.counts)
        self.rows.setVisible(bool(self.counts))
        maximum = max((count for _, count in self.counts), default=1)
        for row, (name, count) in enumerate(self.counts):
            label = QLabel(name)
            label.setTextFormat(Qt.TextFormat.PlainText)
            self.grid.addWidget(label, row, 0)
            bar = QProgressBar()
            bar.setRange(0, maximum)
            bar.setValue(count)
            bar.setFormat(str(count))
            bar.setStyleSheet('QProgressBar { border: 1px solid #35443b; text-align: center; } QProgressBar::chunk { background: #356047; }')
            self.grid.addWidget(bar, row, 1)
        self.grid.setColumnStretch(1, 1)


class InvestigationOverview(QStackedWidget):
    def __init__(self, session, legacy, parent=None):
        super().__init__(parent)
        self.session = session
        self.addWidget(legacy)
        self.dashboard = QWidget()
        self.addWidget(self.dashboard)
        layout = QVBoxLayout(self.dashboard)
        title = QLabel('Investigation Overview')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        cards = QGridLayout()
        self.metrics = {}
        for index, name in enumerate(('datasets', 'entities', 'relations', 'findings', 'analyses')):
            card = QWidget()
            box = QVBoxLayout(card)
            box.addWidget(QLabel('Visible ' + name))
            value = QLabel('0')
            value.setStyleSheet('font-size: 22px; color: #9bcbae;')
            box.addWidget(value)
            self.metrics[name] = value
            cards.addWidget(card, index // 3, index % 3)
        layout.addLayout(cards)
        self.entity_chart = CountBars('Entities by type', 'No visible entities.')
        self.attention_chart = CountBars('Findings by attention', 'No visible findings.')
        layout.addWidget(self.entity_chart)
        layout.addWidget(self.attention_chart)
        layout.addWidget(QLabel('Dataset coverage'))
        self.coverage = QTableWidget(0, 5)
        self.coverage.setHorizontalHeaderLabels(['Dataset', 'Entities', 'Relations', 'Findings', 'Analyses'])
        self.coverage.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.coverage.verticalHeader().hide()
        self.coverage.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.coverage.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.coverage)
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        context, view = self.session.context, self.session.view
        if context is None:
            self.setCurrentIndex(0)
            return
        self.setCurrentIndex(1)
        collections = (view.dataset_names, view.entity_ids, view.relation_ids, view.finding_ids, view.analysis_ids)
        for label, values in zip(self.metrics.values(), collections):
            label.setText(str(len(values)))
        types = Counter(context.entities[i].entity_type for i in view.entity_ids)
        self.entity_chart.render(sorted(types.items(), key=lambda pair: (-pair[1], pair[0])))
        attention = Counter(context.findings[i].attention_level for i in view.finding_ids)
        self.attention_chart.render((level, attention[level]) for level in ATTENTION_LEVELS if attention[level])
        visible_entities, visible_relations, visible_findings = map(set, collections[1:4])
        visible_analyses = set(view.analysis_ids)
        self.coverage.setRowCount(len(view.dataset_names))
        for row, name in enumerate(view.dataset_names):
            d = context.datasets[name]
            values = (name, len(visible_entities.intersection(d.entity_ids)),
                      len(visible_relations.intersection(d.relation_ids)),
                      len(visible_findings.intersection(d.finding_ids)),
                      sum((name, i) in visible_analyses for i in d.analysis_result_ids))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.coverage.setItem(row, column, item)
        self.coverage.setMinimumHeight(80)
        self.coverage.setMaximumHeight(45 + 30 * max(1, len(view.dataset_names)))
