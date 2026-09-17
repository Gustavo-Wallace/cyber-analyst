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
from cyber_analyst.ui.datasets_page import DatasetsPage
from cyber_analyst.ui.analyses_page import AnalysesPage
from cyber_analyst.data.dataset_collection import DatasetCollection


class MainWindow(QMainWindow):
    def closeEvent(self, event) -> None:
        for index in range(self.pages.count()):
            page = self.pages.widget(index)
            if isinstance(page, (DatasetsPage, AnalysesPage)):
                page.shutdown()
        super().closeEvent(event)

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
        self.collection = DatasetCollection()
        self.datasets_page = DatasetsPage(self.collection)
        self.analyses_page = AnalysesPage(self.collection)
        self.datasets_page.collection_changed.connect(self.analyses_page.refresh_datasets)
        for index, title in enumerate((
            "Dashboard", "Datasets", "Análises", "Correlações",
            "AI Analyst", "Workspace", "Configurações",
        )):
            button = QPushButton(title)
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            navigation_layout.addWidget(button)
            page = (self.datasets_page if title == "Datasets" else
                    self.analyses_page if title == "Análises" else PlaceholderPage(title))
            self.pages.addWidget(page)
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
