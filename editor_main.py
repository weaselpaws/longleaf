"""
YARI Troubleshoot - Editor (v1)

The authoring app: build and edit a flow, with a live Test pane wired
to the same engine the shipped Player uses, so what you test here is
exactly what a tech will see.
"""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtGui import QAction, QKeySequence

from engine import Tree
from theme import apply_theme
from widgets.editor_widget import EditorWidget


class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1280, 780)

        self.editor = EditorWidget(Tree())
        self.editor.new_tree()  # start with one blank step rather than nothing
        self.editor.dirty_changed.connect(self._update_title)
        self.setCentralWidget(self.editor)

        self._build_menu()
        self._update_title(False)

    def _build_menu(self):
        menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New Flow", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.editor.new_tree)
        menu.addAction(new_action)

        open_action = QAction("&Open Flow…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.editor.open_tree)
        menu.addAction(open_action)

        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.editor.save_tree)
        menu.addAction(save_action)

        save_as_action = QAction("Save &As…", self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self.editor.save_tree_as)
        menu.addAction(save_as_action)

        menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

    def _update_title(self, dirty: bool):
        name = self.editor.current_path or "Untitled Flow"
        star = " *" if dirty else ""
        self.setWindowTitle(f"YARI Troubleshoot Editor — {name}{star}")

    def closeEvent(self, event):
        if self.editor._dirty:
            reply = QMessageBox.question(
                self, "Unsaved changes",
                "Save changes before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save and not self.editor.save_tree():
                event.ignore()
                return
        event.accept()


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    window = EditorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
