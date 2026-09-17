"""Janela principal do Cyber Analyst."""

from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cyber_analyst.ui.pages import PlaceholderPage


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cyber Analyst")
        self.resize(1100, 720)
        self.setMinimumSize(640, 400)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        navigation_layout = QVBoxLayout(sidebar)
        navigation_layout.setContentsMargins(16, 24, 16, 16)
        navigation_layout.setSpacing(8)
        brand = QLabel("Cyber Analyst")
        brand.setObjectName("brand")
        navigation_layout.addWidget(brand)
        navigation_layout.addSpacing(20)

        self.navigation = QButtonGroup(self)
        self.navigation.setExclusive(True)
        self.pages = QStackedWidget()
        for index, title in enumerate((
            "Dashboard", "Datasets", "Análises", "Correlações",
            "AI Analyst", "Workspace", "Configurações",
        )):
            button = QPushButton(title)
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            navigation_layout.addWidget(button)
            self.pages.addWidget(PlaceholderPage(title))
        navigation_layout.addStretch()
        self.navigation.idClicked.connect(self.pages.setCurrentIndex)
        self.navigation.button(0).setChecked(True)
        self.pages.setCurrentIndex(0)
        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)

        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #181c1b; color: #dce3df; }
            QWidget#sidebar { background-color: #111513; }
            QLabel { background-color: transparent; }
            QLabel#brand { color: #80b99a; font-size: 18px; font-weight: 600; }
            QLabel#pageTitle { font-size: 26px; font-weight: 600; }
            QPushButton {
                background-color: transparent; text-align: left;
                padding: 9px 12px; border: 1px solid transparent;
                border-radius: 4px; font-size: 14px;
            }
            QPushButton:hover { background-color: #202b25; }
            QPushButton:checked { background-color: #253d30; color: #9bcbae; }
            QPushButton:focus { border-color: #80b99a; }
        """)
