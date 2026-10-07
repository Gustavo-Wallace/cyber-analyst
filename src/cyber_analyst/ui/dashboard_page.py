"""Visão barata da sessão, baseada somente em metadados e resultados existentes."""

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QPainter
from PySide6.QtCharts import QBarCategoryAxis, QBarSet, QChart, QChartView, QHorizontalBarSeries, QValueAxis
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QLabel, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from cyber_analyst.data.dataset_collection import DatasetCollection
from cyber_analyst.data.session_results import SessionResults
from .theme import COLORS, SPACE, label as themed_label, role, table_style


class DashboardPage(QWidget):
    def __init__(self, collection: DatasetCollection, results: SessionResults) -> None:
        super().__init__()
        self.collection = collection
        self.results = results
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(SPACE['lg'], SPACE['lg'], SPACE['lg'], SPACE['lg'])
        layout.setSpacing(SPACE['lg'])
        scroll.setWidget(content)
        outer.addWidget(scroll)
        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.empty_panel = QWidget()
        empty_layout = QVBoxLayout(self.empty_panel)
        empty_layout.addStretch()
        self.empty_label = themed_label('No active investigation', 'section_title')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_label)
        caption = themed_label('Load datasets to begin. Manual session results remain available before an investigation is completed.', 'caption')
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_caption = caption
        empty_layout.addWidget(caption)
        empty_layout.addStretch()
        layout.addWidget(self.empty_panel, 1)
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(18)
        cards = QGridLayout()
        self.kpis = {}
        for index, (key, label) in enumerate((
            ("datasets", "Datasets carregados"), ("rows", "Total de linhas"),
            ("columns", "Total de colunas (soma)"), ("largest", "Maior dataset"),
        )):
            card = role(QWidget(), 'metric')
            card_layout = QVBoxLayout(card)
            heading = role(QLabel(label), 'caption')
            heading.setWordWrap(True)
            value = QLabel()
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            role(value, 'card_value')
            card_layout.addWidget(heading)
            card_layout.addWidget(value)
            cards.addWidget(card, index // 2, index % 2)
            self.kpis[key] = value
        body_layout.addLayout(cards)
        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        body_layout.addWidget(self.chart_view)
        body_layout.addWidget(QLabel("Datasets da sessão"))
        self.dataset_table = QTableWidget(0, 4)
        self.dataset_table.setHorizontalHeaderLabels(["Dataset", "Linhas", "Colunas", "Caminho"])
        self.dataset_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dataset_table.setMinimumHeight(180)
        self.dataset_table.horizontalHeader().setDefaultSectionSize(150)
        table_style(self.dataset_table)
        body_layout.addWidget(self.dataset_table)
        body_layout.addWidget(QLabel("Última análise"))
        self.analysis_label = QLabel()
        body_layout.addWidget(self.analysis_label)
        body_layout.addWidget(QLabel("Última correlação"))
        self.correlation_label = QLabel()
        body_layout.addWidget(self.correlation_label)
        for label in (self.analysis_label, self.correlation_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
        layout.addWidget(self.body)
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        datasets = self.collection.values()
        self.empty_panel.setVisible(not datasets)
        self.body.setVisible(bool(datasets))
        self.dataset_table.setRowCount(len(datasets))
        self.kpis["datasets"].setText(str(len(datasets)))
        self.kpis["rows"].setText(str(sum(dataset.row_count for dataset in datasets)))
        self.kpis["columns"].setText(str(sum(dataset.column_count for dataset in datasets)))
        largest = max(datasets, key=lambda dataset: dataset.row_count, default=None)
        self.kpis["largest"].setText(f"{largest.name}\n{largest.row_count} linhas" if largest else "")
        for row, dataset in enumerate(datasets):
            for column, value in enumerate((dataset.name, dataset.row_count, dataset.column_count, dataset.path)):
                self.dataset_table.setItem(row, column, QTableWidgetItem(str(value)))
        self._update_chart(datasets)
        analysis = self.results.last_analysis
        if analysis is None:
            self.analysis_label.setText("Nenhuma análise executada nesta sessão.")
        else:
            profile = analysis.profile
            self.analysis_label.setText(
                f"{analysis.dataset.name}\n{analysis.dataset.path}\n"
                f"Linhas: {profile.row_count} · Colunas: {profile.column_count} · Nulos: {profile.null_count}\n"
                f"Colunas analisadas: {len(profile.columns)}"
            )
        correlation = self.results.last_correlation
        if correlation is None:
            self.correlation_label.setText("Nenhuma correlação executada nesta sessão.")
        else:
            summary = correlation.summary
            self.correlation_label.setText(
                f"A: {correlation.dataset_a.name} · {correlation.column_a}\n"
                f"B: {correlation.dataset_b.name} · {correlation.column_b}\n"
                f"Em comum: {summary.common} · Somente A: {summary.only_a} · Somente B: {summary.only_b}\n"
                f"Linhas correlacionadas: {summary.matched_rows}"
            )

    def _update_chart(self, datasets) -> None:
        chart = QChart()
        chart.setTitle("Linhas por dataset")
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        chart.setBackgroundBrush(QColor(COLORS['canvas']))
        chart.setTitleBrush(QColor(COLORS['text']))
        chart.legend().hide()
        self.bar_set = QBarSet("Linhas")
        self.bar_set.setColor(QColor(COLORS['cyan']))
        self.bar_set.setBorderColor(QColor(COLORS['cyan']))
        self.series = QHorizontalBarSeries()
        if datasets:
            self.bar_set.append([float(dataset.row_count) for dataset in datasets])
            self.series.append(self.bar_set)
        chart.addSeries(self.series)
        self.category_axis = QBarCategoryAxis()
        self.category_axis.append([f"{index + 1}. {dataset.name}" for index, dataset in enumerate(datasets)])
        values = QValueAxis()
        maximum = max(1, max((dataset.row_count for dataset in datasets), default=0))
        values.setRange(0, maximum)
        values.setTickCount(min(5, maximum + 1))
        values.setLabelFormat("%.0f")
        for axis, alignment in ((self.category_axis, Qt.AlignmentFlag.AlignLeft), (values, Qt.AlignmentFlag.AlignBottom)):
            axis.setLabelsColor(QColor(COLORS['secondary']))
            axis.setGridLineColor(QColor(COLORS['border']))
            chart.addAxis(axis, alignment)
            self.series.attachAxis(axis)
        old = self.chart_view.chart()
        self.chart_view.setChart(chart)
        old.deleteLater()
        self.chart_view.setFixedHeight(max(280, 100 + 32 * len(datasets)))
