"""
PlayerWidget — walks a live TroubleshootEngine: shows the current
question, animates in the answer buttons, and ends on a resolution
card with a copyable report. Used standalone by the Player app and
embedded (as the "Test" pane) by the Editor.
"""

import os
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsOpacityEffect, QFrame, QTextEdit, QFileDialog, QApplication,
    QSizePolicy, QLineEdit, QPlainTextEdit, QMessageBox
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QPixmap

from engine import TroubleshootEngine, Tree, OUTCOME_RESOLVED, rich_html
from theme import TEXT_DIM, GREEN, RED
from widgets.answer_button import AnswerButton

# (file-dialog filter, extension) pairs; extension doubles as the SessionRecord.render() format.
EXPORT_FORMATS = [
    ("Text (*.txt)", "txt"),
    ("Markdown (*.md)", "md"),
    ("HTML (*.html)", "html"),
    ("JSON session record (*.json)", "json"),
]


MAX_IMAGE_HEIGHT = 240


def _load_image(base_dir: str | None, rel: str) -> QPixmap | None:
    """The picture at `rel` (relative to the flow's folder), or None if it
    isn't there or can't be read — a missing screenshot must never break a flow."""
    if not rel or base_dir is None:
        return None
    pix = QPixmap(os.path.join(base_dir, rel))
    return None if pix.isNull() else pix


SAVE_DELAY_MS = 600   # typing in notes/comment saves once the tech pauses, not per keystroke


class PlayerWidget(QWidget):
    def __init__(self, tree: Tree | None = None, on_step_changed=None, parent=None, session_store=None):
        """
        on_step_changed: optional callback(step_id | None) fired whenever the
        engine moves — lets an embedding Editor highlight the live node.
        session_store: optional feedback.SessionStore. When set, the result
        screen asks "Did this solve it?" and every finished session is kept
        in the store. The Editor's Test pane leaves it unset, so test runs
        are never recorded.
        """
        super().__init__(parent)
        self.on_step_changed = on_step_changed
        self.session_store = session_store
        self._saved_session_id: str | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_now)
        self.engine = TroubleshootEngine(tree or Tree())
        self.base_dir: str | None = None   # folder the flow's image paths are relative to
        self._build_ui()
        self._render()

    # ---------- public API (Editor uses these) ----------

    def load_tree(self, tree: Tree, base_dir: str | None = None):
        self.flush()
        self.base_dir = base_dir
        self.engine = TroubleshootEngine(tree)
        self._reset_report_inputs()
        self._render()

    def restart(self):
        self.flush()
        self.engine.reset()
        self._reset_report_inputs()
        self._render()

    def _reset_report_inputs(self):
        """New session: clear ticket and notes, but keep the tech's name —
        they're the same person working through the next ticket."""
        for w in (self.ticket_input, self.notes_input, self.feedback_comment):
            w.blockSignals(True)
            w.clear()
            w.blockSignals(False)
        for b in (self.yes_btn, self.no_btn):
            b.setChecked(False)
        self.engine.operator = self.operator_input.text()

    def flush(self):
        """Save a pending finished session now (before the engine is replaced or the app closes)."""
        if self._save_timer.isActive():
            self._save_now()

    # ---------- UI ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        self.logo_label = QLabel("")
        self.logo_label.setVisible(False)
        header.addWidget(self.logo_label)
        self.breadcrumb = QLabel("")
        self.breadcrumb.setProperty("role", "subheading")
        header.addWidget(self.breadcrumb, 1)
        root.addLayout(header)

        self.card = QFrame()
        self.card.setObjectName("card")
        self._opacity_effect = QGraphicsOpacityEffect(self.card)
        self.card.setGraphicsEffect(self._opacity_effect)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(10)
        card_layout.addStretch(1)

        self.question_label = QLabel("")
        self.question_label.setProperty("role", "heading")
        self.question_label.setWordWrap(True)
        self._make_rich(self.question_label)
        card_layout.addWidget(self.question_label)

        self.note_label = QLabel("")
        self.note_label.setProperty("role", "note")
        self.note_label.setWordWrap(True)
        self.note_label.setVisible(False)
        self._make_rich(self.note_label)
        card_layout.addWidget(self.note_label)

        self.image_label = QLabel("")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setVisible(False)
        card_layout.addWidget(self.image_label)

        self.answers_layout = QVBoxLayout()
        self.answers_layout.setSpacing(8)
        card_layout.addLayout(self.answers_layout)

        # resolution state (hidden until finished)
        self.resolution_label = QLabel("")
        self.resolution_label.setWordWrap(True)
        self.resolution_label.setStyleSheet(f"color: {GREEN}; font-size: 16px; font-weight: 600;")
        self.resolution_label.setVisible(False)
        self._make_rich(self.resolution_label)
        card_layout.addWidget(self.resolution_label)

        # "Did this solve it?" (shown on a real ending, only when sessions are being kept)
        self.feedback_widget = QWidget()
        fb = QHBoxLayout(self.feedback_widget)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.addWidget(QLabel("Did this solve it?"))
        self.yes_btn = QPushButton("Yes")
        self.no_btn = QPushButton("No")
        for b in (self.yes_btn, self.no_btn):
            b.setCheckable(True)
            b.setFixedWidth(64)
            fb.addWidget(b)
        self.yes_btn.clicked.connect(lambda: self._rate(self.yes_btn, self.no_btn))
        self.no_btn.clicked.connect(lambda: self._rate(self.no_btn, self.yes_btn))
        self.feedback_comment = QLineEdit()
        self.feedback_comment.setPlaceholderText("Comment (optional)")
        self.feedback_comment.textChanged.connect(self._on_feedback_changed)
        fb.addWidget(self.feedback_comment, 1)
        self.feedback_widget.setVisible(False)
        card_layout.addWidget(self.feedback_widget)

        # report details (hidden until finished) — flow into the report below
        self.details_widget = QWidget()
        details = QVBoxLayout(self.details_widget)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(6)
        ids_row = QHBoxLayout()
        self.ticket_input = QLineEdit()
        self.ticket_input.setPlaceholderText("Ticket / reference (optional)")
        self.ticket_input.textChanged.connect(self._on_details_changed)
        ids_row.addWidget(self.ticket_input)
        self.operator_input = QLineEdit()
        self.operator_input.setPlaceholderText("Your name (optional)")
        self.operator_input.textChanged.connect(self._on_details_changed)
        ids_row.addWidget(self.operator_input)
        details.addLayout(ids_row)
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Notes to include in the report (optional)")
        self.notes_input.setMaximumHeight(60)
        self.notes_input.textChanged.connect(self._on_details_changed)
        details.addWidget(self.notes_input)
        self.details_widget.setVisible(False)
        card_layout.addWidget(self.details_widget)

        self.report_box = QTextEdit()
        self.report_box.setReadOnly(True)
        self.report_box.setFocusPolicy(Qt.NoFocus)
        self.report_box.setMinimumHeight(170)
        self.report_box.setMaximumHeight(300)
        self.report_box.setVisible(False)
        card_layout.addWidget(self.report_box)

        card_layout.addStretch(1)

        root.addWidget(self.card, 1)

        footer = QHBoxLayout()
        self.back_btn = QPushButton("← Back")
        self.back_btn.clicked.connect(self._go_back)
        footer.addWidget(self.back_btn)
        footer.addStretch()
        self.copy_btn = QPushButton("Copy Report")
        self.copy_btn.setVisible(False)
        self.copy_btn.clicked.connect(self._copy_report)
        footer.addWidget(self.copy_btn)
        self.export_btn = QPushButton("Export Report")
        self.export_btn.setVisible(False)
        self.export_btn.clicked.connect(self._export_report)
        footer.addWidget(self.export_btn)
        self.restart_btn = QPushButton("Start Over")
        self.restart_btn.setProperty("role", "primary")
        self.restart_btn.clicked.connect(self.restart)
        footer.addWidget(self.restart_btn)
        root.addLayout(footer)

    # ---------- rendering ----------

    @staticmethod
    def _make_rich(label: QLabel):
        label.setTextFormat(Qt.RichText)
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)

    def _show_image(self, rel: str):
        pix = _load_image(self.base_dir, rel)
        if pix is None:
            self.image_label.setVisible(False)
            return
        if pix.height() > MAX_IMAGE_HEIGHT:
            pix = pix.scaledToHeight(MAX_IMAGE_HEIGHT, Qt.SmoothTransformation)
        self.image_label.setPixmap(pix)
        self.image_label.setVisible(True)

    def set_logo(self, rel: str):
        """Show the client's logo (relative to the flow's folder) in the header, or hide it."""
        pix = _load_image(self.base_dir, rel)
        if pix is None:
            self.logo_label.setVisible(False)
            return
        self.logo_label.setPixmap(pix.scaledToHeight(28, Qt.SmoothTransformation))
        self.logo_label.setVisible(True)

    def _clear_answers(self):
        while self.answers_layout.count():
            item = self.answers_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render(self, animate: bool = True):
        step = self.engine.current_step
        n = len(self.engine.history)

        self.back_btn.setEnabled(self.engine.can_go_back())
        self._clear_answers()

        if self.engine.is_finished:
            self.breadcrumb.setText(f"Finished — {n} step{'s' if n != 1 else ''} taken")
            self.question_label.setVisible(False)
            self.note_label.setVisible(False)
            self.resolution_label.setVisible(True)
            ok = self.engine.outcome == OUTCOME_RESOLVED
            self.resolution_label.setStyleSheet(
                f"color: {GREEN if ok else RED}; font-size: 16px; font-weight: 600;")
            self.resolution_label.setText(("✓  " if ok else "⚠  ") + rich_html(self.engine.resolution or ""))
            self._show_image(self.engine.resolution_image if ok else "")
            self.feedback_widget.setVisible(self.session_store is not None and ok)
            self.details_widget.setVisible(True)
            self.report_box.setVisible(True)
            self._refresh_report()
            self._save_now()
            self.copy_btn.setVisible(True)
            self.export_btn.setVisible(True)
        else:
            self.breadcrumb.setText(f"Step {n + 1}")
            self.question_label.setVisible(True)
            self.resolution_label.setVisible(False)
            self.image_label.setVisible(False)
            self._discard_saved()   # went back from an ending: that session isn't finished any more
            self.feedback_widget.setVisible(False)
            self.details_widget.setVisible(False)
            self.report_box.setVisible(False)
            self.copy_btn.setVisible(False)
            self.export_btn.setVisible(False)

            if step is None:
                self.question_label.setText("This flow has no steps yet.")
            else:
                self.question_label.setText(rich_html(step.question))
                self._show_image(step.image)
                if step.note:
                    self.note_label.setText(rich_html(step.note))
                    self.note_label.setVisible(True)
                else:
                    self.note_label.setVisible(False)

                for option in step.options:
                    btn = AnswerButton(option.label, terminal=option.is_terminal)
                    btn.clicked.connect(lambda _, o=option: self._choose(o))
                    self.answers_layout.addWidget(btn)

        if animate:
            self._fade_in()

        if self.on_step_changed:
            self.on_step_changed(self.engine.current_id)

    def _fade_in(self):
        anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._fade_anim = anim  # keep a reference alive

    def _choose(self, option):
        self.engine.choose(option)
        self._render()

    def _go_back(self):
        self.engine.go_back()
        self._render()

    def _on_details_changed(self):
        self.engine.ticket_ref = self.ticket_input.text().strip()
        self.engine.operator = self.operator_input.text().strip()
        self.engine.notes = self.notes_input.toPlainText()
        if self.engine.is_finished:
            self._refresh_report()
            self._save_timer.start()

    def _rate(self, clicked: QPushButton, other: QPushButton):
        other.setChecked(False)   # Yes/No are mutually exclusive, and clicking the lit one again clears it
        self._on_feedback_changed()

    def _on_feedback_changed(self):
        helpful = True if self.yes_btn.isChecked() else False if self.no_btn.isChecked() else None
        comment = self.feedback_comment.text().strip()
        if helpful is None and not comment:
            self.engine.feedback = None
        else:
            self.engine.set_feedback(helpful, comment)
        self._save_timer.start()

    def _save_now(self):
        self._save_timer.stop()
        if self.session_store is not None and self.engine.is_finished:
            if self.session_store.save(self.engine.record()):
                self._saved_session_id = self.engine.session_id

    def _discard_saved(self):
        self._save_timer.stop()
        if self.session_store is not None and self._saved_session_id == self.engine.session_id:
            self.session_store.discard(self._saved_session_id)
            self._saved_session_id = None

    def _refresh_report(self):
        self.report_box.setPlainText(self.engine.report_text())

    def _copy_report(self):
        QApplication.clipboard().setText(self.engine.report_text())

    def _export_report(self):
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", self.engine.ticket_ref).strip("-")
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        default_name = f"longleaf_report_{slug + '_' if slug else ''}{stamp}.txt"
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save Report", default_name, ";;".join(f for f, _ in EXPORT_FORMATS))
        if not path:
            return
        by_ext = {ext: ext for _, ext in EXPORT_FORMATS}
        by_filter = dict(EXPORT_FORMATS)
        fmt = by_ext.get(Path(path).suffix.lstrip(".").lower()) or by_filter.get(chosen, "txt")
        if not Path(path).suffix:
            path += "." + fmt
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.engine.record().render(fmt))
        except OSError as e:
            QMessageBox.critical(self, "Couldn't save report", str(e))
