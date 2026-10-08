"""Small native workstation theme: tokens, typography roles and shared surfaces."""
from types import MappingProxyType
from hashlib import sha256
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout, QTableWidget
from PySide6.QtCore import Qt


COLORS = MappingProxyType(dict(
    background='#0b101b', sidebar='#101725', canvas='#101827', surface='#162131',
    elevated='#1d2b3e', hover='#23354a', selected='#183c4b', text='#e6edf6',
    secondary='#aab9cd', muted='#7f91aa', border='#2a3a50', cyan='#54ccd7', cyan_hover='#79dce4',
    violet='#a995ee', tertiary='#d995bb', success='#78c7b3', warning='#dfba7d', danger='#dc8b9b',
    blue='#79a9df', purple='#b08bd1', magenta='#cf8eb8', teal='#72bbb0', amber='#d9b77c',
))
DATA_PALETTE = tuple(COLORS[name] for name in ('cyan', 'blue', 'violet', 'purple', 'magenta', 'teal', 'amber'))
ATTENTION_COLORS = MappingProxyType({
    'informational': COLORS['blue'], 'low': COLORS['teal'],
    'medium': COLORS['violet'], 'high': COLORS['magenta'],
})
IDENTIFIER_COLORS = MappingProxyType({
    'username': COLORS['cyan'], 'email': COLORS['blue'], 'ip_address': COLORS['violet'],
    'hostname': COLORS['teal'], 'cve': COLORS['magenta'],
})


def data_color(category):
    """Stable across refreshes, filters and Python processes."""
    return IDENTIFIER_COLORS.get(category) or DATA_PALETTE[
        int.from_bytes(sha256(category.encode('utf-8')).digest()[:4], 'big') % len(DATA_PALETTE)]


def data_colors(categories):
    """Avoid collisions in a small composition while retaining semantic colors.
    Larger charts cycle the finite palette; labels/values remain authoritative.
    """
    assigned = {}
    for category in sorted(set(categories), key=lambda k: (k not in IDENTIFIER_COLORS, k)):
        preferred = data_color(category)
        available = [color for color in DATA_PALETTE if color not in assigned.values()]
        assigned[category] = preferred if preferred in available or not available else available[0]
    return MappingProxyType(assigned)
SPACE = MappingProxyType(dict(xs=4, sm=8, md=12, lg=16, xl=24, xxl=32))
RADIUS = MappingProxyType(dict(sm=4, md=6, lg=8))
TYPE = MappingProxyType(dict(page_title=(23, 600), section_title=(14, 600),
                             card_value=(26, 600), body=(13, 400), caption=(11, 400), table=(12, 600)))


def role(widget, name, tone=None):
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setProperty('role', name)
    if tone is not None:
        widget.setProperty('tone', tone)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
    return widget


def label(text, name='body', tone=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return role(widget, name, tone)


def panel(title, description=''):
    widget = role(QFrame(), 'panel')
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(SPACE['lg'], SPACE['md'], SPACE['lg'], SPACE['md'])
    layout.setSpacing(SPACE['sm'])
    layout.addWidget(label(title, 'section_title'))
    if description:
        layout.addWidget(label(description, 'caption'))
    return widget, layout


def table_style(table):
    table.setShowGrid(False)
    table.verticalHeader().setDefaultSectionSize(30)
    table.horizontalHeader().setMinimumSectionSize(40)


def stylesheet():
    c, s, r = COLORS, SPACE, RADIUS
    typography = '\n'.join(f'QLabel[role="{name}"] {{ font-size: {size}px; font-weight: {weight}; }}'
                           for name, (size, weight) in TYPE.items())
    tones = '\n'.join(f'QLabel[tone="{tone}"] {{ color: {c[tone]}; }}'
                      for tone in ('cyan', 'violet', 'tertiary', 'success', 'warning', 'danger', 'muted'))
    return f'''
        QWidget {{ color: {c['text']}; font-size: {TYPE['body'][0]}px; background: transparent; }}
        QMainWindow {{ background: {c['background']}; }}
        QWidget[role="sidebar"] {{ background: {c['sidebar']}; }}
        QWidget[role="canvas"] {{ background: {c['canvas']}; }}
        QWidget[role="toolbar"], QWidget[role="inspector"] {{ background: {c['sidebar']}; }}
        QWidget[role="panel"], QWidget[role="metric"] {{ background: {c['surface']}; border-radius: {r['md']}px; }}
        QLabel {{ background: transparent; border: none; }}
        QLabel[role="caption"] {{ color: {c['muted']}; }}
        QLabel[role="card_value"] {{ color: {c['cyan']}; }}
        QLabel#pageTitle {{ font-size: {TYPE['page_title'][0]}px; font-weight: 600; }}
        QLabel[role="badge"] {{ background: {c['elevated']}; color: {c['secondary']};
                               padding: {s['xs']}px {s['sm']}px; border-radius: {r['sm']}px; font-size: 11px; }}
        {typography}
        {tones}
        QPushButton, QToolButton {{ background: {c['elevated']}; border: 1px solid transparent;
            border-radius: {r['sm']}px; padding: 5px {s['sm']}px; text-align: left; }}
        QPushButton:hover, QToolButton:hover {{ background: {c['hover']}; }}
        QPushButton:checked, QToolButton:checked {{ background: {c['selected']}; color: {c['cyan']}; }}
        QPushButton:focus, QToolButton:focus {{ border-color: {c['cyan']}; }}
        QPushButton:disabled, QToolButton:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
        QPushButton[role="primary"] {{ background: {c['cyan']}; color: {c['background']}; font-weight: 600; }}
        QPushButton[role="primary"]:hover {{ background: {c['cyan_hover']}; }}
        QPushButton[role="primary"]:disabled {{ background: {c['elevated']}; color: {c['muted']}; }}
        QPushButton[role="secondary"] {{ border-color: {c['border']}; }}
        QPushButton[role="sidebar_button"] {{ background: transparent; padding: 7px {s['md']}px; color: {c['secondary']}; }}
        QPushButton[role="sidebar_button"]:hover {{ background: {c['elevated']}; color: {c['text']}; }}
        QPushButton[role="sidebar_button"]:checked {{ background: {c['selected']}; color: {c['cyan']}; border-left: 2px solid {c['cyan']}; }}
        QPushButton[role="highlight"] {{ background: {c['elevated']}; padding: {s['sm']}px; }}
        QPushButton[role="highlight"]:hover {{ background: {c['hover']}; border-color: {c['border']}; }}
        QToolButton[filterActive="true"] {{ background: {c['selected']}; color: {c['cyan']}; border-color: {c['cyan']}; }}
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']};
            border-radius: {r['sm']}px; padding: 5px; selection-background-color: {c['selected']}; }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {c['cyan']}; }}
        QLineEdit:disabled, QComboBox:disabled {{ color: {c['muted']}; }}
        QPlainTextEdit[role="inspector_details"] {{ background: {c['sidebar']}; color: {c['secondary']}; border: none; padding: 0; }}
        QComboBox::drop-down {{ width: 20px; border: none; }}
        QTableView, QListView {{ background: {c['surface']}; border: none; border-radius: {r['sm']}px;
                              gridline-color: {c['border']}; selection-background-color: {c['selected']}; }}
        QTableView::item, QListView::item {{ padding: 4px; border: none; }}
        QTableView::item:selected, QListView::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
        QTableView::item:hover, QListView::item:hover {{ background: {c['hover']}; }}
        QHeaderView::section {{ background: {c['elevated']}; color: {c['secondary']}; padding: 6px;
                              border: none; border-bottom: 1px solid {c['border']}; font-size: {TYPE['table'][0]}px; font-weight: {TYPE['table'][1]}; }}
        QTableCornerButton::section {{ background: {c['elevated']}; border: none; }}
        QTabWidget::pane {{ border: none; }}
        QTabBar::tab {{ background: transparent; color: {c['secondary']}; padding: 7px {s['md']}px; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ background: {c['elevated']}; color: {c['cyan']}; border-bottom-color: {c['cyan']}; }}
        QTabBar::tab:hover {{ background: {c['hover']}; }}
        QMenu {{ background: {c['elevated']}; border: 1px solid {c['border']}; padding: 4px; }}
        QMenu::item {{ padding: 6px 20px; }}
        QMenu::item:selected {{ background: {c['selected']}; color: {c['cyan']}; }}
        QMenu::separator {{ background: {c['border']}; height: 1px; margin: 4px; }}
        QProgressBar {{ background: {c['elevated']}; border: none; border-radius: 3px; text-align: center; }}
        QProgressBar::chunk {{ background: {c['cyan']}; border-radius: 3px; }}
        QProgressBar[tone="violet"]::chunk {{ background: {c['violet']}; }}
        QProgressBar[tone="tertiary"]::chunk {{ background: {c['tertiary']}; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 24px; border-radius: 4px; }}
        QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
        QScrollBar::handle:horizontal {{ background: {c['border']}; min-width: 24px; border-radius: 4px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        QDockWidget {{ color: {c['secondary']}; font-size: 12px; }}
        QDockWidget::title {{ background: {c['sidebar']}; padding: 7px; }}
        QStatusBar {{ background: {c['background']}; color: {c['muted']}; }}
        QToolTip {{ background: {c['elevated']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
    '''


def apply_theme(window):
    palette = window.palette()
    for target, color in ((QPalette.ColorRole.Window, 'background'), (QPalette.ColorRole.WindowText, 'text'),
                          (QPalette.ColorRole.Base, 'surface'), (QPalette.ColorRole.Text, 'text'),
                          (QPalette.ColorRole.Button, 'elevated'), (QPalette.ColorRole.ButtonText, 'text'),
                          (QPalette.ColorRole.Highlight, 'selected'), (QPalette.ColorRole.HighlightedText, 'text')):
        palette.setColor(target, QColor(COLORS[color]))
    window.setPalette(palette)
    window.setStyleSheet(stylesheet())
    for table in window.findChildren(QTableWidget):
        table_style(table)
