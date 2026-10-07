"""
ImagePicker — a path field plus Browse/Clear for choosing a flow image
(step screenshot, answer screenshot, or client logo). Editor-only.

Images are stored in the flow as paths relative to the flow file's
folder, so they travel with it and get bundled into the client's exe.
A picked file outside that folder is copied into an `images/` subfolder.
"""

import filecmp
import os
import shutil

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QMessageBox
from PySide6.QtCore import Signal

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.svg)"


def relative_asset_path(picked: str, base_dir: str) -> str:
    """Path to store in the flow for `picked`: relative to `base_dir` if it
    lives under it, otherwise copied into base_dir/images and pointed at there."""
    picked, base_dir = os.path.abspath(picked), os.path.abspath(base_dir)
    if os.path.commonpath([picked, base_dir]) == base_dir:
        return os.path.relpath(picked, base_dir).replace(os.sep, "/")
    dest_dir = os.path.join(base_dir, "images")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(picked))
    if os.path.exists(dest) and not filecmp.cmp(dest, picked, shallow=False):   # same name, different picture
        stem, ext = os.path.splitext(os.path.basename(picked))
        n = 2
        while os.path.exists(os.path.join(dest_dir, f"{stem}-{n}{ext}")):
            n += 1
        dest = os.path.join(dest_dir, f"{stem}-{n}{ext}")
    if not os.path.exists(dest):
        shutil.copy2(picked, dest)
    return os.path.relpath(dest, base_dir).replace(os.sep, "/")


class ImagePicker(QWidget):
    changed = Signal(str)   # the new relative path ("" when cleared)

    def __init__(self, placeholder: str = "No image", base_dir_provider=lambda: None, parent=None):
        super().__init__(parent)
        self.base_dir_provider = base_dir_provider
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.path_input.setPlaceholderText(placeholder)
        row.addWidget(self.path_input, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        clear = QPushButton("✕")
        clear.setFixedWidth(30)
        clear.setProperty("role", "danger")
        clear.clicked.connect(lambda: self._set("", emit=True))
        row.addWidget(clear)

    def path(self) -> str:
        return self.path_input.text()

    def set_path(self, rel: str):
        """Show `rel` without announcing a change (for loading from the model)."""
        self._set(rel, emit=False)

    def _set(self, rel: str, emit: bool):
        self.path_input.setText(rel)
        if emit:
            self.changed.emit(rel)

    def _browse(self):
        base_dir = self.base_dir_provider()
        if not base_dir:
            QMessageBox.information(
                self, "Save the flow first",
                "Images are stored next to the flow file. Save the flow once, then pick an image.")
            return
        picked, _ = QFileDialog.getOpenFileName(self, "Choose image", base_dir, IMAGE_FILTER)
        if picked:
            try:
                rel = relative_asset_path(picked, base_dir)
            except OSError as e:
                QMessageBox.critical(self, "Couldn't use image", str(e))
                return
            self._set(rel, emit=True)
