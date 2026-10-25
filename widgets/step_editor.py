"""
StepEditor — the form for editing one Step: its question, an optional
tech-facing note, and its list of answer options.
"""

import re

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea
)
from PySide6.QtCore import Signal

from engine import Step, Option
from widgets.image_picker import ImagePicker
from widgets.option_row import OptionRow
from widgets.shared_content import article_summary, choose_articles, resolution_label


def parse_tags(text: str) -> list[str]:
    """'wifi, No internet;wifi' -> ['wifi', 'No internet']: split on commas, semicolons and newlines,
    trimmed, empties and case-insensitive duplicates dropped, order kept."""
    seen, out = set(), []
    for t in (p.strip() for p in re.split(r"[,;\n]", text)):
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


class StepEditor(QWidget):
    changed = Signal()          # any edit to the current step
    set_as_start_requested = Signal(str)
    new_step_requested = Signal(int)    # index of the answer that should lead to a brand-new step

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step: Step | None = None
        self.all_steps_provider = lambda: []  # callback returning [(id, label), ...]
        self.base_dir_provider = lambda: None  # callback returning the flow file's folder, or None if unsaved
        self.tree_provider = lambda: None      # callback returning the Tree (for shared resolutions / KB articles)
        self.new_resolution = lambda text: None   # callback: create a shared resolution from text, return its id
        self.edit_resolution = lambda rid: None   # callback: open the shared-content dialog on a resolution
        self._build_ui()
        self.set_step(None)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.step_id_label = QLabel("")
        self.step_id_label.setProperty("role", "subheading")
        header.addWidget(self.step_id_label)
        header.addStretch()
        self.start_btn = QPushButton("Set as Start Step")
        self.start_btn.clicked.connect(self._request_start)
        header.addWidget(self.start_btn)
        root.addLayout(header)

        root.addWidget(QLabel("Question:"))
        self.question_input = QPlainTextEdit()
        self.question_input.setMaximumHeight(72)
        self.question_input.textChanged.connect(self._on_question_changed)
        root.addWidget(self.question_input)

        root.addWidget(QLabel("Note (optional, shown as a hint to the tech; web addresses become links):"))
        self.note_input = QPlainTextEdit()
        self.note_input.setMaximumHeight(72)
        self.note_input.textChanged.connect(self._on_note_changed)
        root.addWidget(self.note_input)

        root.addWidget(QLabel("Search tags (optional, comma-separated — words a tech might type to find this step):"))
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText("e.g. wifi, no internet, blue screen")
        self.tags_input.textChanged.connect(self._on_tags_changed)
        root.addWidget(self.tags_input)

        root.addWidget(QLabel("Screenshot (optional):"))
        self.image_picker = ImagePicker("No screenshot", base_dir_provider=lambda: self.base_dir_provider())
        self.image_picker.changed.connect(self._on_image_changed)
        root.addWidget(self.image_picker)

        articles_row = QHBoxLayout()
        articles_row.addWidget(QLabel("KB articles offered here:"))
        self.articles_label = QLabel("None")
        self.articles_label.setWordWrap(True)
        articles_row.addWidget(self.articles_label, 1)
        self.articles_btn = QPushButton("Choose…")
        self.articles_btn.clicked.connect(self._choose_articles)
        articles_row.addWidget(self.articles_btn)
        root.addLayout(articles_row)

        options_header = QHBoxLayout()
        options_header.addWidget(QLabel("Answers:"))
        options_header.addStretch()
        add_option_btn = QPushButton("+ Add Answer")
        add_option_btn.clicked.connect(self._add_option)
        options_header.addWidget(add_option_btn)
        root.addLayout(options_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.options_container = QWidget()
        self.options_layout = QVBoxLayout(self.options_container)
        self.options_layout.setSpacing(10)
        self.options_layout.addStretch()
        scroll.setWidget(self.options_container)
        root.addWidget(scroll, 1)

        self.feedback_box = QPlainTextEdit()
        self.feedback_box.setReadOnly(True)
        self.feedback_box.setMaximumHeight(130)
        self.feedback_box.setVisible(False)
        root.addWidget(self.feedback_box)

    # ---------- wiring from the Editor ----------

    def set_all_steps_provider(self, fn):
        self.all_steps_provider = fn

    def set_feedback_text(self, text: str):
        """What imported sessions say about this step (read-only); hidden when empty."""
        self.feedback_box.setPlainText(text)
        self.feedback_box.setVisible(bool(text))

    def set_base_dir_provider(self, fn):
        self.base_dir_provider = fn

    def set_shared_content_hooks(self, tree_provider, new_resolution, edit_resolution):
        self.tree_provider, self.new_resolution, self.edit_resolution = tree_provider, new_resolution, edit_resolution

    def _show_articles(self):
        tree = self.tree_provider()
        ids = self.step.articles if self.step else []
        self.articles_label.setText(article_summary(tree, ids) if tree else "None")
        self.articles_btn.setEnabled(self.step is not None and tree is not None)

    def _choose_articles(self):
        tree = self.tree_provider()
        if not self.step or tree is None:
            return
        picked = choose_articles(self, tree, self.step.articles)
        if picked is not None and picked != self.step.articles:
            self.step.articles = picked
            self._show_articles()
            self.changed.emit()

    def set_step(self, step: Step | None):
        self.step = step
        enabled = step is not None
        self.question_input.setEnabled(enabled)
        self.note_input.setEnabled(enabled)
        self.tags_input.setEnabled(enabled)
        self.image_picker.setEnabled(enabled)
        self.start_btn.setEnabled(enabled)

        self.question_input.blockSignals(True)
        self.note_input.blockSignals(True)
        tags = step.tags if step else []
        if parse_tags(self.tags_input.text()) != tags:     # don't reformat what is being typed ("wifi," mid-edit)
            self.tags_input.blockSignals(True)
            self.tags_input.setText(", ".join(tags))
            self.tags_input.blockSignals(False)
        self.question_input.setPlainText(step.question if step else "")
        self.note_input.setPlainText(step.note if step else "")
        self.image_picker.set_path(step.image if step else "")
        self.question_input.blockSignals(False)
        self.note_input.blockSignals(False)

        self.step_id_label.setText(f"Editing: {step.id}" if step else "No step selected")
        self._show_articles()
        self._rebuild_options()

    def refresh_target_choices(self):
        """Call after steps are added/removed/renamed elsewhere."""
        self._rebuild_options()

    # ---------- internals ----------

    def _other_step_choices(self):
        return [(sid, label) for sid, label in self.all_steps_provider() if not self.step or sid != self.step.id]

    def _rebuild_options(self):
        while self.options_layout.count() > 1:  # keep the trailing stretch
            item = self.options_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self.step:
            return

        choices = self._other_step_choices()
        tree = self.tree_provider()
        resolutions = [(rid, resolution_label(r.text, rid)) for rid, r in tree.resolutions.items()] if tree else []
        shared_text = (lambda rid: tree.resolutions[rid].text if tree and rid in tree.resolutions else "")
        for option in self.step.options:
            row = OptionRow(option, choices, base_dir_provider=lambda: self.base_dir_provider(),
                            resolution_choices=resolutions, shared_text=shared_text,
                            new_resolution=lambda text: self.new_resolution(text),
                            edit_resolution=lambda rid: self.edit_resolution(rid))
            row.changed.connect(self.changed.emit)
            row.remove_requested.connect(self._remove_option)
            row.new_step_requested.connect(self._new_step_from)
            self.options_layout.insertWidget(self.options_layout.count() - 1, row)

    def _add_option(self):
        if not self.step:
            return
        self.step.options.append(Option(label="New answer"))
        self._rebuild_options()
        self.changed.emit()

    def _new_step_from(self, row: OptionRow):
        if self.step and row.option in self.step.options:
            self.new_step_requested.emit(self.step.options.index(row.option))

    def _remove_option(self, row: OptionRow):
        if not self.step:
            return
        self.step.options.remove(row.option)
        self._rebuild_options()
        self.changed.emit()

    def _on_question_changed(self):
        if self.step:
            self.step.question = self.question_input.toPlainText()
            self.changed.emit()

    def _on_tags_changed(self, text: str):
        if self.step:
            self.step.tags = parse_tags(text)
            self.changed.emit()

    def _on_note_changed(self):
        if self.step:
            self.step.note = self.note_input.toPlainText()
            self.changed.emit()

    def _on_image_changed(self, rel: str):
        if self.step:
            self.step.image = rel
            self.changed.emit()

    def _request_start(self):
        if self.step:
            self.set_as_start_requested.emit(self.step.id)
