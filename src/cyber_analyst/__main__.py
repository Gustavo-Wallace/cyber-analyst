"""Ponto de entrada do Cyber Analyst."""

import sys

from PySide6.QtWidgets import QApplication

from cyber_analyst.ui.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
