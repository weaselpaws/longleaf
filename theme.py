"""
Longleaf - shared visual theme.

Same brand as the rest of the YARI toolset (dark charcoal + gold), kept
in one place so the Player and Editor apps look like one product
instead of two separately-styled builds.
"""

from PySide6.QtWidgets import QApplication

from engine import is_hex_color, shade

BG = "#0F0D09"
PANEL = "#171310"
FIELD = "#1A1510"
BORDER = "#2A2116"
GOLD = "#C9952A"
GOLD_BRIGHT = "#E8B84B"
GOLD_DIM = "#9A7620"
TEXT = "#EDE8DF"
TEXT_DIM = "#9A9080"
GREEN = "#5FB865"
RED = "#D2685A"

DEFAULT_GOLD = GOLD


def set_accent(accent: str = ""):
    """Swap the accent colour (a client's brand colour, "#RRGGBB"), or
    restore the stock gold with an empty/invalid value. Updates the
    module colours; widgets that paint themselves read them at paint time."""
    global GOLD, GOLD_BRIGHT, GOLD_DIM
    GOLD = accent if is_hex_color(accent) else DEFAULT_GOLD
    GOLD_BRIGHT = "#E8B84B" if GOLD == DEFAULT_GOLD else shade(GOLD, 0.12)
    GOLD_DIM = "#9A7620" if GOLD == DEFAULT_GOLD else shade(GOLD, -0.12)


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def make_qss() -> str:
    """The application stylesheet for the current accent."""
    return f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}
QLabel {{
    color: {TEXT};
}}
QLabel[role="heading"] {{
    font-size: 20px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel[role="subheading"] {{
    color: {TEXT_DIM};
    font-size: 12px;
}}
QLabel[role="note"] {{
    color: {GOLD};
    font-style: italic;
}}
QFrame#card {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 12px;
    font-weight: 600;
    color: {GOLD};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background-color: {FIELD};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 8px;
    color: {TEXT};
    selection-background-color: {GOLD};
    selection-color: {BG};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border: 1px solid {GOLD};
}}
QListWidget, QTreeWidget {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 6px 8px;
    border-radius: 4px;
    color: {TEXT_DIM};
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {_rgba(GOLD, 0.18)};
    color: {GOLD_BRIGHT};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {_rgba(GOLD, 0.08)};
}}
QPushButton {{
    background-color: {FIELD};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 7px 16px;
    color: {TEXT};
}}
QPushButton:hover {{
    border: 1px solid {GOLD};
    color: {GOLD_BRIGHT};
}}
QPushButton:pressed {{
    background-color: {GOLD_DIM};
    color: {BG};
}}
QPushButton[role="primary"] {{
    background-color: {GOLD};
    color: {BG};
    border: none;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background-color: {GOLD_BRIGHT};
}}
QPushButton[role="primary"]:pressed {{
    background-color: {GOLD_DIM};
}}
QPushButton[role="danger"]:hover {{
    border: 1px solid {RED};
    color: {RED};
}}
QSplitter::handle {{
    background-color: {BORDER};
}}
QScrollBar:vertical {{
    background: {BG};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {GOLD_DIM};
}}
QMenuBar {{
    background-color: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item:selected {{
    background-color: {_rgba(GOLD, 0.18)};
    color: {GOLD_BRIGHT};
}}
QMenu {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{
    background-color: {_rgba(GOLD, 0.18)};
    color: {GOLD_BRIGHT};
}}
QStatusBar {{
    background-color: {PANEL};
    border-top: 1px solid {BORDER};
    color: {TEXT_DIM};
}}
"""


QSS = make_qss()  # stock look, kept for callers that want the constant


def apply_theme(app: QApplication, accent: str = ""):
    set_accent(accent)
    app.setStyleSheet(make_qss())
