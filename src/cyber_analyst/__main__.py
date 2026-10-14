"""Ponto de entrada do Cyber Analyst."""

import sys
import logging

from cyber_analyst.app.diagnostics import configure_logging

configure_logging()

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QLibraryInfo

from cyber_analyst.ui.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    logging.getLogger("cyber_analyst").info(
        "Window ready; Qt plugins=%s", QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    exit_code = app.exec()
    logging.getLogger("cyber_analyst").info("Application stopped; exit=%s", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
