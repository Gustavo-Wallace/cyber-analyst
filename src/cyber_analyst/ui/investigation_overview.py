"""Visible investigation metadata and deterministic navigation, without execution."""
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QProgressBar, QPushButton, QSizePolicy)
from cyber_analyst.analyst import AnalystReference
from .theme import SPACE, label, panel, role, table_style
from .workstation import WorkspacePages
from .count_labels import count_label
from .dashboard_visuals import select_visuals, human_label, ATTENTION_ORDER
from .chart_factory import VisualPanel
from .next_steps import NextStepsWidget



class MetricButton(QPushButton):
    """A native action whose labels, rather than empty button text, set its size."""
    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return QSize(0, self.sizeHint().height())


class ResponsiveGrid(QWidget):
    """Reflow a few native panels; no fixed desktop widths or hidden controls."""
    def __init__(self, widgets, minimum_width, maximum_columns, align_top=False):
        super().__init__()
        self.widgets = tuple(widgets)
        self.minimum_width, self.maximum_columns = minimum_width, maximum_columns
        self.align_top = align_top
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
            self.grid.addWidget(widget, index // columns, index % columns,
                                Qt.AlignmentFlag.AlignTop if self.align_top else Qt.AlignmentFlag(0))
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

    def replace_widgets(self, widgets):
        while self.grid.count():
            item = self.grid.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        self.widgets = tuple(widgets)
        self.columns = 0
        self._reflow()


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
    detail_requested = Signal(str)

    def __init__(self, session, legacy, parent=None):
        super().__init__(parent)
        self.session = session
        self.addWidget(legacy)
        self.dashboard = role(QWidget(), 'canvas')
        self.addWidget(self.dashboard)
        layout = QVBoxLayout(self.dashboard)
        layout.setContentsMargins(SPACE['lg'], SPACE['lg'], SPACE['lg'], SPACE['lg'])
        layout.setSpacing(SPACE['lg'])
        self.metrics, self.metric_buttons, cards = {}, {}, []
        headings = {'datasets': 'Datasets', 'entities': 'Identifiers', 'relations': 'Connections',
                    'findings': 'Alerts', 'analyses': 'Analysis', 'correlations': 'Data matches'}
        for name in headings:
            card = role(MetricButton() if name != 'datasets' else QWidget(), 'metric')
            if name != 'datasets':
                card.setAccessibleName('Open ' + headings[name])
                card.setToolTip('Open ' + headings[name])
                card.clicked.connect(lambda checked=False, key=name: self.detail_requested.emit(key))
                self.metric_buttons[name] = card
            box = QVBoxLayout(card)
            box.setContentsMargins(SPACE['md'], SPACE['md'], SPACE['md'], SPACE['md'])
            box.setSpacing(SPACE['xs'])
            heading = label(headings[name], 'caption')
            heading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            box.addWidget(heading)
            value = label('0', 'card_value', 'violet' if name == 'findings' else 'cyan')
            value.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            box.addWidget(value)
            self.metrics[name] = value
            cards.append(card)
        self.cards = ResponsiveGrid(cards, 108, 6)
        layout.addWidget(self.cards)
        self.data_summary = label('', 'caption')
        layout.addWidget(self.data_summary)
        self.filtered_empty = label('No results are visible in the current view. Adjust the active filters.', 'caption')
        layout.addWidget(self.filtered_empty)
        self.visual_specs = ()
        self.visual_panels = {}
        self.visual_grid = ResponsiveGrid((), 410, 3, align_top=True)
        layout.addWidget(self.visual_grid)
        self.highlights_heading = label('Investigation highlights', 'section_title')
        layout.addWidget(self.highlights_heading)
        self.finding_highlights = Highlights('Alerts to review', 'Highest attention first. Up to three shown.', 'No visible alerts to review.')
        self.entity_highlights = Highlights('Connected identifiers', 'Most direct connections first. Up to three shown.', 'No visible identifiers.')
        self.correlation_highlights = Highlights('Dataset matches', 'Most shared keys first. Up to two shown.', 'No visible dataset matches.')
        self.highlights_grid = ResponsiveGrid((self.finding_highlights, self.entity_highlights, self.correlation_highlights), 280, 3, align_top=True)
        layout.addWidget(self.highlights_grid)
        self.next_steps = NextStepsWidget(session)
        self.next_steps.navigated.connect(self.target_requested)
        layout.addWidget(self.next_steps)
        coverage_panel, box = panel('Dataset coverage', 'Visible investigation objects by source dataset. Select a row to inspect its counts.')
        self.coverage = QTableWidget(0, 5)
        self.coverage.setHorizontalHeaderLabels(['Dataset', 'Identifiers', 'Connections', 'Alerts', 'Analysis'])
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

    def _visual_activate(self, target):
        context, view = self.session.context, self.session.view
        if view is None:
            raise ValueError('No active investigation for this chart')
        if target.reference is not None:
            self._activate(target.reference)
        else:
            if target.page == 'entities' and target.filter_value:
                if not any(context.entities[i].entity_type == target.filter_value for i in view.entity_ids):
                    raise ValueError('Identifier category is no longer visible')
                self.session.set_entity_types((target.filter_value,))
            elif target.page == 'findings' and target.filter_value:
                if not any(context.findings[i].attention_level == target.filter_value for i in view.finding_ids):
                    raise ValueError('Attention category is no longer visible')
                self.session.set_attention_levels((target.filter_value,))
            self.detail_requested.emit(target.page)

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
        specs = select_visuals(context, view)
        if specs != self.visual_specs:
            self.visual_specs = specs
            self.visual_panels = {spec.key: VisualPanel(spec) for spec in specs}
            for widget in self.visual_panels.values():
                widget.activated.connect(self._visual_activate)
            self.visual_grid.replace_widgets(self.visual_panels.values())
            self.visual_grid.setVisible(bool(specs))
        self.entity_chart = self.visual_panels.get('identifier_types')
        self.attention_chart = self.visual_panels.get('attention')
        finding_rows = []
        for i in sorted(view.finding_ids, key=lambda i: (ATTENTION_ORDER.index(context.findings[i].attention_level), i))[:3]:
            finding = context.findings[i]
            evidence = context.evidence_for(i)
            sources = ', '.join(sorted({e.dataset_name for e in evidence}))
            operations = ', '.join(sorted({e.operation for e in evidence}))
            finding_rows.append((AnalystReference('finding', i), f'{finding.attention_level.upper()}  |  {human_label(operations)}\n{sources}', i + '\n' + operations + '\n' + sources))
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
        has_highlights = bool(finding_rows or entities or correlation_rows)
        self.highlights_heading.setVisible(has_highlights)
        self.highlights_grid.setVisible(has_highlights)
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
