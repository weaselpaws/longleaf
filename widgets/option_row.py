"""
OptionRow — one answer option inside the step editor: its label, where
it goes (another step, or an end-of-flow resolution), and the
resolution text if it ends the flow there.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QComboBox, QPushButton, QTextEdit
)
from PySide6.QtCore import Signal

from engine import Option

END_FLOW = "— End flow here (resolution) —"


class OptionRow(QWidget):
    changed = Signal()
    remove_requested = Signal(object)  # passes self

    def __init__(self, option: Option, step_choices: list[tuple[str, str]], parent=None):
        """step_choices: list of (step_id, display_label) for every OTHER step."""
        super().__init__(parent)
        self.option = option
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

        self.resolution_input = QTextEdit()
        self.resolution_input.setPlaceholderText("Resolution shown to the tech when this answer ends the flow…")
        self.resolution_input.setMaximumHeight(56)
        self.resolution_input.textChanged.connect(self._emit_changed)
        root.addWidget(self.resolution_input)

    def _load(self):
        # Block signals while seeding these from the model — otherwise each
        # setter fires its changed-handler mid-load (before the other two
        # fields are populated) and that handler overwrites the model with
        # whatever partial state exists at that instant.
        self.label_input.blockSignals(True)
        self.target_combo.blockSignals(True)
        self.resolution_input.blockSignals(True)
        try:
            self.label_input.setText(self.option.label)
            if self.option.next_id:
                idx = self.target_combo.findData(self.option.next_id)
                self.target_combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                self.target_combo.setCurrentIndex(0)
            self.resolution_input.setPlainText(self.option.resolution or "")
        finally:
            self.label_input.blockSignals(False)
            self.target_combo.blockSignals(False)
            self.resolution_input.blockSignals(False)
        self._sync_resolution_visibility()

    def _sync_resolution_visibility(self):
        self.resolution_input.setVisible(self.target_combo.currentData() is None)

    def _target_changed(self):
        self._sync_resolution_visibility()
        self._emit_changed()

    def _emit_changed(self):
        self.option.label = self.label_input.text()
        self.option.next_id = self.target_combo.currentData()
        self.option.resolution = self.resolution_input.toPlainText() if self.option.next_id is None else None
        self.changed.emit()
