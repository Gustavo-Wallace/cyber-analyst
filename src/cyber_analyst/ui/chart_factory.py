"""Native rendering of bounded DashboardVisual specs, with no data access."""
from datetime import date
from PySide6.QtCore import Qt, QSize, QRectF, Signal, QMargins
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QCursor
from PySide6.QtCharts import (QChart, QChartView, QPieSeries, QBarSeries, QBarSet,
    QBarCategoryAxis, QValueAxis, QLineSeries)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout,
    QPushButton, QToolTip, QSizePolicy)
from .theme import COLORS, SPACE, DATA_PALETTE, ATTENTION_COLORS, data_colors, label, role


def point_color(spec, point):
    return ATTENTION_COLORS[point.color_key] if spec.attention else data_colors(
        p.color_key for p in spec.series[0].points)[point.color_key]


def _axis_labels(points):
    labels = [p.label if len(p.label) <= 18 else p.label[:15] + '...' for p in points]
    if len(set(labels)) != len(labels):
        # Qt category axes require distinct labels. Keep clipped source names
        # distinguishable; full values remain in the original specs/tooltips.
        labels = [f'{p.label[:12]}... [{i+1}]' for i, p in enumerate(points)]
    return labels


class CategoryBars(QWidget):
    """Readable category bars with exact tooltips and keyboard-accessible drill-down
    via the containing panel. Native painting avoids one Qt bar set per category.
    """
    clicked = Signal(int)

    def __init__(self, spec):
        super().__init__()
        self.spec = spec
        self.points = spec.series[0].points
        self.selected = None
        self.setMouseTracking(True)
        self.setMinimumHeight(max(170, len(self.points) * 24))
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self):
        return QSize(300, self.minimumHeight())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font()); font.setPixelSize(11)
        painter.setFont(font)
        height = self.height() / len(self.points)
        maximum = max(p.value for p in self.points) or 1
        value_width = min(self.width() * .25, max(painter.fontMetrics().horizontalAdvance(str(p.value)) for p in self.points) + 8)
        label_width = min(125, self.width() * .34)
        bar_width = max(1, self.width() - label_width - value_width - 16)
        for index, point in enumerate(self.points):
            y = index * height
            rect = QRectF(label_width + 8, y + height * .3, bar_width, height * .4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS['elevated']))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setBrush(QColor(point_color(self.spec, point)))
            filled = QRectF(rect); filled.setWidth(bar_width * point.value / maximum)
            painter.drawRoundedRect(filled, 3, 3)
            if self.selected == index:
                painter.setPen(QPen(QColor(COLORS['text']), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(COLORS['secondary']))
            text = painter.fontMetrics().elidedText(point.label, Qt.TextElideMode.ElideRight, int(label_width))
            painter.drawText(QRectF(0, y, label_width, height), Qt.AlignmentFlag.AlignVCenter, text)
            painter.setPen(QColor(COLORS['text']))
            painter.drawText(QRectF(label_width + bar_width + 16, y, value_width, height),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(point.value))

    def mouseMoveEvent(self, event):
        index = min(len(self.points)-1, max(0, int(event.position().y() * len(self.points) / self.height())))
        point = self.points[index]
        QToolTip.showText(event.globalPosition().toPoint(), f'{point.label}: {point.value}', self)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected = min(len(self.points)-1, max(0, int(event.position().y() * len(self.points) / self.height())))
            self.update()
            self.clicked.emit(self.selected)
        super().mousePressEvent(event)


class VisualPanel(QWidget):
    activated = Signal(object)

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self.spec = spec
        role(self, 'panel')
        self.setMinimumWidth(0)
        box = QVBoxLayout(self)
        box.setContentsMargins(SPACE['lg'], SPACE['md'], SPACE['lg'], SPACE['md'])
        box.setSpacing(SPACE['sm'])
        self.heading = label(spec.title, 'section_title')
        box.addWidget(self.heading)
        box.addWidget(label(spec.subtitle, 'caption'))
        self.chart_view = None
        self.bars = None
        self.buttons = []
        points = spec.series[0].points
        if spec.kind == 'horizontal_bar':
            self.bars = CategoryBars(spec)
            self.bars.clicked.connect(lambda i: self.activate_point(i))
            box.addWidget(self.bars, 1)
        elif spec.kind in ('ranked_list', 'metrics'):
            grid = QGridLayout()
            for i, point in enumerate(points):
                if spec.kind == 'ranked_list':
                    button = role(QPushButton(), 'highlight')
                    button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                    button.setText(f'{point.label.replace("&", "&&")}\n{spec.series[0].name}: {point.value}')
                    button.setToolTip(f'{point.label}: {point.value}')
                    button.setCheckable(True)
                    button.clicked.connect(lambda checked=False, index=i: self.activate_point(index))
                    self.buttons.append(button)
                    grid.addWidget(button, i, 0)
                else:
                    grid.addWidget(label(point.label, 'caption'), i, 0)
                    value = label(str(point.value), 'body')
                    value.setToolTip(str(point.value))
                    grid.addWidget(value, i, 1)
            grid.setColumnStretch(0, 1)
            box.addLayout(grid)
            box.addStretch()
        else:
            self.chart_view = QChartView(self._chart())
            self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.chart_view.setMinimumSize(0, 200)
            self.chart_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            box.addWidget(self.chart_view, 1)
            if spec.kind == 'donut':
                legend = QGridLayout()
                for i, point in enumerate(points):
                    name = label(f'{point.label}: {point.value}', 'caption')
                    name.setStyleSheet(f'color: {point_color(spec, point)}')
                    name.setToolTip(f'{point.label}: {point.value}')
                    legend.addWidget(name, i // 2, i % 2)
                box.addLayout(legend)
        if spec.target:
            self.open_button = role(QPushButton('Open analysis'), 'secondary')
            self.open_button.clicked.connect(lambda: self.activated.emit(spec.target))
            box.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignLeft)

    def minimumSizeHint(self):
        return QSize(0, self.layout().minimumSize().height())

    @property
    def counts(self):
        return tuple((p.label, p.value) for p in self.spec.series[0].points)

    def activate_point(self, index, series=0):
        if self.buttons:
            for i, button in enumerate(self.buttons):
                button.setChecked(i == index)
        point = self.spec.series[series].points[index]
        target = point.target or self.spec.target
        if target is not None:
            self.activated.emit(target)

    def _hover(self, text, active):
        if active:
            QToolTip.showText(QCursor.pos(), text, self)
        else:
            QToolTip.hideText()

    def _chart(self):
        spec = self.spec
        chart = QChart()
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        chart.setBackgroundBrush(QBrush(QColor(COLORS['surface'])))
        chart.setBackgroundPen(QPen(Qt.PenStyle.NoPen))
        chart.setPlotAreaBackgroundVisible(False)
        chart.setMargins(QMargins(0, 0, 0, 0))
        chart.legend().hide()
        points = spec.series[0].points
        if spec.kind == 'donut':
            pie = QPieSeries(); pie.setPieSize(.9); pie.setHoleSize(.55)
            for i, point in enumerate(points):
                slice_ = pie.append(point.label, point.value)
                slice_.setBrush(QColor(point_color(spec, point)))
                slice_.setPen(QPen(QColor(COLORS['surface']), 2))
                slice_.hovered.connect(lambda active, p=point: self._hover(f'{p.label}: {p.value}', active))
                slice_.clicked.connect(lambda s=slice_, index=i: (s.setExploded(not s.isExploded()), self.activate_point(index)))
            chart.addSeries(pie)
            return chart
        if spec.kind == 'line':
            line = QLineSeries()
            for point in points:
                line.append(date.fromisoformat(point.label).toordinal(), point.value)
            line.setPen(QPen(QColor(COLORS['cyan']), 2))
            series = line
            line.setPointsVisible(True)
            chart.addSeries(series)
            # Only a few exact dates on the axis; every point remains in hover data.
            from PySide6.QtCharts import QCategoryAxis
            axis = QCategoryAxis()
            stride = max(1, (len(points) - 1) // 3)
            for i in sorted(set((*range(0, len(points), stride), len(points)-1))):
                axis.append(points[i].label, date.fromisoformat(points[i].label).toordinal())
            axis.setLabelsPosition(QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
            axis.setRange(date.fromisoformat(points[0].label).toordinal(), date.fromisoformat(points[-1].label).toordinal())
            def hover(position, active):
                point = min(points, key=lambda p: abs(date.fromisoformat(p.label).toordinal() - position.x()))
                self._hover(f'{point.label}: {point.value}', active)
            series.hovered.connect(hover)
            series.clicked.connect(lambda point: self.activate_point(0))
        else:
            series = QBarSeries()
            series.setBarWidth(.95 if spec.kind == 'histogram' else .7)
            for i, source in enumerate(spec.series):
                bars = QBarSet(source.name)
                bars.append([p.value for p in source.points])
                bars.setColor(QColor(DATA_PALETTE[i % len(DATA_PALETTE)]))
                bars.setBorderColor(QColor(COLORS['surface']))
                bars.setSelectedColor(QColor(COLORS['violet']))
                bars.clicked.connect(lambda index, b=bars, s=i: (b.selectBar(index), self.activate_point(index, s)))
                bars.hovered.connect(lambda active, index, src=source: self._hover(
                    f'{src.points[index].label} | {src.name}: {src.points[index].value}', active))
                series.append(bars)
            chart.addSeries(series)
            axis = QBarCategoryAxis()
            axis.append(_axis_labels(points))
            axis.setLabelsAngle(-20 if len(points) > 4 else 0)
            if len(spec.series) > 1:
                chart.legend().setVisible(True)
                chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
                chart.legend().setLabelColor(QColor(COLORS['secondary']))
                font = QFont(); font.setPixelSize(10)
                chart.legend().setFont(font)
        chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis)
        y = QValueAxis()
        maximum = max(p.value for s in spec.series for p in s.points)
        y.setRange(0, max(1, maximum))
        small_counts = maximum <= 5 and all(type(p.value) is int for s in spec.series for p in s.points)
        y.setTickCount(max(1, maximum) + 1 if small_counts else 4)
        if small_counts:
            y.setLabelFormat('%.0f')
        chart.addAxis(y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(y)
        for a in chart.axes():
            font = QFont(); font.setPixelSize(10)
            a.setLabelsFont(font)
            a.setLabelsColor(QColor(COLORS['secondary']))
            a.setLineVisible(False)
            a.setGridLinePen(QPen(QColor(COLORS['border']), .5))
        axis.setGridLineVisible(False)
        return chart
