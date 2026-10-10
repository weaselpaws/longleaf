"""
Longleaf - Editor (v1)

The authoring app: build and edit a flow, with a live Test pane wired
to the same engine the shipped Player uses, so what you test here is
exactly what a tech will see.
"""

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QWidget
from PySide6.QtCore import QEvent, QStandardPaths, Qt
from PySide6.QtGui import QAction, QKeySequence

from autosave import AutosaveStore
from engine import Tree
from theme import apply_theme
from widgets.editor_widget import EditorWidget


DATA_DIR_ENV = "LONGLEAF_DATA_DIR"   # same override the Player honours (portable installs, tests)


def default_autosave_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    base = Path(override) if override else Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    return base / "editor-autosave"


class EditorWindow(QMainWindow):
    def __init__(self, autosave_dir: Path | None = None):
        super().__init__()
        self.resize(1280, 780)

        self.editor = EditorWidget(Tree())
        self.editor.new_tree()  # start with one blank step rather than nothing
        self.autosave = AutosaveStore(autosave_dir or default_autosave_dir())
        self.editor.set_autosave_store(self.autosave)
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

        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = QAction("&Undo", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.editor.undo)
        edit_menu.addAction(self.undo_action)
        self.redo_action = QAction("&Redo", self)
        redo_keys = QKeySequence.keyBindings(QKeySequence.Redo)
        if QKeySequence("Ctrl+Y") not in redo_keys:      # Windows has it; Linux/Mac get it too
            redo_keys.append(QKeySequence("Ctrl+Y"))
        self.redo_action.setShortcuts(redo_keys)
        self.redo_action.triggered.connect(self.editor.redo)
        edit_menu.addAction(self.redo_action)
        self.editor.history_changed.connect(self._update_history_actions)
        self._update_history_actions(False, False)
        # Text boxes claim Ctrl+Z for their own per-field undo, which would hide the
        # flow-level history (add/delete step, answers, branding) whenever the cursor
        # sits in one. Keep a single history: let these keys reach the Edit menu.
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ShortcutOverride and isinstance(obj, QWidget) and self.isAncestorOf(obj):
            ctrl_y = event.key() == Qt.Key_Y and event.modifiers() == Qt.ControlModifier
            if event.matches(QKeySequence.Undo) or event.matches(QKeySequence.Redo) or ctrl_y:
                event.ignore()
                return True      # the text box never sees it, so the shortcut fires
        return super().eventFilter(obj, event)

    def _update_history_actions(self, can_undo: bool, can_redo: bool):
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)

    def offer_recovery(self) -> bool:
        """At startup: if an earlier session died with unsaved work, offer it back.
        Returns True if something was recovered."""
        pending = self.autosave.pending()
        for n, rec in enumerate(pending):
            others = len(pending) - n - 1
            box = QMessageBox(self)
            box.setWindowTitle("Recover unsaved work")
            box.setText(f"Longleaf closed unexpectedly with unsaved changes to:\n\n  {rec.label}\n\nRecover them?")
            if others:
                box.setInformativeText(f"{others} more recovery cop{'ies' if others != 1 else 'y'} will be offered next.")
            recover = box.addButton("Recover", QMessageBox.AcceptRole)
            discard = box.addButton("Discard", QMessageBox.DestructiveRole)
            box.addButton("Ask me later", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is recover:
                if self.editor.recover(rec):
                    return True
            elif box.clickedButton() is discard:
                self.autosave.discard_slot(rec.slot)
            else:
                break
        return False

    def _update_title(self, dirty: bool):
        name = self.editor.current_path or "Untitled Flow"
        star = " *" if dirty else ""
        self.setWindowTitle(f"Longleaf Editor — {name}{star}")

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
        self.editor.discard_autosave()    # saved or deliberately discarded: nothing to recover
        QApplication.instance().removeEventFilter(self)
        event.accept()


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    window = EditorWindow()
    window.show()
    window.offer_recovery()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
