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
from cyber_analyst.ui.findings_page import FindingsPage
from cyber_analyst.ui.investigation_overview import InvestigationOverview
from cyber_analyst.ui.relations_page import RelationsPage
from cyber_analyst.ui.investigation_runner import InvestigationRunner
from cyber_analyst.ui.settings_page import SettingsPage
from cyber_analyst.app.pipeline_factory import create_pipeline
from PySide6.QtWidgets import QApplication


class MainWindow(QMainWindow):
    def _collection_changed(self) -> None:
        self.session_results.invalidate(self.collection)
        self.analyses_page.refresh_datasets()
        self.correlations_page.refresh_datasets()
        self.dashboard_page.refresh()
        self._update_run_controls()

    def _profile_completed(self, dataset, profile) -> None:
        self.session_results.record_analysis(dataset, profile)
        self.dashboard_page.refresh()

    def _correlation_completed(self, result) -> None:
        self.session_results.record_correlation(result)
        self.dashboard_page.refresh()

    def closeEvent(self, event) -> None:
        if self.investigation_runner.running:
            self._close_pending = True
            self.statusBar().showMessage('Waiting for investigation to finish before closing')
            event.ignore()
            return
        for page in (self.datasets_page, self.analyses_page, self.correlations_page):
            page.shutdown()
        self._shutdown_runtime()
        super().closeEvent(event)

    def __init__(self, investigation_pipeline=None) -> None:
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
        self.investigation_session = InvestigationSession(self)
        self.overview_page = InvestigationOverview(self.investigation_session, self.dashboard_page)
        self.findings_page = FindingsPage(self.investigation_session)
        self.relations_page = RelationsPage(self.investigation_session)
        self._owned_pipeline = None
        self.settings_page = SettingsPage(self._apply_runtime_config)
        destinations = (
            ('Overview', self.overview_page), ('Investigate', self.investigate_page),
            ('Findings', self.findings_page), ('Data', self.datasets_page),
            ('Relations', self.relations_page), ('Settings', self.settings_page))
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
        self._close_pending = False
        self.investigation_runner = InvestigationRunner(investigation_pipeline, self)
        self.investigation_runner.changed.connect(self._update_run_controls)
        self.investigation_runner.succeeded.connect(self._investigation_completed)
        self.investigation_runner.failed.connect(self._investigation_failed)
        QApplication.instance().aboutToQuit.connect(self.investigation_runner.shutdown)
        QApplication.instance().aboutToQuit.connect(self._shutdown_runtime)
        self.workspace.run_button.clicked.connect(self._run_investigation)
        self.datasets_page.loading_finished.connect(self._update_run_controls)
        self._update_run_controls()
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

        self.workspace.filters.bind(self.investigation_session)
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

    def _shutdown_runtime(self):
        if self._owned_pipeline is not None:
            self._owned_pipeline.shutdown()

    def _apply_runtime_config(self, config):
        if self.investigation_runner.running or self._close_pending:
            raise ValueError('Cannot replace pipeline during an investigation or shutdown')
        pipeline = create_pipeline(config)
        self._shutdown_runtime()
        self._owned_pipeline = pipeline
        self.investigation_runner.pipeline = pipeline
        self._update_run_controls()

    def _update_run_controls(self):
        runner = self.investigation_runner
        available = runner.pipeline is not None
        self.settings_page.setEnabled(not runner.running and not self._close_pending)
        self.workspace.run_button.setEnabled(available and bool(len(self.collection)) and not runner.running and not self.datasets_page.is_loading and not self._close_pending)
        self.workspace.run_button.setToolTip('No investigation pipeline configured' if not available else 'Run on the currently loaded datasets')
        self.datasets_page.setEnabled(not runner.running)
        if runner.running:
            self.workspace.run_status.setText('Running investigation...')
        elif self._close_pending:
            self.close()

    def _run_investigation(self):
        if self.datasets_page.is_loading or self._close_pending:
            return
        try:
            self.investigation_runner.start(self.collection.values())
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))

    def _investigation_completed(self, result):
        try:
            self.set_investigation(result)
        except Exception as exc:
            self._investigation_failed(exc)
            return
        self.workspace.run_status.setText('Completed')
        self.statusBar().showMessage('Investigation completed')

    def _investigation_failed(self, error):
        self.workspace.run_status.setText('Failed')
        stage = getattr(error, 'stage', 'result')
        self.statusBar().showMessage(f'Investigation failed [{stage}]: {error}')

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
