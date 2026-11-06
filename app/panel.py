"""The floating translator panel (the desktop twin of the extension's in-page panel)."""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
                               QStyledItemDelegate, QStyleOptionViewItem, QTextEdit, QVBoxLayout, QWidget)

from . import theme, winapi
from .languages import (AUTO, CUSTOM_PREFIX, LANGUAGES, NONE, find_language, language_name,
                        make_custom_language_code, search_languages)
from .settings import Prefs
from .tones import (MAX_CUSTOM_TONE_LENGTH, TONE_DEFAULT, TONES, find_tone, is_custom_tone,
                    make_custom_tone_code, search_tones, tone_name)

log = logging.getLogger("inline_translator.panel")

MARGIN = 16  # transparent margin around the card (room for the shadow)
CARD_WIDTH = 392
ROLE = Qt.ItemDataRole.UserRole


# ----------------------------------------------------------------------- small widgets

class IconButton(QPushButton):
    """Flat 28x28 button with a hand-drawn glyph ("swap" or "close")."""

    def __init__(self, kind: str, tooltip: str, tokens: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("icon")
        self.kind = kind
        self.tokens = tokens
        self.setFixedSize(28, 28)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(self.tokens["muted"] if self.isEnabled() else self.tokens["line"])
        if self.underMouse() and self.isEnabled():
            col = QColor(self.tokens["fg"])
        pen = QPen(col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = QPointF(self.width() / 2, self.height() / 2)
        if self.kind == "close":
            d = 4.5
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))
        else:  # swap: two opposite arrows
            x0, x1 = c.x() - 6, c.x() + 6
            y0, y1 = c.y() - 3.5, c.y() + 3.5
            p.drawLine(QPointF(x0, y0), QPointF(x1, y0))
            p.drawLine(QPointF(x1 - 2.5, y0 - 2.5), QPointF(x1, y0))
            p.drawLine(QPointF(x1 - 2.5, y0 + 2.5), QPointF(x1, y0))
            p.drawLine(QPointF(x1, y1), QPointF(x0, y1))
            p.drawLine(QPointF(x0 + 2.5, y1 - 2.5), QPointF(x0, y1))
            p.drawLine(QPointF(x0 + 2.5, y1 + 2.5), QPointF(x0, y1))


class GoButton(QPushButton):
    """Round accent button with an arrow, or a spinner while translating."""

    def __init__(self, tokens: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("go")
        self.tokens = tokens
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Translate (Enter)")
        self.setAccessibleName("Translate")
        self._busy = False
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 24) % 360
        self.update()

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(self.tokens["accent_fg"] if self.isEnabled() else self.tokens["muted"])
        pen = QPen(col, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = QPointF(self.width() / 2, self.height() / 2)
        if self._busy:
            r = QRectF(c.x() - 7, c.y() - 7, 14, 14)
            p.drawArc(r, int(-self._angle * 16), 270 * 16)
        else:
            p.drawLine(QPointF(c.x() - 5.5, c.y()), QPointF(c.x() + 5.5, c.y()))
            p.drawLine(QPointF(c.x() + 1.5, c.y() - 4), QPointF(c.x() + 5.5, c.y()))
            p.drawLine(QPointF(c.x() + 1.5, c.y() + 4), QPointF(c.x() + 5.5, c.y()))


class InputEdit(QTextEdit):
    """Auto-growing text box: Enter submits, Shift+Enter inserts a newline, Esc closes."""

    submit = Signal()
    escape = Signal()
    height_changed = Signal()
    MIN_H, MAX_H = 66, 170

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("input")
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.setPlaceholderText("Type to translate…")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        opt = self.document().defaultTextOption()
        opt.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)  # Arabic / Hebrew / Urdu read right-to-left
        self.document().setDefaultTextOption(opt)
        self.document().documentLayout().documentSizeChanged.connect(self._grow)
        self.setFixedHeight(self.MIN_H)

    def _grow(self, *_):
        h = max(self.MIN_H, min(self.MAX_H, int(self.document().size().height()) + 18))
        if h != self.height():
            self.setFixedHeight(h)
            self.height_changed.emit()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submit.emit()
            return
        if e.key() == Qt.Key.Key_Escape:
            self.escape.emit()
            return
        super().keyPressEvent(e)

    def insertFromMimeData(self, source):  # noqa: N802
        if source.hasText():
            self.insertPlainText(source.text())


class SearchEdit(QLineEdit):
    move = Signal(int)
    accept_ = Signal()
    escape = Signal()

    def keyPressEvent(self, e):  # noqa: N802
        k = e.key()
        if k == Qt.Key.Key_Down:
            self.move.emit(1)
        elif k == Qt.Key.Key_Up:
            self.move.emit(-1)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept_.emit()
        elif k == Qt.Key.Key_Escape:
            self.escape.emit()
        else:
            super().keyPressEvent(e)


class LangDelegate(QStyledItemDelegate):
    def __init__(self, tokens: dict[str, str], parent=None):
        super().__init__(parent)
        self.t = tokens

    def sizeHint(self, option, index):  # noqa: N802
        d = index.data(ROLE) or {}
        return QSize(option.rect.width(), 26 if d.get("kind") == "group" else 30)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):  # noqa: N802
        d = index.data(ROLE) or {}
        r = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        if not d:  # placeholder row ("No languages found")
            painter.setPen(QColor(t["muted"]))
            painter.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
            painter.restore()
            return
        if d.get("kind") == "group":
            f = painter.font()
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor(t["muted"]))
            painter.drawText(r.adjusted(10, 6, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, d["label"])
            painter.restore()
            return
        if d.get("active"):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t["hover"]))
            painter.drawRoundedRect(r.adjusted(2, 1, -2, -1), 7, 7)
        selected = d.get("selected")
        f = painter.font()
        f.setBold(bool(selected))
        painter.setFont(f)
        painter.setPen(QColor(t["accent"] if selected else t["fg"]))
        right = 34 if d.get("starrable") else 10
        native = d.get("native") or ""
        native_w = 0
        if native:
            nf = painter.font()
            nf.setBold(False)
            nf.setPointSizeF(max(7.5, nf.pointSizeF() - 1))
            painter.setFont(nf)
            native_w = min(110, painter.fontMetrics().horizontalAdvance(native) + 6)
            painter.setPen(QColor(t["muted"]))
            painter.drawText(QRect(r.right() - right - native_w, r.top(), native_w, r.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(native, Qt.TextElideMode.ElideRight, native_w))
            painter.setFont(f)
            painter.setPen(QColor(t["accent"] if selected else t["fg"]))
        name_rect = QRect(r.left() + 10, r.top(), r.width() - 10 - right - native_w - 4, r.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(d["label"], Qt.TextElideMode.ElideRight, name_rect.width()))
        if d.get("starrable"):
            painter.setPen(QColor(t["star"] if d.get("fav") else t["muted"]))
            sf = painter.font()
            sf.setBold(False)
            sf.setPointSizeF(sf.pointSizeF() + 1)
            painter.setFont(sf)
            painter.drawText(QRect(r.right() - 30, r.top(), 26, r.height()), Qt.AlignmentFlag.AlignCenter,
                             "★" if d.get("fav") else "☆")
        painter.restore()


class LangList(QListWidget):
    star_clicked = Signal(str)
    chosen = Signal(str)

    def __init__(self, tokens: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("langs")
        self.setItemDelegate(LangDelegate(tokens, self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setFixedHeight(230)

    def mousePressEvent(self, e):  # noqa: N802
        item = self.itemAt(e.position().toPoint())
        d = item.data(ROLE) if item else None
        if d and d.get("kind") == "opt":
            if d.get("starrable") and e.position().x() >= self.viewport().width() - 34:
                self.star_clicked.emit(d["code"])
                return
            self.chosen.emit(d["code"])
            return
        e.accept()

    def mouseMoveEvent(self, e):  # noqa: N802
        item = self.itemAt(e.position().toPoint())
        if item and (item.data(ROLE) or {}).get("kind") == "opt":
            self.set_active_row(self.row(item))


    def set_active_row(self, row: int) -> None:
        for i in range(self.count()):
            it = self.item(i)
            d = it.data(ROLE) or {}
            if d.get("kind") == "opt":
                new = dict(d, active=(i == row))
                if new != d:
                    it.setData(ROLE, new)
        if 0 <= row < self.count():
            self.scrollToItem(self.item(row), QListWidget.ScrollHint.EnsureVisible)
        self.viewport().update()

    def active_row(self) -> int:
        for i in range(self.count()):
            if (self.item(i).data(ROLE) or {}).get("active"):
                return i
        return -1

    def option_rows(self) -> list[int]:
        return [i for i in range(self.count()) if (self.item(i).data(ROLE) or {}).get("kind") == "opt"]


# ----------------------------------------------------------------------------- panel

class TranslatorPanel(QWidget):
    submitted = Signal(str, str, str, str)  # text, source, target, tone
    closed = Signal(str)               # "cancel" | "done" | "outside"
    prefs_changed = Signal(dict)
    open_settings = Signal()
    copy_requested = Signal(str)

    def __init__(self, prefs: Prefs, dark: bool, needs_setup: bool = False, standalone: bool = False):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle("Inline Translator")
        self.t = theme.tokens(dark)
        self.setStyleSheet(theme.panel_qss(self.t))
        self.prefs = Prefs(prefs.source_lang, prefs.target_lang, list(prefs.recent), list(prefs.favorites),
                           prefs.tone, list(prefs.tone_recent), list(prefs.tone_favorites), prefs.theme)
        self.needs_setup = needs_setup
        self.standalone = standalone
        self.busy = False
        self._opened = False
        self._closing = False
        self._picker_mode: str | None = None
        self._status_action: Callable[[], None] | None = None
        self._rows_cache: list[dict[str, Any]] = []
        self._anchor_avail: QRect | None = None
        self._anchor_rect: QRect | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card.setFixedWidth(CARD_WIDTH)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 120 if dark else 70))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # --- top bar
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.src_btn = self._picker_button("source")
        self.dst_btn = self._picker_button("target")
        self.tone_btn = self._picker_button("tone")
        self.swap_btn = IconButton("swap", "Swap languages", self.t)
        self.swap_btn.clicked.connect(self.swap)
        close_btn = IconButton("close", "Close (Esc)", self.t)
        close_btn.clicked.connect(lambda: self.close_panel("cancel"))
        bar.addWidget(self.src_btn)
        bar.addWidget(self.swap_btn)
        bar.addWidget(self.dst_btn)
        bar.addSpacing(4)
        bar.addWidget(self.tone_btn)
        bar.addStretch(1)
        bar.addWidget(close_btn)
        lay.addLayout(bar)

        # --- inline language picker (hidden until a language button is clicked)
        self.picker_box = QFrame(self.card)
        self.picker_box.setObjectName("pickerBox")
        pl = QVBoxLayout(self.picker_box)
        pl.setContentsMargins(6, 6, 6, 6)
        pl.setSpacing(4)
        self.search = SearchEdit()
        self.search.setObjectName("search")
        self.search.setClearButtonEnabled(False)
        self.search.textChanged.connect(self._render_rows)
        self.search.move.connect(self._move_active)
        self.search.accept_.connect(self._choose_active)
        self.search.escape.connect(self._close_picker)
        self.langs = LangList(self.t)
        self.langs.chosen.connect(self._choose_code)
        self.langs.star_clicked.connect(self._toggle_favorite)
        pl.addWidget(self.search)
        pl.addWidget(self.langs)
        self.picker_box.hide()
        lay.addWidget(self.picker_box)

        # --- input + go button
        self.field = QWidget(self.card)
        fl = QVBoxLayout(self.field)
        fl.setContentsMargins(0, 0, 0, 0)
        self.input = InputEdit()
        self.input.submit.connect(self.submit)
        self.input.escape.connect(lambda: self.close_panel("cancel"))
        self.input.height_changed.connect(self._relayout)
        fl.addWidget(self.input)
        self.go = GoButton(self.t, self.field)
        self.go.clicked.connect(self.submit)
        self.input.installEventFilter(self)
        lay.addWidget(self.field)

        # --- status line
        self.status = QFrame(self.card)
        self.status.setObjectName("status")
        sl = QHBoxLayout(self.status)
        sl.setContentsMargins(8, 5, 8, 5)
        sl.setSpacing(8)
        self.status_text = QLabel()
        self.status_text.setObjectName("statusText")
        self.status_text.setWordWrap(True)
        self.status_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_btn = QPushButton()
        self.status_btn.setObjectName("statusBtn")
        self.status_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_btn.clicked.connect(self._on_status_action)
        sl.addWidget(self.status_text, 1)
        sl.addWidget(self.status_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.status.hide()
        lay.addWidget(self.status)

        # --- result (fallback when the text could not be inserted)
        self.result = QTextEdit(self.card)
        self.result.setObjectName("resultBox")
        self.result.setReadOnly(True)
        self.result.setFixedHeight(96)
        self.result.setStyleSheet(
            f"QTextEdit#resultBox {{ background: {self.t['field']}; border: 1px solid {self.t['line']};"
            f" border-radius: 8px; padding: 6px; }}")
        opt = self.result.document().defaultTextOption()
        opt.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
        self.result.document().setDefaultTextOption(opt)
        self.result.hide()
        lay.addWidget(self.result)

        self._refresh_labels()
        self._update_swap_state()

    # ---- construction helpers ----------------------------------------------------
    def _picker_button(self, mode: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("picker")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumWidth(36)
        b.setMaximumWidth(112)
        b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.clicked.connect(lambda: self._toggle_picker(mode))
        return b

    def _button_text(self, mode: str) -> str:
        if mode == "source":
            return "Auto-detect" if self.prefs.source_lang == AUTO else language_name(self.prefs.source_lang)
        if mode == "target":
            return language_name(self.prefs.target_lang)
        return "Tone" if self.prefs.tone == TONE_DEFAULT else tone_name(self.prefs.tone)

    _KIND = {"source": "Source language", "target": "Target language", "tone": "Tone"}

    def _refresh_labels(self) -> None:
        tone_only = self.prefs.target_lang == NONE
        for btn, mode in ((self.src_btn, "source"), (self.dst_btn, "target"), (self.tone_btn, "tone")):
            text = self._button_text(mode)
            fm = btn.fontMetrics()
            btn.setText(fm.elidedText(text + "  ▾", Qt.TextElideMode.ElideRight, 100))
            btn.setToolTip(f"{self._KIND[mode]}: {text}")
            btn.setProperty("open", self._picker_mode == mode)
            if mode == "tone":
                btn.setProperty("tone", "active" if self.prefs.tone != TONE_DEFAULT else "idle")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        # Tone-only mode keeps the input language: the source language and swap make no sense.
        self.src_btn.setVisible(not tone_only)
        self.swap_btn.setVisible(not tone_only)
        self.input.setPlaceholderText(
            "Type text to rewrite in the chosen tone…" if tone_only
            else ("Type to translate… (the result is copied to the clipboard)" if self.standalone else "Type to translate…"))
        if self._opened:
            self._relayout()

    def _update_swap_state(self) -> None:
        auto = self.prefs.source_lang == AUTO
        self.swap_btn.setEnabled(not auto)
        self.swap_btn.setToolTip("Choose a source language to swap" if auto else "Swap languages")

    # ---- picker models: languages (source / target) and tones share one dropdown ----------
    @staticmethod
    def _lang_item(code: str, label: str, sub: str = "", starrable: bool = True) -> dict[str, Any]:
        return {"code": code, "label": label, "native": sub, "starrable": starrable}

    def _lang_item_for(self, code: str) -> dict[str, Any] | None:
        lang = find_language(code)
        if lang:
            return self._lang_item(code, lang.name, lang.native if lang.native != lang.name else "")
        if code.startswith(CUSTOM_PREFIX):
            return self._lang_item(code, language_name(code), "custom")
        return None

    def _tone_item_for(self, code: str) -> dict[str, Any] | None:
        t = find_tone(code)
        if t:
            return self._lang_item(code, t.name, t.hint)
        if is_custom_tone(code):
            return self._lang_item(code, tone_name(code), "custom")
        return None

    def _model(self, mode: str) -> dict[str, Any]:
        if mode == "tone":
            def custom(q: str, found: list[dict[str, Any]]):
                if any(i["label"].lower() == q.lower() for i in found) or len(q) > MAX_CUSTOM_TONE_LENGTH:
                    return None
                return self._lang_item(make_custom_tone_code(q), f"Custom tone: “{q}”", "custom", False)

            return {
                "placeholder": "Search or type your own tone…",
                "pinned": [self._lang_item(TONE_DEFAULT, "Default", "no tone", False)],
                "all": [self._lang_item(t.code, t.name, t.hint) for t in TONES],
                "all_label": "All tones",
                "resolve": self._tone_item_for,
                "search": lambda q: [self._lang_item(t.code, t.name, t.hint) for t in search_tones(q)],
                "custom": custom,
                "current": self.prefs.tone,
                "favorites": self.prefs.tone_favorites,
                "recent": self.prefs.tone_recent,
            }

        def lang_custom(q: str, found: list[dict[str, Any]]):
            if any(i["label"].lower() == q.lower() for i in found) or len(q) > 40:
                return None
            return self._lang_item(make_custom_language_code(q), f"Use “{q}”", "custom", False)

        pinned = ([self._lang_item(AUTO, "Detect language", "", False)] if mode == "source"
                  else [self._lang_item(NONE, "No translation", "tone only", False)])
        return {
            "placeholder": "Translate from…" if mode == "source" else "Translate to…",
            "pinned": pinned,
            "all": [self._lang_item(l.code, l.name, l.native if l.native != l.name else "") for l in LANGUAGES],
            "all_label": "All languages",
            "resolve": self._lang_item_for,
            "search": lambda q: [self._lang_item(l.code, l.name, l.native if l.native != l.name else "")
                                 for l in search_languages(q)],
            "custom": lang_custom,
            "current": self.prefs.source_lang if mode == "source" else self.prefs.target_lang,
            "favorites": self.prefs.favorites,
            "recent": self.prefs.recent,
        }

    # ---- language / tone picker ------------------------------------------------------
    def _toggle_picker(self, mode: str) -> None:
        if self._picker_mode == mode:
            self._close_picker()
            return
        self._picker_mode = mode
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.search.setPlaceholderText(self._model(mode)["placeholder"])
        self.picker_box.show()
        self._render_rows()
        self.search.setFocus()
        self._refresh_labels()
        self._relayout()

    def _close_picker(self) -> None:
        if self._picker_mode is None:
            return
        self._picker_mode = None
        self.picker_box.hide()
        self._refresh_labels()
        self.input.setFocus()
        self._relayout()

    def _build_rows(self) -> list[dict[str, Any]]:
        m = self._model(self._picker_mode or "target")
        q = self.search.text().strip()
        favs = set(m["favorites"])
        current = m["current"]

        def opt(item: dict[str, Any]) -> dict[str, Any]:
            return {"kind": "opt", "code": item["code"], "label": item["label"], "native": item["native"],
                    "starrable": item["starrable"], "fav": item["code"] in favs,
                    "selected": item["code"] == current, "active": False}

        rows: list[dict[str, Any]] = []
        if not q:
            rows += [opt(i) for i in m["pinned"]]
            fav_items = [i for i in map(m["resolve"], m["favorites"]) if i]
            if fav_items:
                rows.append({"kind": "group", "label": "Favorites"})
                rows += [opt(i) for i in fav_items]
            rec_items = [i for i in map(m["resolve"], [c for c in m["recent"] if c not in favs]) if i]
            if rec_items:
                rows.append({"kind": "group", "label": "Recent"})
                rows += [opt(i) for i in rec_items]
            rows.append({"kind": "group", "label": m["all_label"]})
            rows += [opt(i) for i in m["all"]]
            return rows
        lower = q.lower()
        rows += [opt(i) for i in m["pinned"] if lower in i["label"].lower()
                 or (self._picker_mode == "source" and lower in "detect automatically")]
        found = m["search"](q)
        rows += [opt(i) for i in found]
        extra = m["custom"](q, found)
        if extra:
            rows.append(opt(extra))
        return rows

    def _render_rows(self, *_):
        rows = self._build_rows()
        self.langs.setUpdatesEnabled(False)
        self.langs.clear()
        first_opt = selected = -1
        for i, r in enumerate(rows):
            it = QListWidgetItem()
            it.setData(ROLE, r)
            self.langs.addItem(it)
            if r["kind"] == "opt":
                if first_opt < 0:
                    first_opt = i
                if r.get("selected") and selected < 0:
                    selected = i
        self.langs.setUpdatesEnabled(True)
        if first_opt < 0:
            self.langs.addItem(QListWidgetItem("Nothing found"))
            return
        self.langs.set_active_row(first_opt if self.search.text().strip() or selected < 0 else selected)

    def _move_active(self, delta: int) -> None:
        rows = self.langs.option_rows()
        if not rows:
            return
        cur = self.langs.active_row()
        pos = rows.index(cur) if cur in rows else 0
        self.langs.set_active_row(rows[(pos + delta) % len(rows)])

    def _choose_active(self) -> None:
        row = self.langs.active_row()
        if row >= 0:
            self._choose_code(self.langs.item(row).data(ROLE)["code"])

    def _choose_code(self, code: str) -> None:
        mode = self._picker_mode
        if mode == "source":
            self.prefs.source_lang = code
            self.prefs_changed.emit({"source_lang": code})
        elif mode == "target" and code != AUTO:
            self.prefs.target_lang = code
            self.prefs_changed.emit({"target_lang": code})
        elif mode == "tone":
            self.prefs.tone = code
            self.prefs_changed.emit({"tone": code})
        self._update_swap_state()
        self._close_picker()  # also refreshes the button labels and the tone-only layout

    def _toggle_favorite(self, code: str) -> None:
        tone = self._picker_mode == "tone"
        favs = list(self.prefs.tone_favorites if tone else self.prefs.favorites)
        favs = [c for c in favs if c != code] if code in favs else (favs + [code])[-30:]
        if tone:
            self.prefs.tone_favorites = favs
            self.prefs_changed.emit({"tone_favorites": favs})
        else:
            self.prefs.favorites = favs
            self.prefs_changed.emit({"favorites": favs})
        scroll = self.langs.verticalScrollBar().value()
        active = self.langs.active_row()
        self._render_rows()
        self.langs.verticalScrollBar().setValue(scroll)
        if active >= 0:
            self.langs.set_active_row(min(active, self.langs.count() - 1))

    def swap(self) -> None:
        if self.prefs.source_lang == AUTO or self.prefs.target_lang == NONE:
            return
        self.prefs.source_lang, self.prefs.target_lang = self.prefs.target_lang, self.prefs.source_lang
        self._refresh_labels()
        self.prefs_changed.emit({"source_lang": self.prefs.source_lang, "target_lang": self.prefs.target_lang})
        self.input.setFocus()

    def update_prefs(self, prefs: Prefs) -> None:
        self.prefs.recent = list(prefs.recent)
        self.prefs.tone_recent = list(prefs.tone_recent)

    # ---- state display -----------------------------------------------------------
    def _on_status_action(self) -> None:
        if self._status_action:
            self._status_action()

    def clear_status(self) -> None:
        self.status.hide()
        self.status_text.clear()
        self.result.hide()
        self.result.clear()
        self._relayout()

    def show_notice(self, message: str, action_label: str | None = None,
                    action: Callable[[], None] | None = None, error: bool = False) -> None:
        self.status_text.setText(message)
        self.status.setProperty("error", error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self._status_action = action
        self.status_btn.setVisible(bool(action_label and action))
        if action_label:
            self.status_btn.setText(action_label)
        self.status.show()
        self._relayout()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.go.set_busy(busy)
        self.input.setReadOnly(busy or self.needs_setup)
        self.clear_status()
        if busy:
            self.show_notice("Translating…")

    def show_error(self, message: str, can_retry: bool) -> None:
        self.busy = False
        self.go.set_busy(False)
        self.input.setReadOnly(False)
        self.result.hide()
        self.show_notice(message, "Retry" if can_retry else None, self.submit if can_retry else None, error=True)
        self.input.setFocus()

    def show_result(self, text: str, note: str) -> None:
        """Shown when the text could not be inserted (or in standalone mode)."""
        self.busy = False
        self.go.set_busy(False)
        self.input.setReadOnly(False)
        self.show_notice(note, "Copy", lambda: self.copy_requested.emit(text))
        self.result.setPlainText(text)
        self.result.show()
        self._relayout()

    def submit(self) -> None:
        if self.busy or self.needs_setup:
            return
        text = self.input.toPlainText().strip()
        if not text:
            self.input.setFocus()
            return
        if self.prefs.target_lang == NONE and self.prefs.tone == TONE_DEFAULT:
            self.show_notice("“No translation” needs a tone. Choose a tone, or pick a target language.")
            return
        self.submitted.emit(text, self.prefs.source_lang, self.prefs.target_lang, self.prefs.tone)

    # ---- layout / positioning -------------------------------------------------------
    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.input and ev.type() == QEvent.Type.Resize:
            self._place_go()
        return super().eventFilter(obj, ev)

    def _place_go(self) -> None:
        g = self.go
        g.move(self.field.width() - g.width() - 7, self.field.height() - g.height() - 7)
        g.raise_()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._place_go()

    def _relayout(self) -> None:
        if not self._opened:
            return
        QTimer.singleShot(0, self._apply_layout)

    def _apply_layout(self) -> None:
        if not self._opened:
            return
        self.layout().activate()
        self.adjustSize()
        self._place_go()
        self._keep_on_screen()

    def _keep_on_screen(self) -> None:
        avail = self._anchor_avail
        if not avail:
            return
        x, y = self.x(), self.y()
        h, w = self.height(), self.width()
        if y + h - MARGIN > avail.bottom():
            above = self._anchor_rect.top() - h + MARGIN - 4 if self._anchor_rect else avail.bottom() - h + MARGIN
            y = above
        y = max(avail.top() - MARGIN + 2, min(y, avail.bottom() - h + MARGIN))
        x = max(avail.left() - MARGIN + 2, min(x, avail.right() - w + MARGIN))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def open_at(self, anchor: QRect, avail: QRect, prefill: str = "", prefill_note: str = "") -> None:
        """``anchor`` is the caret/mouse rectangle in Qt logical screen coordinates.
        ``prefill`` is the text that was selected in the other program."""
        self._anchor_avail = avail
        self._anchor_rect = anchor
        if prefill:
            self.input.setPlainText(prefill)
            cursor = self.input.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.input.setTextCursor(cursor)
        self.layout().activate()
        self.adjustSize()
        w, h = self.width(), self.height()
        x = anchor.left() - MARGIN - 6
        y = anchor.bottom() + 6 - MARGIN
        self.move(x, y)
        self._opened = True
        self._keep_on_screen()
        if y + h - MARGIN > avail.bottom():  # not enough room below: open above the caret
            self.move(self.x(), anchor.top() - h + MARGIN - 6)
            self._keep_on_screen()
        self.show()
        self.raise_()
        winapi.force_foreground(int(self.winId()))
        self.activateWindow()
        if self.needs_setup:
            self.input.setReadOnly(True)
            self.input.setPlaceholderText("Set up your AI connection to translate.")
            self.go.setEnabled(False)
            self.show_notice("No AI provider is configured yet.", "Open settings", self.open_settings.emit)
        elif prefill_note:
            self.show_notice(prefill_note)
        self.input.setFocus()

    def focus_input(self) -> None:
        self.activateWindow()
        winapi.force_foreground(int(self.winId()))
        self.input.setFocus()

    def close_panel(self, reason: str) -> None:
        if self._closing or not self._opened:
            return
        self._closing = True
        self._opened = False
        self.hide()
        self.closed.emit(reason)
        self.deleteLater()

    @property
    def is_open(self) -> bool:
        return self._opened and not self._closing

    # ---- closing when the user clicks elsewhere ----------------------------------------
    def event(self, e):  # noqa: N802
        if e.type() == QEvent.Type.WindowDeactivate and self._opened and not self.busy:
            QTimer.singleShot(150, self._check_deactivated)
        return super().event(e)

    def _check_deactivated(self) -> None:
        if self._opened and not self._closing and not self.busy and not self.isActiveWindow():
            self.close_panel("outside")

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            if self._picker_mode:
                self._close_picker()
            else:
                self.close_panel("cancel")
            return
        super().keyPressEvent(e)
