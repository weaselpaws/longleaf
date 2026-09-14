"""
Longleaf - Player (v1)

The version that ships to field techs: opens a flow file and walks it.
No editing capability at all — just Play, answer, get a report.
"""

import sys
import os

from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PySide6.QtGui import QAction

from engine import Tree
from theme import apply_theme
from widgets.player_widget import PlayerWidget

DEFAULT_FLOW_NAME = "flow.json"


def _bundled_flow_path() -> str:
    """The flow shipped alongside the exe (or this script, in dev)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, DEFAULT_FLOW_NAME)


class PlayerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Longleaf")
        self.resize(720, 640)

        self.player = PlayerWidget(Tree())
        self.setCentralWidget(self.player)

        self._build_menu()
        self._load_default_flow()

    def _build_menu(self):
        menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open Flow…", self)
        open_action.triggered.connect(self._open_flow)
        menu.addAction(open_action)
        restart_action = QAction("&Restart", self)
        restart_action.triggered.connect(self.player.restart)
        menu.addAction(restart_action)

    def _load_default_flow(self):
        path = _bundled_flow_path()
        if os.path.exists(path):
            self._load(path)
        else:
            self._open_flow(required=True)

    def _open_flow(self, required: bool = False):
        path, _ = QFileDialog.getOpenFileName(self, "Open Flow", "", "YARI Flow (*.json)")
        if not path:
            if required:
                QMessageBox.warning(
                    self, "No flow loaded",
                    "No flow file was found or selected. Use File → Open Flow to load one."
                )
            return
        self._load(path)

    def _load(self, path: str):
        try:
            tree = Tree.load(path)
        except Exception as e:
            QMessageBox.critical(self, "Couldn't open flow", str(e))
            return
        self.player.load_tree(tree)
        self.setWindowTitle(f"Longleaf — {tree.title}")


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    window = PlayerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
