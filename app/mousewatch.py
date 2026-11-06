"""Watches mouse button events (never movement, never content) to notice text selections."""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import winapi
from .gesture import SelectionGesture

log = logging.getLogger("inline_translator.mouse")

WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_MBUTTONDOWN = 0x0201, 0x0202, 0x0204, 0x0207


class MouseWatcher(QObject):
    """Emits ``selection_gesture(x, y)`` (physical pixels) after a drag or double/triple click,
    and ``pressed(x, y)`` on any button press (used to dismiss the bubble)."""

    selection_gesture = Signal(int, int)
    pressed = Signal(int, int)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._proc = None
        self._gesture = SelectionGesture(double_click_ms=winapi.double_click_ms())
        self.enabled = True

    def start(self) -> None:
        if not winapi.IS_WINDOWS or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._run, name="mouse-hook", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not winapi.IS_WINDOWS:
            return
        t = self._thread
        if t and t.is_alive() and self._thread_id:
            winapi.user32.PostThreadMessageW(self._thread_id, winapi.WM_QUIT, 0, 0)
            t.join(1.5)
        self._thread = None

    def _run(self) -> None:
        w = winapi
        self._thread_id = int(w.kernel32.GetCurrentThreadId())
        self._proc = w.HOOKPROC(self._callback)
        self._hook = w.user32.SetWindowsHookExW(w.WH_MOUSE_LL, self._proc, w.kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            log.warning("mouse hook could not be installed")
            return
        msg = w.wintypes.MSG()
        try:
            while w.user32.GetMessageW(w.ctypes.byref(msg), None, 0, 0) > 0:
                w.user32.TranslateMessage(w.ctypes.byref(msg))
                w.user32.DispatchMessageW(w.ctypes.byref(msg))
        finally:
            w.user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _callback(self, n_code, w_param, l_param):
        w = winapi
        try:
            # Movement is by far the most frequent event: leave immediately.
            if n_code == 0 and self.enabled and w_param in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                ms = w.ctypes.cast(l_param, w.ctypes.POINTER(w.MSLLHOOKSTRUCT)).contents
                x, y = int(ms.pt.x), int(ms.pt.y)
                now = time.monotonic() * 1000.0
                if w_param == WM_LBUTTONDOWN:
                    self._gesture.on_down(x, y, now)
                    self.pressed.emit(x, y)
                elif w_param == WM_LBUTTONUP:
                    if self._gesture.on_up(x, y, now):
                        self.selection_gesture.emit(x, y)
                else:
                    self.pressed.emit(x, y)
        except Exception:
            log.exception("mouse hook callback failed")
        return w.user32.CallNextHookEx(None, n_code, w_param, l_param)
