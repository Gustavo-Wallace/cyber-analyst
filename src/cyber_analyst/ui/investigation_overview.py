"""Visible investigation metadata and deterministic navigation, without execution."""
from collections import Counter
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QProgressBar, QPushButton, QSizePolicy)
from cyber_analyst.analyst import AnalystReference
from .theme import SPACE, label, panel, role, table_style
from .workstation import WorkspacePages
from .count_labels import count_label

ATTENTION_ORDER = ('high', 'medium', 'low', 'informational')


class ResponsiveGrid(QWidget):
    """Reflow a few native panels; no fixed desktop widths or hidden controls."""
    def __init__(self, widgets, minimum_width, maximum_columns):
        super().__init__()
        self.widgets = tuple(widgets)
        self.minimum_width, self.maximum_columns = minimum_width, maximum_columns
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(SPACE['md'])
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._reflow()

    def _columns(self, width):
        return max(1, min(self.maximum_columns, (width + SPACE['md']) // (self.minimum_width + SPACE['md'])))

    def _reflow(self):
        columns = self._columns(self.width())
        if columns == self.columns:
            return
        for index in range(self.maximum_columns):
            self.grid.setColumnStretch(index, 0)
        for index, widget in enumerate(self.widgets):
            self.grid.addWidget(widget, index // columns, index % columns)
        for index in range(columns):
            self.grid.setColumnStretch(index, 1)
        self.columns = columns
        self.updateGeometry()

    def resizeEvent(self, event):
        self._reflow()
        super().resizeEvent(event)

    def heightForWidth(self, width):
        columns = self._columns(width)
        rows = (len(self.widgets) + columns - 1) // columns
        return rows * max((w.sizeHint().height() for w in self.widgets), default=0) + max(0, rows - 1) * SPACE['md']

    def minimumSizeHint(self):
        return QSize(0, 0)


class CountBars(QWidget):
    def __init__(self, title, empty_text, description='', tone='cyan'):
        super().__init__()
        role(self, 'panel')
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(SPACE['lg'], SPACE['md'], SPACE['lg'], SPACE['md'])
        self.layout.setSpacing(SPACE['sm'])
        self.layout.addWidget(label(title, 'section_title'))
        if description:
            self.layout.addWidget(label(description, 'caption'))
        self.empty = label(empty_text, 'caption')
        self.layout.addWidget(self.empty)
        self.rows = QWidget()
        self.grid = QGridLayout(self.rows)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(SPACE['md'])
        self.grid.setVerticalSpacing(SPACE['sm'])
        self.layout.addWidget(self.rows)
        self.layout.addStretch()
        self.counts, self.tone = (), tone

    def render(self, counts):
        self.counts = tuple(counts)
        while self.grid.count():
            item = self.grid.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        self.empty.setVisible(not self.counts)
        self.rows.setVisible(bool(self.counts))
        maximum = max((count for _, count in self.counts), default=1)
        for row, (name, count) in enumerate(self.counts):
            self.grid.addWidget(label(name, 'body'), row, 0)
            bar = QProgressBar()
            role(bar, 'count_bar', self.tone)
            bar.setRange(0, maximum)
            bar.setValue(count)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setToolTip(f'{name}: {count}')
            self.grid.addWidget(bar, row, 1)
            value = label(str(count), 'body')
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.grid.addWidget(value, row, 2)
        self.grid.setColumnStretch(1, 1)
        self.updateGeometry()


class Highlights(QWidget):
    def __init__(self, title, description, empty_text):
        super().__init__()
        role(self, 'panel')
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(SPACE['lg'], SPACE['md'], SPACE['lg'], SPACE['md'])
        self.box.setSpacing(SPACE['sm'])
        self.box.addWidget(label(title, 'section_title'))
        self.box.addWidget(label(description, 'caption'))
        self.empty = label(empty_text, 'caption')
        self.box.addWidget(self.empty)
        self.buttons = ()
        self.box.addStretch()

    def render(self, rows, activate):
        for button in self.buttons:
            self.box.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.empty.setVisible(not rows)
        buttons = []
        for reference, text, tooltip in rows:
            button = role(QPushButton(text.replace('&', '&&')), 'highlight')
            button.setToolTip(tooltip)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            button.clicked.connect(lambda checked=False, ref=reference: activate(ref))
            self.box.insertWidget(self.box.count() - 1, button)
            buttons.append(button)
        self.buttons = tuple(buttons)
        self.updateGeometry()


class InvestigationOverview(WorkspacePages):
    target_requested = Signal(object)

    def __init__(self, session, legacy, parent=None):
        super().__init__(parent)
        self.session = session
        self.addWidget(legacy)
        self.dashboard = role(QWidget(), 'canvas')
        self.addWidget(self.dashboard)
        layout = QVBoxLayout(self.dashboard)
        layout.setContentsMargins(SPACE['lg'], SPACE['lg'], SPACE['lg'], SPACE['lg'])
        layout.setSpacing(SPACE['lg'])
        self.metrics, cards = {}, []
        for name in ('datasets', 'entities', 'relations', 'findings', 'analyses', 'correlations'):
            card = role(QWidget(), 'metric')
            box = QVBoxLayout(card)
            box.setContentsMargins(SPACE['md'], SPACE['md'], SPACE['md'], SPACE['md'])
            box.setSpacing(SPACE['xs'])
            box.addWidget(label(name.capitalize(), 'caption'))
            value = label('0', 'card_value', 'violet' if name == 'findings' else 'cyan')
            box.addWidget(value)
            self.metrics[name] = value
            cards.append(card)
        self.cards = ResponsiveGrid(cards, 108, 6)
        layout.addWidget(self.cards)
        self.data_summary = label('', 'caption')
        layout.addWidget(self.data_summary)
        self.filtered_empty = label('No results are visible in the current view. Adjust the active filters.', 'caption')
        layout.addWidget(self.filtered_empty)
        self.attention_chart = CountBars('Finding attention', 'No visible findings. Adjust filters or review the other investigation objects.',
                                        'Stored investigation priority, not vulnerability severity.', 'tertiary')
        self.entity_chart = CountBars('Entity types', 'No visible entities.', 'Distribution of the current investigation view.', 'cyan')
        layout.addWidget(ResponsiveGrid((self.attention_chart, self.entity_chart), 280, 2))
        layout.addWidget(label('Investigation highlights', 'section_title'))
        self.finding_highlights = Highlights('Findings to review', 'Ordered by attention, then stable ID. Up to three shown.', 'No visible findings to review.')
        self.entity_highlights = Highlights('Connected entities', 'Ordered by visible direct relations. Up to three shown.', 'No visible entities.')
        self.correlation_highlights = Highlights('Executed correlations', 'Ordered by common keys, then matched rows. Up to two shown.', 'No visible executed correlations.')
        layout.addWidget(ResponsiveGrid((self.finding_highlights, self.entity_highlights, self.correlation_highlights), 280, 3))
        coverage_panel, box = panel('Dataset coverage', 'Visible investigation objects by source dataset. Select a row to inspect its counts.')
        self.coverage = QTableWidget(0, 5)
        self.coverage.setHorizontalHeaderLabels(['Dataset', 'Entities', 'Relations', 'Findings', 'Analyses'])
        self.coverage.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.coverage.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.coverage.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.coverage.verticalHeader().hide()
        self.coverage.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.coverage.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table_style(self.coverage)
        self.coverage.itemClicked.connect(lambda item: self._activate(
            AnalystReference('dataset', self.coverage.item(item.row(), 0).text())))
        box.addWidget(self.coverage)
        self.coverage_empty = label('No visible datasets.', 'caption')
        box.addWidget(self.coverage_empty)
        layout.addWidget(coverage_panel)
        layout.addStretch()
        session.changed.connect(self.refresh)
        self.refresh()

    def _activate(self, reference):
        self.session.navigate_reference(reference)
        self.target_requested.emit(reference)

    def refresh(self):
        context, view = self.session.context, self.session.view
        if context is None:
            self.setCurrentIndex(0)
            return
        self.setCurrentIndex(1)
        collections = (view.dataset_names, view.entity_ids, view.relation_ids, view.finding_ids, view.analysis_ids, view.correlation_ids)
        for value, values in zip(self.metrics.values(), collections):
            value.setText(str(len(values)))
        visible_names = set(view.dataset_names)
        loaded = [entry.dataset for entry in self.session.result.datasets if entry.dataset.name in visible_names]
        self.data_summary.setText(
            count_label(sum(d.row_count for d in loaded), 'source row', number_format=',') + ' | ' +
            count_label(sum(d.column_count for d in loaded), 'source column', number_format=',') +
            ' across visible datasets')
        self.filtered_empty.setVisible(not any(collections[1:]))
        types = Counter(context.entities[i].entity_type for i in view.entity_ids)
        self.entity_chart.render(sorted(types.items(), key=lambda pair: (-pair[1], pair[0])))
        attention = Counter(context.findings[i].attention_level for i in view.finding_ids)
        self.attention_chart.render((level, attention[level]) for level in ATTENTION_ORDER if attention[level])
        finding_rows = []
        for i in sorted(view.finding_ids, key=lambda i: (ATTENTION_ORDER.index(context.findings[i].attention_level), i))[:3]:
            finding = context.findings[i]
            evidence = context.evidence_for(i)
            sources = ', '.join(sorted({e.dataset_name for e in evidence}))
            operations = ', '.join(sorted({e.operation for e in evidence}))
            finding_rows.append((AnalystReference('finding', i), f'{finding.attention_level.upper()}  |  {operations}\n{sources}', i + '\n' + sources))
        self.finding_highlights.render(finding_rows, self._activate)
        visible_entities, visible_relations, visible_findings = map(set, collections[1:4])
        entities = sorted(view.entity_ids, key=lambda i: (-len(visible_relations.intersection(context.entities[i].relation_ids)),
                                                          context.entities[i].entity_type, context.entities[i].canonical_value, i))[:3]
        self.entity_highlights.render([(AnalystReference('entity', i),
            f'{context.entities[i].canonical_value}\n{context.entities[i].entity_type} | ' +
            count_label(len(visible_relations.intersection(context.entities[i].relation_ids)), 'visible relation'),
            i + '\n' + context.entities[i].canonical_value) for i in entities], self._activate)
        correlation_rows = []
        for i in sorted(view.correlation_ids, key=lambda i: (-context.correlations[i].correlation_result.summary.common,
                                                            -context.correlations[i].correlation_result.summary.matched_rows, i))[:2]:
            c = context.correlations[i]
            m = c.correlation_result.summary
            endpoints = f'{c.left_dataset}.{c.left_column} <-> {c.right_dataset}.{c.right_column}'
            correlation_rows.append((AnalystReference('correlation', i), f'{c.left_column} <-> {c.right_column}\n' +
                count_label(m.common, 'common key') + ' | ' + count_label(m.matched_rows, 'matched row'), endpoints + '\n' + i))
        self.correlation_highlights.render(correlation_rows, self._activate)
        visible_analyses = set(view.analysis_ids)
        self.coverage.setRowCount(len(view.dataset_names))
        for row, name in enumerate(view.dataset_names):
            d = context.datasets[name]
            values = (name, len(visible_entities.intersection(d.entity_ids)), len(visible_relations.intersection(d.relation_ids)),
                      len(visible_findings.intersection(d.finding_ids)), sum((name, i) in visible_analyses for i in d.analysis_result_ids))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.coverage.setItem(row, column, item)
        self.coverage.setVisible(bool(view.dataset_names))
        self.coverage_empty.setVisible(not view.dataset_names)
        self.coverage.setFixedHeight(self.coverage.horizontalHeader().sizeHint().height() +
            self.coverage.verticalHeader().defaultSectionSize() * min(6, max(1, len(view.dataset_names))) +
            2 * self.coverage.frameWidth())
