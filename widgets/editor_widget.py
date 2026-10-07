"""
EditorWidget — master-detail authoring UI for a Tree:
  left:   outline of every step (click to edit it)
  middle: StepEditor form for the selected step
  right:  a live PlayerWidget ("Test") that always reflects the
          in-memory tree, synced back to the outline as you click
          through it so you can see exactly where you are.
"""

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QMessageBox, QFileDialog, QDialog, QDialogButtonBox,
    QFormLayout, QColorDialog, QTabWidget
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, Signal

from engine import Branding, Tree, Issue, SEVERITY_ERROR, is_hex_color
from theme import TEXT_DIM, GOLD, GREEN, RED
from widgets.graph_view import GraphPanel
from widgets.image_picker import ImagePicker
from widgets.step_editor import StepEditor
from widgets.player_widget import PlayerWidget

ROOT_MARK = "★ "
UNREACHABLE_MARK = "⚠ "
ERROR_MARK = "✖ "
SEVERITY_ICON = {"error": "✖", "warning": "⚠"}


class ValidationDialog(QDialog):
    """Lists every issue, errors first. Double-click one to jump to its step."""
    jump_to_step = Signal(str)

    def __init__(self, issues: list[Issue], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Validate")
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        errors = sum(i.is_error for i in issues)
        warnings = len(issues) - errors
        layout.addWidget(QLabel(
            f"{errors} error{'s' if errors != 1 else ''}, {warnings} warning{'s' if warnings != 1 else ''}"
            + (" — errors must be fixed before a client release can be built." if errors else "")
        ))
        self.list = QListWidget()
        for issue in sorted(issues, key=lambda i: not i.is_error):
            item = QListWidgetItem(f"{SEVERITY_ICON[issue.severity]}  {issue.message}")
            item.setData(Qt.UserRole, issue.step_id)
            item.setForeground(Qt.red if issue.is_error else Qt.yellow)
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(self._jump)
        layout.addWidget(self.list, 1)
        layout.addWidget(QLabel("Double-click an item to jump to that step."))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _jump(self, item: QListWidgetItem):
        sid = item.data(Qt.UserRole)
        if sid:
            self.jump_to_step.emit(sid)


class BrandingDialog(QDialog):
    """Edit the client's Player branding: product name, accent colour, logo."""

    def __init__(self, branding: Branding, base_dir_provider, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Client branding")
        self.resize(460, 0)
        form = QFormLayout(self)
        self.name_input = QLineEdit(branding.name)
        self.name_input.setPlaceholderText("Longleaf")
        form.addRow("Name:", self.name_input)

        accent_row = QHBoxLayout()
        self.accent_input = QLineEdit(branding.accent)
        self.accent_input.setPlaceholderText("#RRGGBB — blank for the Yellowhammer gold")
        accent_row.addWidget(self.accent_input, 1)
        pick = QPushButton("Pick…")
        pick.clicked.connect(self._pick_colour)
        accent_row.addWidget(pick)
        form.addRow("Accent colour:", accent_row)

        self.logo_picker = ImagePicker("No logo", base_dir_provider=base_dir_provider)
        self.logo_picker.set_path(branding.logo)
        form.addRow("Logo:", self.logo_picker)

        self.problem_label = QLabel("")
        self.problem_label.setStyleSheet(f"color: {RED};")
        form.addRow(self.problem_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _pick_colour(self):
        colour = QColorDialog.getColor(QColor(self.accent_input.text() or GOLD), self, "Accent colour")
        if colour.isValid():
            self.accent_input.setText(colour.name().upper())

    def _accept(self):
        accent = self.accent_input.text().strip()
        if accent and not is_hex_color(accent):
            self.problem_label.setText("Accent must look like #C9952A (six hex digits), or be blank.")
            return
        self.accept()

    def branding(self) -> Branding:
        return Branding(name=self.name_input.text().strip(), accent=self.accent_input.text().strip(),
                        logo=self.logo_picker.path())


class EditorWidget(QWidget):
    dirty_changed = Signal(bool)

    def __init__(self, tree: Tree | None = None, parent=None):
        super().__init__(parent)
        self.tree = tree or Tree()
        self.current_path: str | None = None
        self._dirty = False
        self._build_ui()
        self._reload_all()

    def base_dir(self) -> str | None:
        """Folder of the saved flow file (where its images live), or None while unsaved."""
        return os.path.dirname(os.path.abspath(self.current_path)) if self.current_path else None

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
        self._refresh_test()   # images now resolve against the new folder
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
        title_row.addWidget(QLabel("Client:"))
        self.client_input = QLineEdit()
        self.client_input.setPlaceholderText("e.g. acme-hvac")
        self.client_input.setMaximumWidth(140)
        self.client_input.textChanged.connect(self._on_meta_changed)
        title_row.addWidget(self.client_input)
        title_row.addWidget(QLabel("Version:"))
        self.version_input = QLineEdit()
        self.version_input.setPlaceholderText("1.0.0")
        self.version_input.setMaximumWidth(70)
        self.version_input.textChanged.connect(self._on_meta_changed)
        title_row.addWidget(self.version_input)
        self.status_label = QLabel("")
        title_row.addWidget(self.status_label)
        branding_btn = QPushButton("Branding…")
        branding_btn.clicked.connect(self._edit_branding)
        title_row.addWidget(branding_btn)
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
        self.step_editor.set_base_dir_provider(self.base_dir)
        self.step_editor.changed.connect(self._on_step_edited)
        self.step_editor.set_as_start_requested.connect(self._set_start_step)
        splitter.addWidget(self.step_editor)

        # --- right pane: live test + graph, as tabs ---
        self.graph = GraphPanel()
        self.graph.step_selected.connect(self.select_step)
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
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(test_panel, "Live Test")
        self.right_tabs.addTab(self.graph, "Graph")
        self.right_tabs.currentChanged.connect(self._on_right_tab_changed)
        splitter.addWidget(self.right_tabs)

        splitter.setSizes([220, 420, 380])
        root.addWidget(splitter, 1)

    # ---------- data <-> UI sync ----------

    def _step_choices(self):
        return [(sid, f"{sid} — {s.question[:30] or '(no question)'}") for sid, s in self.tree.steps.items()]

    def _reload_all(self):
        self.title_input.blockSignals(True)
        self.title_input.setText(self.tree.title)
        self.title_input.blockSignals(False)
        for w, text in ((self.client_input, self.tree.client), (self.version_input, self.tree.version)):
            w.blockSignals(True)
            w.setText(text)
            w.blockSignals(False)
        self._refresh_outline()
        self._refresh_test()
        self.graph.view.fit()

    def _refresh_outline(self, keep_selection: bool = True):
        selected_id = None
        if keep_selection and self.outline_list.currentItem():
            selected_id = self.outline_list.currentItem().data(Qt.UserRole)

        issues = self.tree.check(self.base_dir())
        unreachable = set(self.tree.steps) - self.tree.reachable_ids()
        error_steps = {i.step_id for i in issues if i.is_error and i.step_id}
        self._update_status(issues)
        self.graph.view.set_tree(self.tree, issues)
        self.outline_list.blockSignals(True)
        self.outline_list.clear()
        for sid, step in self.tree.steps.items():
            prefix = ""
            if sid == self.tree.root_id:
                prefix += ROOT_MARK
            if sid in error_steps:
                prefix += ERROR_MARK
            elif sid in unreachable:
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
        self.graph.view.set_selected(sid)

    def _on_step_edited(self):
        self._mark_dirty(True)
        self._refresh_outline()

    def _on_title_changed(self, text):
        self.tree.title = text
        self._mark_dirty(True)

    def _on_meta_changed(self):
        self.tree.client = self.client_input.text().strip()
        self.tree.version = self.version_input.text().strip()
        self._mark_dirty(True)

    def _update_status(self, issues: list[Issue]):
        errors = sum(i.is_error for i in issues)
        warnings = len(issues) - errors
        if not issues:
            self.status_label.setText("✓ Valid")
            self.status_label.setStyleSheet(f"color: {GREEN};")
        else:
            parts = []
            if errors:
                parts.append(f"✖ {errors} error{'s' if errors != 1 else ''}")
            if warnings:
                parts.append(f"⚠ {warnings} warning{'s' if warnings != 1 else ''}")
            self.status_label.setText(" · ".join(parts))
            self.status_label.setStyleSheet(f"color: {RED if errors else GOLD};")

    def select_step(self, step_id: str):
        for i in range(self.outline_list.count()):
            if self.outline_list.item(i).data(Qt.UserRole) == step_id:
                self.outline_list.setCurrentRow(i)
                return

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
        self.player.load_tree(self.tree, base_dir=self.base_dir())
        self.player.set_logo(self.tree.branding.logo)

    def _on_right_tab_changed(self, index):
        if self.right_tabs.widget(index) is self.graph:
            self.graph.view.fit()

    def _on_test_step_changed(self, step_id):
        player = getattr(self, "player", None)   # the Player reports its first step while still being constructed
        path = [(h.step_id, h.option_index) for h in player.engine.history] if player else []
        self.graph.view.set_progress(step_id, path)
        for i in range(self.outline_list.count()):
            item = self.outline_list.item(i)
            base = item.text().replace("▶ ", "", 1)
            item.setText(("▶ " if item.data(Qt.UserRole) == step_id else "") + base)

    def _edit_branding(self):
        dlg = BrandingDialog(self.tree.branding, self.base_dir, self)
        if dlg.exec() == QDialog.Accepted:
            self.tree.branding = dlg.branding()
            self._mark_dirty(True)
            self._refresh_outline()
            self._refresh_test()

    def _run_validate(self):
        issues = self.tree.check(self.base_dir())
        if not issues:
            QMessageBox.information(self, "Validate", "No issues found — this flow looks complete.")
            return
        dlg = ValidationDialog(issues, self)
        dlg.jump_to_step.connect(self.select_step)
        dlg.exec()

    def _mark_dirty(self, value: bool):
        self._dirty = value
        self.dirty_changed.emit(value)
