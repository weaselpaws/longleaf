"""
EditorWidget — master-detail authoring UI for a Tree:
  left:   outline of every step (click to edit it)
  middle: StepEditor form for the selected step
  right:  a live PlayerWidget ("Test") that always reflects the
          in-memory tree, synced back to the outline as you click
          through it so you can see exactly where you are.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal

from engine import Tree
from theme import TEXT_DIM, GOLD
from widgets.step_editor import StepEditor
from widgets.player_widget import PlayerWidget

ROOT_MARK = "★ "
UNREACHABLE_MARK = "⚠ "


class EditorWidget(QWidget):
    dirty_changed = Signal(bool)

    def __init__(self, tree: Tree | None = None, parent=None):
        super().__init__(parent)
        self.tree = tree or Tree()
        self.current_path: str | None = None
        self._dirty = False
        self._build_ui()
        self._reload_all()

    # ---------- File operations (called by the host window's menu) ----------

    def new_tree(self):
        if not self._confirm_discard():
            return
        self.tree = Tree()
        self.current_path = None
        step = self.tree.add_step("What's the problem?")
        self.tree.root_id = step.id
        self._reload_all()
        self._mark_dirty(False)

    def open_tree(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Flow", "", "YARI Flow (*.json)")
        if not path:
            return
        try:
            self.tree = Tree.load(path)
        except Exception as e:
            QMessageBox.critical(self, "Couldn't open file", str(e))
            return
        self.current_path = path
        self._reload_all()
        self._mark_dirty(False)

    def save_tree(self) -> bool:
        if not self.current_path:
            return self.save_tree_as()
        self.tree.save(self.current_path)
        self._mark_dirty(False)
        return True

    def save_tree_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save Flow As", "flow.json", "YARI Flow (*.json)")
        if not path:
            return False
        self.current_path = path
        self.tree.save(path)
        self._mark_dirty(False)
        return True

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self, "Unsaved changes",
            "Discard unsaved changes to the current flow?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        return reply == QMessageBox.Yes

    # ---------- UI ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Flow title:"))
        self.title_input = QLineEdit()
        self.title_input.textChanged.connect(self._on_title_changed)
        title_row.addWidget(self.title_input, 1)
        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self._run_validate)
        title_row.addWidget(validate_btn)
        root.addLayout(title_row)

        splitter = QSplitter(Qt.Horizontal)

        # --- outline pane ---
        outline_panel = QWidget()
        outline_layout = QVBoxLayout(outline_panel)
        outline_layout.addWidget(QLabel("Steps:"))
        self.outline_list = QListWidget()
        self.outline_list.currentItemChanged.connect(self._on_outline_selection)
        outline_layout.addWidget(self.outline_list, 1)
        outline_btns = QHBoxLayout()
        add_btn = QPushButton("+ Add Step")
        add_btn.clicked.connect(self._add_step)
        outline_btns.addWidget(add_btn)
        del_btn = QPushButton("Delete")
        del_btn.setProperty("role", "danger")
        del_btn.clicked.connect(self._delete_selected_step)
        outline_btns.addWidget(del_btn)
        outline_layout.addLayout(outline_btns)
        splitter.addWidget(outline_panel)

        # --- editor pane ---
        self.step_editor = StepEditor()
        self.step_editor.set_all_steps_provider(self._step_choices)
        self.step_editor.changed.connect(self._on_step_edited)
        self.step_editor.set_as_start_requested.connect(self._set_start_step)
        splitter.addWidget(self.step_editor)

        # --- test pane ---
        test_panel = QWidget()
        test_layout = QVBoxLayout(test_panel)
        test_header = QHBoxLayout()
        test_header.addWidget(QLabel("Live Test:"))
        test_header.addStretch()
        refresh_btn = QPushButton("↻ Refresh Test")
        refresh_btn.clicked.connect(self._refresh_test)
        test_header.addWidget(refresh_btn)
        test_layout.addLayout(test_header)
        self.player = PlayerWidget(self.tree, on_step_changed=self._on_test_step_changed)
        test_layout.addWidget(self.player, 1)
        splitter.addWidget(test_panel)

        splitter.setSizes([220, 420, 380])
        root.addWidget(splitter, 1)

    # ---------- data <-> UI sync ----------

    def _step_choices(self):
        return [(sid, f"{sid} — {s.question[:30] or '(no question)'}") for sid, s in self.tree.steps.items()]

    def _reload_all(self):
        self.title_input.blockSignals(True)
        self.title_input.setText(self.tree.title)
        self.title_input.blockSignals(False)
        self._refresh_outline()
        self._refresh_test()

    def _refresh_outline(self, keep_selection: bool = True):
        selected_id = None
        if keep_selection and self.outline_list.currentItem():
            selected_id = self.outline_list.currentItem().data(Qt.UserRole)

        unreachable = set(self.tree.steps) - self.tree.reachable_ids()
        self.outline_list.blockSignals(True)
        self.outline_list.clear()
        for sid, step in self.tree.steps.items():
            prefix = ""
            if sid == self.tree.root_id:
                prefix += ROOT_MARK
            if sid in unreachable:
                prefix += UNREACHABLE_MARK
            label = f"{prefix}{step.question[:40] or '(no question)'}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, sid)
            if sid in unreachable:
                item.setForeground(Qt.gray)
            self.outline_list.addItem(item)
            if sid == selected_id:
                self.outline_list.setCurrentItem(item)
        if selected_id is None and self.outline_list.count():
            self.outline_list.setCurrentRow(0)
        self.outline_list.blockSignals(False)
        # currentItemChanged doesn't fire while signals were blocked — sync manually
        self._on_outline_selection(self.outline_list.currentItem(), None)

    def _on_outline_selection(self, current: QListWidgetItem | None, _previous):
        sid = current.data(Qt.UserRole) if current else None
        step = self.tree.steps.get(sid) if sid else None
        self.step_editor.set_step(step)

    def _on_step_edited(self):
        self._mark_dirty(True)
        self._refresh_outline()

    def _on_title_changed(self, text):
        self.tree.title = text
        self._mark_dirty(True)

    def _add_step(self):
        step = self.tree.add_step("New question")
        self._mark_dirty(True)
        self._refresh_outline(keep_selection=False)
        for i in range(self.outline_list.count()):
            if self.outline_list.item(i).data(Qt.UserRole) == step.id:
                self.outline_list.setCurrentRow(i)
                break

    def _delete_selected_step(self):
        item = self.outline_list.currentItem()
        if not item:
            return
        sid = item.data(Qt.UserRole)
        reply = QMessageBox.question(
            self, "Delete step", f"Delete '{sid}'? Any answers pointing to it will be unlinked.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self.tree.delete_step(sid)
        self._mark_dirty(True)
        self._refresh_outline(keep_selection=False)

    def _set_start_step(self, step_id):
        self.tree.root_id = step_id
        self._mark_dirty(True)
        self._refresh_outline()

    def _refresh_test(self):
        self.player.load_tree(self.tree)

    def _on_test_step_changed(self, step_id):
        for i in range(self.outline_list.count()):
            item = self.outline_list.item(i)
            base = item.text().replace("▶ ", "", 1)
            item.setText(("▶ " if item.data(Qt.UserRole) == step_id else "") + base)

    def _run_validate(self):
        warnings = self.tree.validate()
        if not warnings:
            QMessageBox.information(self, "Validate", "No issues found — this flow looks complete.")
        else:
            QMessageBox.warning(self, "Validate", "\n".join(f"• {w}" for w in warnings))

    def _mark_dirty(self, value: bool):
        self._dirty = value
        self.dirty_changed.emit(value)
