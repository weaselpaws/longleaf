"""
OptionRow — one answer option inside the step editor: its label, where
it goes (another step, or an end-of-flow resolution), and the
resolution if it ends the flow there. A resolution is either inline text
(just this answer) or a shared resolution defined once for the whole flow.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QTextEdit
)
from PySide6.QtCore import Signal

from engine import Option
from widgets.image_picker import ImagePicker

_NEW = "\0new-shared-resolution"   # sentinel combo data, never a real id
END_FLOW = "— End flow here (resolution) —"
INLINE_ENDING = "Written here (just this answer)"
NEW_SHARED = "+ New shared resolution from this text…"


class OptionRow(QWidget):
    changed = Signal()
    remove_requested = Signal(object)  # passes self

    def __init__(self, option: Option, step_choices: list[tuple[str, str]],
                 base_dir_provider=lambda: None, resolution_choices=(), shared_text=lambda rid: "",
                 new_resolution=lambda text: None, edit_resolution=lambda rid: None, parent=None):
        """step_choices: list of (step_id, display_label) for every OTHER step.
        resolution_choices: (resolution_id, label) for each shared resolution.
        shared_text(rid) -> its text; new_resolution(text) -> id of a new one (or None);
        edit_resolution(rid) opens the shared-content dialog on it."""
        super().__init__(parent)
        self.option = option
        self.base_dir_provider = base_dir_provider
        self.resolution_choices = list(resolution_choices)
        self.shared_text = shared_text
        self.new_resolution = new_resolution
        self.edit_resolution = edit_resolution
        self._build_ui(step_choices)
        self._load()

    def _build_ui(self, step_choices):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        top = QHBoxLayout()
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Answer label (e.g. Yes)")
        self.label_input.textChanged.connect(self._emit_changed)
        top.addWidget(self.label_input, 2)

        self.target_combo = QComboBox()
        self.target_combo.addItem(END_FLOW, userData=None)
        for step_id, label in step_choices:
            self.target_combo.addItem(label, userData=step_id)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        top.addWidget(self.target_combo, 2)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedWidth(30)
        remove_btn.setProperty("role", "danger")
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        top.addWidget(remove_btn)
        root.addLayout(top)

        # How this answer ends: its own text, or one of the flow's shared resolutions.
        ending_row = QHBoxLayout()
        self.ending_combo = QComboBox()
        self.ending_combo.addItem(INLINE_ENDING, userData=None)
        known = {rid for rid, _ in self.resolution_choices}
        for rid, label in self.resolution_choices:
            self.ending_combo.addItem(f"Shared: {label}", userData=rid)
        if self.option.resolution_id and self.option.resolution_id not in known:
            self.ending_combo.addItem(f"⚠ Missing shared resolution ({self.option.resolution_id})",
                                      userData=self.option.resolution_id)
        self.ending_combo.addItem(NEW_SHARED, userData=_NEW)
        self.ending_combo.currentIndexChanged.connect(self._ending_changed)
        ending_row.addWidget(self.ending_combo, 1)
        self.edit_shared_btn = QPushButton("Edit shared…")
        self.edit_shared_btn.clicked.connect(lambda: self.edit_resolution(self.option.resolution_id))
        ending_row.addWidget(self.edit_shared_btn)
        root.addLayout(ending_row)
        self.shared_preview = QLabel("")
        self.shared_preview.setWordWrap(True)
        root.addWidget(self.shared_preview)

        self.resolution_input = QTextEdit()
        self.resolution_input.setPlaceholderText("Resolution shown to the tech when this answer ends the flow…")
        self.resolution_input.setMaximumHeight(56)
        self.resolution_input.textChanged.connect(self._emit_changed)
        root.addWidget(self.resolution_input)

        self.image_picker = ImagePicker("Screenshot shown with the resolution (optional)",
                                        base_dir_provider=lambda: self.base_dir_provider())
        self.image_picker.changed.connect(self._emit_changed)
        root.addWidget(self.image_picker)

    def _load(self):
        # Block signals while seeding these from the model — otherwise each
        # setter fires its changed-handler mid-load (before the other two
        # fields are populated) and that handler overwrites the model with
        # whatever partial state exists at that instant.
        self.label_input.blockSignals(True)
        self.target_combo.blockSignals(True)
        self.resolution_input.blockSignals(True)
        self.ending_combo.blockSignals(True)
        try:
            self.label_input.setText(self.option.label)
            if self.option.next_id:
                idx = self.target_combo.findData(self.option.next_id)
                self.target_combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                self.target_combo.setCurrentIndex(0)
            self.resolution_input.setPlainText(self.option.resolution or "")
            self.image_picker.set_path(self.option.image)
            idx = self.ending_combo.findData(self.option.resolution_id) if self.option.resolution_id else 0
            self.ending_combo.setCurrentIndex(max(idx, 0))
        finally:
            self.ending_combo.blockSignals(False)
            self.label_input.blockSignals(False)
            self.target_combo.blockSignals(False)
            self.resolution_input.blockSignals(False)
        self._sync_resolution_visibility()

    def _sync_resolution_visibility(self):
        ends_flow = self.target_combo.currentData() is None
        shared = self._shared_id()
        self.ending_combo.setVisible(ends_flow)
        self.edit_shared_btn.setVisible(ends_flow and shared is not None)
        self.shared_preview.setVisible(ends_flow and shared is not None)
        self.resolution_input.setVisible(ends_flow and shared is None)
        self.image_picker.setVisible(ends_flow)
        if shared is not None:
            text = self.shared_text(shared).strip()
            self.shared_preview.setText(text or "(this shared resolution has no text yet)")
            self.image_picker.path_input.setPlaceholderText("Screenshot to use if the shared resolution has none (optional)")
        else:
            self.image_picker.path_input.setPlaceholderText("Screenshot shown with the resolution (optional)")

    def _shared_id(self) -> str | None:
        data = self.ending_combo.currentData()
        return None if data in (None, _NEW) else data

    def _ending_changed(self):
        if self.ending_combo.currentData() == _NEW:
            new_id = self.new_resolution(self.resolution_input.toPlainText())
            if new_id:
                self.option.resolution_id = new_id    # the Editor rebuilds this row with the new choice listed
                self.option.resolution = None
                self.changed.emit()
                return
            self.ending_combo.blockSignals(True)       # cancelled: back to what it was
            idx = self.ending_combo.findData(self.option.resolution_id) if self.option.resolution_id else 0
            self.ending_combo.setCurrentIndex(max(idx, 0))
            self.ending_combo.blockSignals(False)
            return
        self._sync_resolution_visibility()
        self._emit_changed()

    def _target_changed(self):
        self._sync_resolution_visibility()
        self._emit_changed()

    def _emit_changed(self):
        self.option.label = self.label_input.text()
        self.option.next_id = self.target_combo.currentData()
        ends_flow = self.option.next_id is None
        # An answer that goes to another step has no ending at all; leaving a resolution_id behind
        # would make validation warn that it is never shown.
        self.option.resolution_id = self._shared_id() if ends_flow else None
        self.option.resolution = self.resolution_input.toPlainText() if ends_flow and self.option.resolution_id is None else None
        self.option.image = self.image_picker.path() if ends_flow else ""
        self.changed.emit()
