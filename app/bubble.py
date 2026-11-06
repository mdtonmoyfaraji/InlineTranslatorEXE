"""The small round "translate" bubble that appears next to selected text."""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme

SIZE = 36


class SelectionBubble(QWidget):
    clicked = Signal()

    def __init__(self, icon: QIcon, dark: bool):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(SIZE, SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Translate the selected text")
        self.t = theme.tokens(dark)
        self._pix = icon.pixmap(22, 22)
        self._hover = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_near(self, anchor: QRect, avail: QRect, seconds: float = 6.0) -> None:
        """``anchor`` = end of the selection (logical pixels). Sits just right of / below it."""
        x = anchor.right() + 8
        y = anchor.bottom() + 6
        if x + SIZE > avail.right():
            x = max(avail.left(), anchor.left() - SIZE - 8)
        if y + SIZE > avail.bottom():
            y = max(avail.top(), anchor.top() - SIZE - 6)
        self.move(x, y)
        self.show()
        self.raise_()
        self._timer.start(int(seconds * 1000))

    def hide_bubble(self) -> None:
        self._timer.stop()
        self.hide()

    def contains_global(self, x: int, y: int) -> bool:
        return self.isVisible() and self.geometry().contains(x, y)

    def enterEvent(self, e):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1.5, 1.5, SIZE - 3, SIZE - 3)
        p.setPen(QPen(QColor(self.t["accent"] if self._hover else self.t["line"]), 1.5))
        p.setBrush(QColor(self.t["bg"]))
        p.drawEllipse(r)
        p.drawPixmap(int((SIZE - self._pix.width() / self._pix.devicePixelRatio()) / 2),
                     int((SIZE - self._pix.height() / self._pix.devicePixelRatio()) / 2), self._pix)
