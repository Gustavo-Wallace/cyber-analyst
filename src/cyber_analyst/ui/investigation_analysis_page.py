"""Browse committed results; never execute analyses or reinterpret evidence."""
import json
import math
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtCharts import QChart, QChartView, QBarSeries, QBarSet, QBarCategoryAxis, QLineSeries, QValueAxis
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QStackedWidget, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QSplitter)
from cyber_analyst.context import SearchResult


def text(value):
    return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


class InvestigationAnalysisPage(QStackedWidget):
    def __init__(self, session, legacy, parent=None):
        super().__init__(parent)
        self.session = session
        self.addWidget(legacy)
        self.page = QWidget()
        self.addWidget(self.page)
        layout = QVBoxLayout(self.page)
        title = QLabel('Investigation analyses')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)
        self.selector = table(['Dataset', 'Operation', 'Title'])
        splitter.addWidget(self.selector)
        detail = QWidget()
        details = QVBoxLayout(detail)
        self.heading = QLabel()
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        details.addWidget(self.heading)
        self.statistics = QLabel()
        self.statistics.setTextFormat(Qt.TextFormat.PlainText)
        self.statistics.setWordWrap(True)
        details.addWidget(self.statistics)
        self.chart_view = QChartView()
        self.chart_view.setMinimumHeight(200)
        details.addWidget(self.chart_view, 2)
        self.result_table = table([])
        details.addWidget(self.result_table, 1)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        self.chart_kind = None
        self.selector.itemSelectionChanged.connect(self._select)
        self.selector.itemActivated.connect(lambda _: self._select())
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        s = self.session
        if s.context is None:
            self.setCurrentIndex(0)
            return
        self.setCurrentIndex(1)
        ids = s.view.analysis_ids
        f = s.state.focus.analysis
        selected = (f.dataset_name, f.analysis_id) if f else None
        with QSignalBlocker(self.selector):
            self.selector.setRowCount(0)
            self.selector.setRowCount(len(ids))
            for row, pair in enumerate(ids):
                step = s.context.analyses[pair]
                for col, value in enumerate((pair[0], step.operation, step.title)):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, pair)
                    item.setToolTip(value + '\n' + pair[1])
                    self.selector.setItem(row, col, item)
                if selected == pair:
                    self.selector.setCurrentCell(row, 0)
                    self.selector.selectRow(row)
        self.selector.setVisible(bool(ids))
        self.message.setText(f'{len(ids)} visible analyses' if ids else 'No analyses match the current investigation view.')
        self.heading.setText('Focused analysis is hidden by filters.' if selected and selected not in ids else 'Select a visible analysis.')
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self.result_table.hide()
        self.statistics.clear()
        self.statistics.hide()
        self.chart_kind = None
        old = self.chart_view.chart()
        chart = QChart()
        self.chart_view.setChart(chart)
        if old is not None: old.deleteLater()
        self.chart_view.hide()
        if selected not in ids:
            return
        step = s.context.analyses[selected]
        self.heading.setText(f'{selected[0]} | {step.operation}\n{step.title}' + ('\nNo result rows.' if not step.rows else ''))
        self.heading.setToolTip(selected[1])
        self.result_table.setColumnCount(len(step.columns))
        self.result_table.setHorizontalHeaderLabels(step.columns)
        self.result_table.setRowCount(len(step.rows))
        for row, values in enumerate(step.rows):
            for col, value in enumerate(values):
                item = QTableWidgetItem(text(value))
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setToolTip(text(value))
                self.result_table.setItem(row, col, item)
        self.result_table.show()
        if step.operation in ('numeric_summary', 'null_analysis', 'unique_count') and step.rows:
            self.statistics.setText('\n'.join(' | '.join(f'{name}: {text(value)}' for name, value in zip(step.columns, row)) for row in step.rows[:3]) + ('\nAdditional rows are available in the complete table below.' if len(step.rows) > 3 else ''))
            self.statistics.show()
        chartable = step.operation in ('column_distribution','top_values','group_count','cross_tab','time_series_count')
        valid = (step.rows and len(step.columns) >= 2 and step.columns[-1] == 'count'
                 and all(len(row) == len(step.columns) and type(row[-1]) in (int,float)
                         and math.isfinite(row[-1]) and abs(row[-1]) <= 2**53 for row in step.rows))
        if not chartable or not valid or len(step.rows) > 50:
            if step.rows:
                self.heading.setText(self.heading.text() + '\nCommitted statistics / result table (no chart).')
            return
        labels = [' | '.join(text(value) for value in row[:-1]) for row in step.rows]
        if len(set(labels)) != len(labels): return
        if step.operation == 'time_series_count':
            # Only an ungrouped, ordered daily series can form one safe line.
            from datetime import date
            if len(step.columns) != 2: return
            try: days = [date.fromisoformat(row[0]) for row in step.rows]
            except (TypeError, ValueError): return
            if days != sorted(days): return
            series = QLineSeries()
            for day, row in zip(days, step.rows): series.append(day.toordinal(), row[-1])
            chart.addSeries(series)
            from PySide6.QtCharts import QCategoryAxis
            axis = QCategoryAxis()
            for day, row in zip(days, step.rows): axis.append(row[0], day.toordinal())
            axis.setLabelsPosition(QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
            chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
            series.attachAxis(axis)
            self.chart_kind = 'line'
        else:
            series = QBarSeries()
            values = QBarSet('count')
            values.append([row[-1] for row in step.rows])
            series.append(values)
            chart.addSeries(series)
            axis = QBarCategoryAxis()
            axis.append(labels)
            chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
            series.attachAxis(axis)
            self.chart_kind = 'bar'
        y = QValueAxis()
        chart.addAxis(y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(y)
        y.setRange(min(0, min(row[-1] for row in step.rows)), max(1, max(row[-1] for row in step.rows)))
        chart.legend().hide()
        chart.setBackgroundBrush(QColor('#181c1b'))
        for axis in chart.axes(): axis.setLabelsColor(QColor('#dce3df'))
        self.chart_view.show()

    def _select(self):
        items = self.selector.selectedItems()
        if items:
            name, identifier = items[0].data(Qt.ItemDataRole.UserRole)
            self.session.navigate(SearchResult('analysis', identifier, identifier, name, identifier))
