"""Janela principal do Cyber Analyst."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cyber Analyst")
        self.resize(1100, 720)
        self.setMinimumSize(640, 400)

        label = QLabel("Cyber Analyst")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(label)
        self.setStyleSheet("""
            QMainWindow, QLabel { background-color: #181c1b; }
            QLabel { color: #80b99a; font-size: 22px; }
        """)
