"""Janela principal do Cyber Analyst."""

from PySide6.QtWidgets import (
    QButtonGroup,
    QDockWidget,
    QTabWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QListWidgetItem
from cyber_analyst.ui.investigation_session import InvestigationSession
from cyber_analyst.ui.workstation import Workspace, WorkspacePages, ContextInspector
from cyber_analyst.ui.pages import PlaceholderPage
from cyber_analyst.ui.datasets_page import DatasetsPage
from cyber_analyst.ui.analyses_page import AnalysesPage
from cyber_analyst.ui.correlations_page import CorrelationsPage
from cyber_analyst.data.dataset_collection import DatasetCollection
from cyber_analyst.data.session_results import SessionResults
from cyber_analyst.ui.dashboard_page import DashboardPage
from cyber_analyst.ui.findings_page import FindingsPage
from cyber_analyst.ui.investigation_overview import InvestigationOverview
from cyber_analyst.ui.investigation_analysis_page import InvestigationAnalysisPage
from cyber_analyst.ui.investigation_correlation_page import InvestigationCorrelationPage
from cyber_analyst.ui.relations_page import RelationsPage
from cyber_analyst.ui.investigation_entity_page import InvestigationEntityPage
from cyber_analyst.ui.investigation_runner import InvestigationRunner
from cyber_analyst.ui.settings_page import SettingsPage
from cyber_analyst.ui.analyst_page import AnalystPage
from cyber_analyst.ui.analyst_runner import AnalystRunner
from cyber_analyst.app.pipeline_factory import create_pipeline
from PySide6.QtWidgets import QApplication
from .theme import SPACE, apply_theme, role, label


class MainWindow(QMainWindow):
    def _collection_changed(self) -> None:
        self.datasets_page.refresh_collection()
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
        if self.investigation_runner.running or self.analyst_runner.running:
            self._close_pending = True
            self.analyst_runner.cancel()
            self.analyst_page.set_execution_blocked(True)
            self.statusBar().showMessage('Cancelling Analyst request before closing' if self.analyst_runner.running else
                                         'Waiting for the investigation to finish before closing')
            event.ignore()
            return
        for page in (self.datasets_page, self.analyses_page, self.correlations_page):
            page.shutdown()
        self._shutdown_runtime()
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Quit and self.analyst_runner.running:
            self._quit_pending = True
            self.analyst_runner.cancel()
            return True
        return super().eventFilter(watched, event)

    def __init__(self, investigation_pipeline=None, analyst_pipeline=None) -> None:
        super().__init__()
        self.setWindowTitle("Cyber Analyst")
        self.resize(1100, 720)
        self.setMinimumSize(640, 400)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = sidebar = role(QWidget(), 'sidebar')
        sidebar.setMinimumWidth(128)
        sidebar.setMaximumWidth(168)
        navigation_layout = QVBoxLayout(sidebar)
        navigation_layout.setContentsMargins(SPACE['sm'], SPACE['lg'], SPACE['sm'], SPACE['md'])
        navigation_layout.setSpacing(SPACE['xs'])
        brand = label('Cyber Analyst', 'section_title', 'cyan')
        navigation_layout.addWidget(brand)
        navigation_layout.addWidget(label('LOCAL WORKSTATION', 'caption'))
        navigation_layout.addSpacing(SPACE['lg'])

        self.navigation = QButtonGroup(self)
        self.navigation.setExclusive(True)
        self.pages = WorkspacePages()
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
        self.datasets_page.bind_session(self.investigation_session)
        self.analysis_explorer = InvestigationAnalysisPage(self.investigation_session, self.investigate_page)
        self.correlation_explorer = InvestigationCorrelationPage(self.investigation_session)
        self.investigation_tabs = QTabWidget()
        self.investigation_tabs.addTab(self.analysis_explorer, 'Analyses')
        self.investigation_tabs.addTab(self.correlation_explorer, 'Correlations')
        self.investigation_tabs.setTabVisible(1, False)
        self.overview_page = InvestigationOverview(self.investigation_session, self.dashboard_page)
        self.findings_page = FindingsPage(self.investigation_session)
        self.relations_page = RelationsPage(self.investigation_session)
        self.entity_page = InvestigationEntityPage(self.investigation_session)
        self.relations_tabs = QTabWidget()
        self.relations_tabs.addTab(self.entity_page, 'Entities')
        self.relations_tabs.addTab(self.relations_page, 'Relations')
        self.relations_tabs.setTabVisible(0, False)
        self._owned_pipeline = None
        # A directly destroyed page/window cannot destroy a still-unwinding QThread.
        self.analyst_runner = AnalystRunner(analyst_pipeline, QApplication.instance())
        self.destroyed.connect(self.analyst_runner.dispose)
        self.analyst_page = AnalystPage(self.investigation_session, self.analyst_runner)
        self.analyst_page.reference_navigated.connect(self._open_analyst_reference)
        self.analyst_page.destination_requested.connect(lambda destination: self._show_page(3 if destination == 'Data' else 0))
        self.settings_page = SettingsPage(self._apply_runtime_config)
        destinations = (
            ('Dashboard', self.overview_page), ('Investigate', self.investigation_tabs),
            ('Findings', self.findings_page), ('Data', self.datasets_page),
            ('Relations', self.relations_tabs), ('Settings', self.settings_page),
            ('AI Analyst', self.analyst_page))
        for index, (title, page) in enumerate(destinations):
            button = role(QPushButton(title, sidebar), 'sidebar_button')
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            self.pages.addWidget(page)
            if index in (1, 2, 4):
                button.hide()
        for index in (0, 3, 6):
            navigation_layout.addWidget(self.navigation.button(index))
        navigation_layout.addStretch()
        navigation_layout.addWidget(self.navigation.button(5))
        self.navigation.idClicked.connect(self._show_page)
        self.navigation.button(0).setChecked(True)
        self.pages.setCurrentIndex(0)
        layout.addWidget(sidebar)
        self.workspace = Workspace(self.pages)
        self.pages.currentChanged.connect(self._workspace_page_changed)
        self.overview_page.target_requested.connect(self._open_analyst_reference)
        self.overview_page.detail_requested.connect(self._open_dashboard_detail)
        self.dashboard_page.manual_requested.connect(lambda: self._show_page(1))
        self._close_pending = False
        self._quit_pending = False
        QApplication.instance().installEventFilter(self)
        self.investigation_runner = InvestigationRunner(investigation_pipeline, self)
        self.investigation_runner.changed.connect(self._update_run_controls)
        self.investigation_runner.succeeded.connect(self._investigation_completed)
        self.investigation_runner.failed.connect(self._investigation_failed)
        QApplication.instance().aboutToQuit.connect(self.investigation_runner.shutdown)
        QApplication.instance().aboutToQuit.connect(self.analyst_runner.shutdown)
        QApplication.instance().aboutToQuit.connect(self._shutdown_runtime)
        self.analyst_runner.changed.connect(self._update_run_controls)
        self.workspace.run_button.clicked.connect(self._primary_action)
        self.dashboard_page.primary_requested.connect(self._primary_action)
        self.datasets_page.loading_finished.connect(self._update_run_controls)
        self._update_run_controls()
        layout.addWidget(self.workspace, 1)
        self.context_dock = QDockWidget('Context', self)
        self.context_dock.setObjectName('contextInspectorDock')
        self.context_dock.setMinimumWidth(160)
        self.context_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.context_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.context_inspector = ContextInspector()
        self.context_dock.setWidget(self.context_inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.context_dock)
        self.context_dock.hide()
        self.workspace.inspector_button.toggled.connect(self.context_dock.setVisible)
        self.context_dock.visibilityChanged.connect(self.workspace.inspector_button.setChecked)
        self.resizeDocks([self.context_dock], [210], Qt.Orientation.Horizontal)

        self.workspace.filters.bind(self.investigation_session)
        self.investigation_session.changed.connect(self._investigation_changed)
        self.workspace.search.textChanged.connect(self._search_investigation)
        self.workspace.search_results.itemActivated.connect(self._navigate_search_item)
        self.workspace.search_results.itemClicked.connect(self._navigate_search_item)
        self.workspace.search.returnPressed.connect(self._activate_search)

        # The shared header replaces duplicate page headings; page content/logic stays intact.
        for heading in self.pages.findChildren(QLabel):
            if heading.objectName() == 'pageTitle':
                heading.hide()
        apply_theme(self)

    def _workspace_page_changed(self, index):
        self.workspace.header.set_page(self.navigation.button(index).text())
        self.workspace.set_exploration_visible(self.pages.currentWidget() not in (self.datasets_page, self.settings_page))
        self.workspace.set_search_visible(self.pages.currentWidget() is not self.analyst_page)
        self._refresh_primary_presentation()

    def _refresh_primary_presentation(self):
        # Empty-page actions already provide the same entry point.
        page = self.pages.currentWidget()
        duplicate = (page is self.overview_page and self.investigation_session.context is None
                     or page is self.datasets_page and not len(self.collection))
        self.workspace.run_button.setVisible(not duplicate and page is not self.settings_page)
        self.workspace.header._reflow()

    def _show_page(self, index):
        # Specialist routes keep Dashboard selected without becoming sidebar entries.
        self.navigation.button(0 if index in (1, 2, 4) else index).setChecked(True)
        self.pages.setCurrentIndex(index)

    def _primary_action(self):
        if not len(self.collection):
            self._show_page(3)
        else:
            self._run_investigation()

    def _open_dashboard_detail(self, kind):
        if kind in ('entities', 'relations'):
            self.relations_tabs.setCurrentIndex(0 if kind == 'entities' else 1)
            self._show_page(4)
        elif kind in ('analyses', 'correlations'):
            self.investigation_tabs.setCurrentIndex(0 if kind == 'analyses' else 1)
            self._show_page(1)
        elif kind == 'findings':
            self._show_page(2)

    def set_investigation(self, result):
        self.investigation_session.load(result)

    def _open_analyst_reference(self, reference):
        """Reveal an already authorized/focused object; never change filters."""
        destination = {'entity': 4, 'relation': 4, 'finding': 2,
                       'analysis': 1, 'correlation': 1, 'dataset': 0}[reference.kind]
        if reference.kind in ('entity', 'relation'):
            self.relations_tabs.setCurrentIndex(0 if reference.kind == 'entity' else 1)
        elif reference.kind in ('analysis', 'correlation'):
            self.investigation_tabs.setCurrentIndex(0 if reference.kind == 'analysis' else 1)
        self.navigation.button(destination).click()
        if reference.kind == 'dataset':
            # Overview shows the active investigation's datasets, unlike the legacy
            # Data collection which may have changed independently of this result.
            table = self.overview_page.coverage
            for row in range(table.rowCount()):
                if table.item(row, 0).text() == reference.target_id:
                    table.selectRow(row)
                    table.scrollToItem(table.item(row, 0))
                    break

    def _shutdown_runtime(self):
        if self._owned_pipeline is not None:
            self._owned_pipeline.shutdown()

    def _apply_runtime_config(self, config):
        if self.investigation_runner.running or self.analyst_runner.running or self._close_pending:
            raise ValueError('Cannot replace pipeline during an investigation or shutdown')
        pipeline = create_pipeline(config)
        self._shutdown_runtime()
        self._owned_pipeline = pipeline
        self.investigation_runner.pipeline = pipeline
        self.analyst_runner.pipeline = pipeline
        self._update_run_controls()

    def _update_run_controls(self):
        runner = self.investigation_runner
        available = runner.pipeline is not None
        busy = runner.running or self.analyst_runner.running
        self.settings_page.setEnabled(not busy and not self._close_pending)
        self.analyst_page.set_execution_blocked(runner.running or self._close_pending)
        self.workspace.run_button.setEnabled(available and bool(len(self.collection)) and not busy and not self.datasets_page.is_loading and not self._close_pending)
        self.workspace.run_button.setToolTip('No investigation pipeline configured' if not available else 'Run on the currently loaded datasets')
        has_data = bool(len(self.collection))
        self.workspace.run_button.setText('Analyze again' if has_data and self.investigation_session.context else 'Analyze' if has_data else 'Add datasets')
        if not has_data:
            self.workspace.run_button.setEnabled(not busy and not self.datasets_page.is_loading and not self._close_pending)
            self.workspace.run_button.setToolTip('Choose datasets in Data')
        self.dashboard_page.set_primary_action(self.workspace.run_button.text(), self.workspace.run_button.isEnabled(), self.workspace.run_button.toolTip())
        self._refresh_primary_presentation()
        self.datasets_page.setEnabled(not runner.running)
        if runner.running:
            self.workspace.run_status.setText('Running investigation...')
        elif self._quit_pending and not busy:
            QApplication.instance().quit()
        elif self._close_pending and not busy:
            self.close()

    def _run_investigation(self):
        if self.datasets_page.is_loading or self.analyst_runner.running or self._close_pending:
            return
        try:
            self.investigation_runner.start(self.collection.values())
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))

    def _investigation_completed(self, result):
        first_result = self.investigation_session.context is None
        try:
            self.set_investigation(result)
        except Exception as exc:
            self._investigation_failed(exc)
            return
        if first_result:
            self._show_page(0)
        self.workspace.run_status.setText('Completed')
        self.statusBar().showMessage('Investigation completed')

    def _investigation_failed(self, error):
        self.workspace.run_status.setText('Failed')
        stage = getattr(error, 'stage', 'result')
        self.statusBar().showMessage(f'Investigation failed [{stage}]: {error}')

    def _investigation_changed(self):
        session=self.investigation_session
        self.workspace.header.set_investigation(session.context)
        if self.pages.currentIndex() == 0:
            self.workspace.header.description.setText('Explore your data, review alerts and ask AI Analyst.'
                if session.context else 'Choose one or more datasets to start an investigation.')
        self.workspace.refresh_exploration(session)
        self._update_run_controls()
        self.investigation_tabs.setTabVisible(1, session.context is not None)
        self.relations_tabs.setTabVisible(0, session.context is not None)
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
        results.setVisible(bool(len(matches)) and not self.workspace.search.isHidden())
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
