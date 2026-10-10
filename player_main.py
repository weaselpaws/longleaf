"""
Longleaf - Player (v1)

The version that ships to field techs: opens a flow file and walks it.
No editing capability at all — just Play, answer, get a report.
"""

import sys
import os
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QAction

from engine import Tree
from feedback import SessionStore, write_bundle
from theme import apply_theme
from widgets.player_widget import PlayerWidget

DEFAULT_FLOW_NAME = "flow.json"
DATA_DIR_ENV = "LONGLEAF_DATA_DIR"   # override where finished sessions are kept (portable installs, tests)


def _data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    return Path(override) if override else Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))


def _store_for(tree: Tree) -> SessionStore:
    """Finished sessions are kept per client, so opening another client's flow never mixes them."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", tree.client).strip("-") or "default"
    return SessionStore(_data_dir() / "sessions" / slug)


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
        self.store: SessionStore | None = None

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
        menu.addSeparator()
        export_action = QAction("&Export Feedback…", self)
        export_action.triggered.connect(self._export_feedback)
        menu.addAction(export_action)
        clear_action = QAction("&Clear Saved Sessions…", self)
        clear_action.triggered.connect(self._clear_sessions)
        menu.addAction(clear_action)

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
        self.player.flush()                       # finish saving the old flow's session before switching stores
        self.store = _store_for(tree)
        self.player.session_store = self.store
        self.player.load_tree(tree, base_dir=os.path.dirname(os.path.abspath(path)))
        brand = tree.branding
        apply_theme(QApplication.instance(), brand.accent)   # empty accent -> stock gold
        self.player.set_logo(brand.logo)
        self.setWindowTitle(f"{brand.name or 'Longleaf'} — {tree.title}")

    def _export_feedback(self):
        self.player.flush()
        records = self.store.load_all() if self.store else []
        if not records:
            QMessageBox.information(self, "Export Feedback", "No finished sessions have been saved yet.")
            return
        tree = self.player.engine.tree
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", tree.client).strip("-")
        default = f"longleaf_feedback_{slug + '_' if slug else ''}{datetime.now():%Y%m%d}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export Feedback", default, "Longleaf feedback (*.json)")
        if not path:
            return
        try:
            n = write_bundle(path, records, tree)
        except OSError as e:
            QMessageBox.critical(self, "Couldn't save feedback", str(e))
            return
        QMessageBox.information(
            self, "Export Feedback",
            f"Saved {n} session{'s' if n != 1 else ''} to:\n{path}\n\n"
            f"Send this file to whoever maintains this flow. It includes the tickets, notes and "
            f"comments entered on those sessions.")

    def _clear_sessions(self):
        n = self.store.count() if self.store else 0
        if not n:
            QMessageBox.information(self, "Clear Saved Sessions", "There are no saved sessions.")
            return
        reply = QMessageBox.question(
            self, "Clear Saved Sessions",
            f"Delete {n} saved session{'s' if n != 1 else ''} from this computer? "
            f"Export them first if they haven't been sent yet.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.store.clear()

    def closeEvent(self, event):
        self.player.flush()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("Yellowhammer")
    app.setApplicationName("Longleaf")
    apply_theme(app)
    window = PlayerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
