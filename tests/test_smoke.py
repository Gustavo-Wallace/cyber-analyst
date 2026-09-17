import os
import subprocess
import sys


def test_module_entry_point():
    script = """
import runpy
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication([])
QTimer.singleShot(0, lambda: app.exit(7))
runpy.run_module("cyber_analyst", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 7, result.stderr


def test_main_window(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from cyber_analyst.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert app.platformName() == "offscreen"
        assert window.windowTitle() == "Cyber Analyst"
        assert window.centralWidget() is not None
        assert window.minimumWidth() == 640
        assert window.minimumHeight() == 400
    finally:
        window.close()
