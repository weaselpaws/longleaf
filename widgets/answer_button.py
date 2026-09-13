"""
AnswerButton — a custom-painted option button used by the Player.

Plain QPushButton + QSS hover states look fine but static. This one
animates a 0..1 "glow" value on hover/press with a QPropertyAnimation
and paints its own rounded background/border/text each frame, so the
color and border actually ease in and out instead of snapping.
"""

from PySide6.QtWidgets import QPushButton, QSizePolicy
from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from theme import FIELD, BORDER, GOLD, GOLD_BRIGHT, TEXT, BG


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


class AnswerButton(QPushButton):
    def __init__(self, text: str, terminal: bool = False, parent=None):
        super().__init__(text, parent)
        self.terminal = terminal  # terminal answers (resolutions) read a touch differently
        self._glow = 0.0
        self.setMinimumHeight(48)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._anim = QPropertyAnimation(self, b"glow")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self._base_bg = QColor(FIELD)
        self._hover_bg = QColor(GOLD) if terminal else QColor(BORDER)
        self._base_border = QColor(BORDER)
        self._hover_border = QColor(GOLD)

    def getGlow(self) -> float:
        return self._glow

    def setGlow(self, value: float):
        self._glow = value
        self.update()

    glow = Property(float, getGlow, setGlow)

    def _animate_to(self, target: float):
        self._anim.stop()
        self._anim.setStartValue(self._glow)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event):
        self._animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_to(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        bg = _lerp_color(self._base_bg, self._hover_bg, self._glow)
        border = _lerp_color(self._base_border, self._hover_border, self._glow)

        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(rect, 8, 8)

        if self.terminal:
            text_color = _lerp_color(QColor(TEXT), QColor(BG), self._glow)
        else:
            text_color = _lerp_color(QColor(TEXT), QColor(GOLD_BRIGHT), self._glow)
        painter.setPen(text_color)
        font = self.font()
        font.setPointSize(11)
        font.setWeight(QFont.DemiBold if self.terminal else QFont.Normal)
        painter.setFont(font)
        painter.drawText(rect.adjusted(16, 0, -16, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())
