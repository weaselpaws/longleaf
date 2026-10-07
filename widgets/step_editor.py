"""
StepEditor — the form for editing one Step: its question, an optional
tech-facing note, and its list of answer options.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea
)
from PySide6.QtCore import Signal

from engine import Step, Option
from widgets.image_picker import ImagePicker
from widgets.option_row import OptionRow


class StepEditor(QWidget):
    changed = Signal()          # any edit to the current step
    set_as_start_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step: Step | None = None
        self.all_steps_provider = lambda: []  # callback returning [(id, label), ...]
        self.base_dir_provider = lambda: None  # callback returning the flow file's folder, or None if unsaved
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

        root.addWidget(QLabel("Screenshot (optional):"))
        self.image_picker = ImagePicker("No screenshot", base_dir_provider=lambda: self.base_dir_provider())
        self.image_picker.changed.connect(self._on_image_changed)
        root.addWidget(self.image_picker)

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

    # ---------- wiring from the Editor ----------

    def set_all_steps_provider(self, fn):
        self.all_steps_provider = fn

    def set_base_dir_provider(self, fn):
        self.base_dir_provider = fn

    def set_step(self, step: Step | None):
        self.step = step
        enabled = step is not None
        self.question_input.setEnabled(enabled)
        self.note_input.setEnabled(enabled)
        self.image_picker.setEnabled(enabled)
        self.start_btn.setEnabled(enabled)

        self.question_input.blockSignals(True)
        self.note_input.blockSignals(True)
        self.question_input.setPlainText(step.question if step else "")
        self.note_input.setPlainText(step.note if step else "")
        self.image_picker.set_path(step.image if step else "")
        self.question_input.blockSignals(False)
        self.note_input.blockSignals(False)

        self.step_id_label.setText(f"Editing: {step.id}" if step else "No step selected")
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
        for option in self.step.options:
            row = OptionRow(option, choices, base_dir_provider=lambda: self.base_dir_provider())
            row.changed.connect(self.changed.emit)
            row.remove_requested.connect(self._remove_option)
            self.options_layout.insertWidget(self.options_layout.count() - 1, row)

    def _add_option(self):
        if not self.step:
            return
        self.step.options.append(Option(label="New answer"))
        self._rebuild_options()
        self.changed.emit()

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
