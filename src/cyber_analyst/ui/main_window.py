"""Janela principal do Cyber Analyst."""

from PySide6.QtWidgets import (
    QButtonGroup,
    QDockWidget,
    QTabWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem
from cyber_analyst.ui.investigation_session import InvestigationSession
from cyber_analyst.ui.workstation import Workspace, ContextInspector
from cyber_analyst.ui.pages import PlaceholderPage
from cyber_analyst.ui.datasets_page import DatasetsPage
from cyber_analyst.ui.analyses_page import AnalysesPage
from cyber_analyst.ui.correlations_page import CorrelationsPage
from cyber_analyst.data.dataset_collection import DatasetCollection
from cyber_analyst.data.session_results import SessionResults
from cyber_analyst.ui.dashboard_page import DashboardPage


class MainWindow(QMainWindow):
    def _collection_changed(self) -> None:
        self.session_results.invalidate(self.collection)
        self.analyses_page.refresh_datasets()
        self.correlations_page.refresh_datasets()
        self.dashboard_page.refresh()

    def _profile_completed(self, dataset, profile) -> None:
        self.session_results.record_analysis(dataset, profile)
        self.dashboard_page.refresh()

    def _correlation_completed(self, result) -> None:
        self.session_results.record_correlation(result)
        self.dashboard_page.refresh()

    def closeEvent(self, event) -> None:
        for page in (self.datasets_page, self.analyses_page, self.correlations_page):
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
        sidebar.setMinimumWidth(120)
        sidebar.setMaximumWidth(180)
        navigation_layout = QVBoxLayout(sidebar)
        navigation_layout.setContentsMargins(8, 12, 8, 8)
        navigation_layout.setSpacing(8)
        brand = QLabel("Cyber Analyst")
        brand.setObjectName("brand")
        navigation_layout.addWidget(brand)
        navigation_layout.addSpacing(8)

        self.navigation = QButtonGroup(self)
        self.navigation.setExclusive(True)
        self.pages = QStackedWidget()
        self.collection = DatasetCollection()
        self.session_results = SessionResults()
        self.dashboard_page = DashboardPage(self.collection, self.session_results)
        self.datasets_page = DatasetsPage(self.collection)
        self.analyses_page = AnalysesPage(self.collection)
        self.correlations_page = CorrelationsPage(self.collection)
        self.datasets_page.collection_changed.connect(self._collection_changed)
        self.analyses_page.profile_completed.connect(self._profile_completed)
        self.correlations_page.result_completed.connect(self._correlation_completed)
        self.investigate_page = QTabWidget()
        self.investigate_page.addTab(self.analyses_page, 'Analyses')
        self.investigate_page.addTab(self.correlations_page, 'Correlations')
        destinations = (
            ('Overview', self.dashboard_page), ('Investigate', self.investigate_page),
            ('Findings', PlaceholderPage('Findings')), ('Data', self.datasets_page),
            ('Relations', PlaceholderPage('Relations')), ('Settings', PlaceholderPage('Settings')))
        for index, (title, page) in enumerate(destinations):
            button = QPushButton(title)
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            navigation_layout.addWidget(button)
            self.pages.addWidget(page)
        navigation_layout.addStretch()
        self.navigation.idClicked.connect(self.pages.setCurrentIndex)
        self.navigation.button(0).setChecked(True)
        self.pages.setCurrentIndex(0)
        layout.addWidget(sidebar)
        self.workspace = Workspace(self.pages)
        layout.addWidget(self.workspace, 1)
        self.context_dock = QDockWidget('Context', self)
        self.context_dock.setObjectName('contextInspectorDock')
        self.context_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.context_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.context_inspector = ContextInspector()
        self.context_dock.setWidget(self.context_inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.context_dock)
        self.workspace.inspector_button.setChecked(True)
        self.workspace.inspector_button.toggled.connect(self.context_dock.setVisible)
        self.context_dock.visibilityChanged.connect(self.workspace.inspector_button.setChecked)
        self.resizeDocks([self.context_dock], [210], Qt.Orientation.Horizontal)

        self.investigation_session = InvestigationSession(self)
        self.investigation_session.changed.connect(self._investigation_changed)
        self.workspace.search.textChanged.connect(self._search_investigation)
        self.workspace.search_results.itemActivated.connect(self._navigate_search_item)
        self.workspace.search_results.itemClicked.connect(self._navigate_search_item)
        self.workspace.search.returnPressed.connect(self._activate_search)

        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #181c1b; color: #dce3df; }
            QWidget#sidebar { background-color: #111513; }
            QLabel { background-color: transparent; }
            QLabel#brand { color: #80b99a; font-size: 14px; font-weight: 600; }
            QLabel#pageTitle { font-size: 26px; font-weight: 600; }
            QPushButton {
                background-color: transparent; text-align: left;
                padding: 6px 8px; border: 1px solid transparent;
                border-radius: 4px; font-size: 14px;
            }
            QPushButton:hover { background-color: #202b25; }
            QPushButton:checked { background-color: #253d30; color: #9bcbae; }
            QPushButton:focus { border-color: #80b99a; }
        """)

    def set_investigation(self, result):
        self.investigation_session.load(result)

    def _investigation_changed(self):
        session=self.investigation_session
        self.workspace.search_results.clear()
        self.workspace.search_results.hide()
        self.workspace.search.setEnabled(session.context is not None)
        self.workspace.search.setPlaceholderText('Search investigation' if session.context else 'Load an investigation to search')
        if session.context is None:
            self.workspace.search.clear()
        self.context_inspector.render(session.context,session.state)

    def _search_investigation(self, query):
        results=self.workspace.search_results
        results.clear()
        results.hide()
        if not query.strip() or self.investigation_session.context is None:
            return
        try:
            matches=self.investigation_session.search(query)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc),5000)
            return
        for match in matches:
            item=QListWidgetItem(f'{match.kind} | {match.label}'+(f' | {match.dataset_name}' if match.dataset_name else ''))
            item.setData(Qt.ItemDataRole.UserRole,match)
            results.addItem(item)
        results.setVisible(bool(len(matches)))
        if len(matches): results.setCurrentRow(0)

    def _activate_search(self):
        item=self.workspace.search_results.currentItem()
        if item is not None: self._navigate_search_item(item)

    def _navigate_search_item(self, item):
        result=item.data(Qt.ItemDataRole.UserRole)
        try:
            self.investigation_session.navigate(result)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc),5000)
            self.workspace.search_results.clear()
            self.workspace.search_results.hide()
