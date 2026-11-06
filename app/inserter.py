"""Puts the translation back where the cursor was in the original application.

Flow (all non-blocking, driven by Qt timers so the clipboard keeps being served):
  1. give focus back to the original window,
  2. wait until Windows reports it as foreground,
  3. paste (clipboard + Ctrl+V, original clipboard restored afterwards) or type it,
  4. report success / failure to the caller.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QMimeData, QObject, QTimer
from PySide6.QtGui import QGuiApplication

from . import winapi

log = logging.getLogger("inline_translator.insert")

_NO_HISTORY_FORMATS = {
    "ExcludeClipboardContentFromMonitorProcessing": b"\x01",
    "CanIncludeInClipboardHistory": b"\x00\x00\x00\x00",
    "CanUploadToCloudClipboard": b"\x00\x00\x00\x00",
}


def _snapshot_clipboard() -> QMimeData | None:
    """Copies whatever is on the clipboard (text, html, images, urls ...) so it can be restored."""
    try:
        src = QGuiApplication.clipboard().mimeData()
        if src is None:
            return None
        copy = QMimeData()
        for fmt in src.formats():
            if fmt.startswith("application/x-qt-"):
                continue
            data = src.data(fmt)
            if data:
                copy.setData(fmt, data)
        if src.hasImage():
            copy.setImageData(src.imageData())
        return copy if copy.formats() else None
    except Exception:
        log.exception("clipboard snapshot failed")
        return None


class Inserter(QObject):
    """One instance is reused; call ``insert`` for each translation."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._busy = False

    def insert(self, hwnd: int, text: str, method: str, restore_clipboard: bool,
               done: Callable[[bool, str], None]) -> None:
        """``done(ok, message)`` is called exactly once. On failure the text is left on the clipboard."""
        if self._busy:
            done(False, "Another insertion is still running.")
            return
        self._busy = True

        def finish(ok: bool, msg: str = "") -> None:
            self._busy = False
            done(ok, msg)

        clipboard = QGuiApplication.clipboard()
        if not winapi.IS_WINDOWS or not hwnd or not winapi.is_window(hwnd):
            self._copy(text)
            finish(False, "The original window is gone.")
            return

        previous = _snapshot_clipboard() if (method == "paste" and restore_clipboard) else None
        if method == "paste":
            self._copy(text)

        winapi.force_foreground(hwnd)
        deadline = time.monotonic() + 1.0

        def wait_for_focus() -> None:
            if winapi.get_foreground() == hwnd:
                QTimer.singleShot(40, act)  # let the target restore its inner focus
            elif time.monotonic() > deadline:
                self._copy(text)  # leave the translation on the clipboard as a fallback
                finish(False, "Could not return to the original window.")
            else:
                winapi.force_foreground(hwnd)
                QTimer.singleShot(30, wait_for_focus)

        def wait_modifiers(until: float) -> None:
            if winapi.physical_modifiers_down() and time.monotonic() < until:
                QTimer.singleShot(25, lambda: wait_modifiers(until))
            else:
                send()

        def act() -> None:
            wait_modifiers(time.monotonic() + 0.6)

        def send() -> None:
            try:
                if method == "type":
                    ok = winapi.type_text(text)
                else:
                    ok = winapi.send_ctrl_v()
            except Exception:
                log.exception("sending input failed")
                ok = False
            if not ok:
                self._copy(text)
                finish(False, "Windows blocked the keystrokes (is the target app running as administrator?).")
                return
            if method == "paste" and previous is not None:
                QTimer.singleShot(450, lambda: self._restore(previous, text))
            finish(True)

        QTimer.singleShot(0, wait_for_focus)
        _ = clipboard  # keep a reference for readability

    # ---- clipboard helpers ----------------------------------------------------------
    @staticmethod
    def _copy(text: str, history: bool = False) -> None:
        mime = QMimeData()
        mime.setText(text)
        if not history:
            for fmt, data in _NO_HISTORY_FORMATS.items():
                mime.setData(fmt, data)
        QGuiApplication.clipboard().setMimeData(mime)

    @staticmethod
    def copy_for_user(text: str) -> None:
        """Plain copy that the user expects to find in clipboard history too."""
        mime = QMimeData()
        mime.setText(text)
        QGuiApplication.clipboard().setMimeData(mime)

    @staticmethod
    def _restore(previous: QMimeData, ours: str) -> None:
        try:
            cb = QGuiApplication.clipboard()
            current = cb.mimeData()
            if current is not None and current.hasText() and current.text() != ours:
                return  # the user copied something else in the meantime: do not overwrite it
            cb.setMimeData(previous)
        except Exception:
            log.exception("clipboard restore failed")


class CopyCapture(QObject):
    """Reads the current selection of programs that cannot report it, by sending Ctrl+Insert (copy).

    The previous clipboard content is restored right after. Ctrl+Insert is used instead of Ctrl+C
    because it never sends an interrupt to a terminal when nothing is selected.
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._busy = False

    def capture(self, done: Callable[[str | None], None]) -> None:
        if self._busy or not winapi.IS_WINDOWS:
            done(None)
            return
        self._busy = True
        clipboard = QGuiApplication.clipboard()
        previous = _snapshot_clipboard()
        sentinel = f"\u200b__inline_translator_probe_{time.monotonic_ns()}__"
        Inserter._copy(sentinel)

        def finish(text: str | None) -> None:
            self._busy = False
            try:
                if previous is not None:
                    clipboard.setMimeData(previous)
                else:
                    clipboard.clear()
            except Exception:
                log.exception("clipboard restore failed")
            done(text)

        def poll(deadline: float) -> None:
            mime = clipboard.mimeData()
            text = mime.text() if mime is not None and mime.hasText() else ""
            if text and text != sentinel:
                finish(text)
            elif time.monotonic() > deadline:
                finish(None)
            else:
                QTimer.singleShot(20, lambda: poll(deadline))

        def send(until: float) -> None:
            if winapi.physical_modifiers_down() and time.monotonic() < until:
                QTimer.singleShot(25, lambda: send(until))
                return
            if not winapi.send_copy():
                finish(None)
                return
            poll(time.monotonic() + 0.45)

        QTimer.singleShot(0, lambda: send(time.monotonic() + 0.7))
