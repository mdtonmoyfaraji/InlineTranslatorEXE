"""Small reusable widgets for the settings window."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractButton, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget)

from . import theme
from .shortcut import vk_to_code


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def make_label(text: str = "", role: str | None = None, wrap: bool = True, name: str | None = None) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    if role:
        lab.setProperty("role", role)
    if name:
        lab.setObjectName(name)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def set_note(label: QLabel, kind: str | None, text: str = "") -> None:
    """kind: ok | err | warn | info | None (hides the label)."""
    label.setProperty("note", kind or "")
    label.setText(text)
    label.setWordWrap(True)
    label.setVisible(bool(kind and text))
    repolish(label)


def card(*widgets: QWidget, spacing: int = 12) -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    return f


def field(title: str, widget: QWidget, hint_text: str | None = None) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(make_label(title, "label"))
    lay.addWidget(widget)
    if hint_text:
        lay.addWidget(make_label(hint_text, "hint"))
    return box


def separator() -> QFrame:
    s = QFrame()
    s.setObjectName("sep")
    s.setFrameShape(QFrame.Shape.HLine)
    return s


class Switch(QAbstractButton):
    """iOS-style toggle."""

    def __init__(self, tokens: dict[str, str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.t = tokens or theme.LIGHT
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(110)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)

    def set_tokens(self, tokens: dict[str, str]) -> None:
        self.t = tokens
        self.update()

    def sizeHint(self):  # noqa: N802
        return QSize(40, 22)

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        self._pos = 1.0 if checked else 0.0
        self.update()

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _on_anim(self, v) -> None:
        self._pos = float(v)
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = QColor(self.t["line"]), QColor(self.t["accent"])
        mix = lambda a, b, k: int(a + (b - a) * k)  # noqa: E731
        track = QColor(mix(off.red(), on.red(), self._pos), mix(off.green(), on.green(), self._pos), mix(off.blue(), on.blue(), self._pos))
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor("#ffffff"))
        x = 3 + 18 * self._pos
        p.drawEllipse(QPointF(x + 8, 11), 8, 8)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(self.t["accent"]))
            p.drawRoundedRect(QRectF(0.5, 0.5, 39, 21), 11, 11)


class ToggleRow(QWidget):
    """A title + description on the left and a switch on the right."""

    toggled = Signal(bool)

    def __init__(self, title: str, description: str, tokens: dict[str, str]):
        super().__init__()
        from PySide6.QtWidgets import QHBoxLayout
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(make_label(title, "label"))
        if description:
            text.addWidget(make_label(description, "hint"))
        row.addLayout(text, 1)
        self.switch = Switch(tokens)
        self.switch.toggled.connect(self.toggled)
        row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_checked(self, v: bool) -> None:
        self.switch.blockSignals(True)
        self.switch.setChecked(v)
        self.switch.blockSignals(False)

    def is_checked(self) -> bool:
        return self.switch.isChecked()


class ShortcutRecorder(QPushButton):
    """Click, then press the keys you want. Modifier-only triggers (e.g. Ctrl) are recorded by
    pressing and releasing the modifier on its own."""

    recorded = Signal(str, bool, bool, bool, bool)  # code, ctrl, shift, alt, meta
    recording_changed = Signal(bool)

    _FAMILY = {Qt.Key.Key_Control: "Control", Qt.Key.Key_Shift: "Shift", Qt.Key.Key_Alt: "Alt",
               Qt.Key.Key_Meta: "Meta", Qt.Key.Key_AltGr: "Alt"}

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.recording = False
        self._idle_text = "Record…"
        self._mods_down: set[str] = set()
        self._pending: str | None = None
        self.setMinimumWidth(150)
        self.clicked.connect(self.toggle)

    def set_idle_text(self, text: str) -> None:
        self._idle_text = text
        if not self.recording:
            self.setText(text)

    def toggle(self) -> None:
        self.stop() if self.recording else self.start()

    def start(self) -> None:
        self.recording = True
        self._mods_down.clear()
        self._pending = None
        self.setText("Press the keys…  (Esc cancels)")
        self.setProperty("recording", True)
        repolish(self)
        self.grabKeyboard()
        self.recording_changed.emit(True)

    def stop(self) -> None:
        if not self.recording:
            return
        self.recording = False
        self.releaseKeyboard()
        self.setText(self._idle_text)
        self.setProperty("recording", False)
        repolish(self)
        self.recording_changed.emit(False)

    def focusOutEvent(self, e):  # noqa: N802
        self.stop()
        super().focusOutEvent(e)

    def keyPressEvent(self, e):  # noqa: N802
        if not self.recording:
            super().keyPressEvent(e)
            return
        if e.isAutoRepeat():
            return
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self.stop()
            return
        fam = self._FAMILY.get(key)
        if fam:
            self._pending = fam if not self._mods_down else None
            self._mods_down.add(fam)
            return
        vk = e.nativeVirtualKey()
        if vk in (0, 0xE5, 0xFF):  # unknown / IME composition
            return
        m = e.modifiers()
        code = vk_to_code(vk)
        self._pending = None
        self.stop()
        self.recorded.emit(code, bool(m & Qt.KeyboardModifier.ControlModifier), bool(m & Qt.KeyboardModifier.ShiftModifier),
                           bool(m & Qt.KeyboardModifier.AltModifier), bool(m & Qt.KeyboardModifier.MetaModifier))

    def keyReleaseEvent(self, e):  # noqa: N802
        if not self.recording:
            super().keyReleaseEvent(e)
            return
        if e.isAutoRepeat():
            return
        fam = self._FAMILY.get(e.key())
        if not fam:
            return
        self._mods_down.discard(fam)
        if self._pending == fam and not self._mods_down:
            self._pending = None
            self.stop()
            self.recorded.emit(fam, False, False, False, False)
