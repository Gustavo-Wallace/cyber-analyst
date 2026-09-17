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
    from PySide6.QtWidgets import QLabel
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from cyber_analyst.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert app.platformName() == "offscreen"
        assert window.windowTitle() == "Cyber Analyst"
        assert window.centralWidget() is not None
        assert window.minimumWidth() == 640
        assert window.minimumHeight() == 400
        titles = [
            "Dashboard", "Datasets", "Análises", "Correlações",
            "AI Analyst", "Workspace", "Configurações",
        ]
        buttons = window.navigation.buttons()
        assert [button.text() for button in buttons] == titles
        assert window.pages.count() == 7
        assert window.pages.currentIndex() == 0
        assert buttons[0].isChecked()
        window.show()
        app.processEvents()
        for index in (1, 2, 3, 4, 5, 6, 0):
            QTest.mouseClick(buttons[index], Qt.MouseButton.LeftButton)
            assert window.pages.currentIndex() == index
            heading = window.pages.currentWidget().findChild(QLabel, "pageTitle")
            assert heading.text() == titles[index]
            assert [button.isChecked() for button in buttons] == [
                i == index for i in range(7)
            ]
        for width, height in ((640, 400), (1400, 900)):
            window.resize(width, height)
            app.processEvents()
            assert window.pages.width() > 0
            for button in buttons:
                assert button.parentWidget().rect().contains(button.geometry())
    finally:
        window.close()
