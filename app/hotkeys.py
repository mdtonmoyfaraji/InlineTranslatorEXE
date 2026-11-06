"""Global shortcut listener (low-level keyboard hook on its own thread).

The hook only compares each key against the configured trigger. Nothing that is
typed is stored, logged or sent anywhere.
"""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import winapi
from .shortcut import (KeyInfo, SequenceDetector, ShortcutConfig, is_modifier_only,
                       modifier_family, types_a_character, vk_to_code)

log = logging.getLogger("inline_translator.hotkeys")

WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
LLKHF_INJECTED = 0x10


class HotkeyService(QObject):
    """Emits ``triggered(erase_count, delay_ms)`` on the Qt thread when the shortcut is completed."""

    triggered = Signal(int, int)
    failed = Signal(str)
    key_activity = Signal()  # first key press after ``watch_keys`` was set (hides the selection bubble)

    def __init__(self, cfg: ShortcutConfig, parent: QObject | None = None):
        super().__init__(parent)
        self._cfg = cfg
        self._detector = SequenceDetector(cfg)
        self._lock = threading.Lock()
        self._suspended = False
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._proc = None
        self._mods = {"Control": False, "Shift": False, "Alt": False, "Meta": False}
        self._down: set[int] = set()
        self._swallow_up: set[int] = set()
        self._ready = threading.Event()
        self.watch_keys = False

    # ---- public ------------------------------------------------------------
    def start(self) -> None:
        if not winapi.IS_WINDOWS or (self._thread and self._thread.is_alive()):
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="keyboard-hook", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    def stop(self) -> None:
        if not winapi.IS_WINDOWS:
            return
        t = self._thread
        if t and t.is_alive() and self._thread_id:
            winapi.user32.PostThreadMessageW(self._thread_id, winapi.WM_QUIT, 0, 0)
            t.join(1.5)
        self._thread = None

    def restart(self) -> None:
        self.stop()
        self._mods = dict.fromkeys(self._mods, False)
        self._down.clear()
        self._swallow_up.clear()
        self.start()

    def set_config(self, cfg: ShortcutConfig) -> None:
        with self._lock:
            self._cfg = cfg
            self._detector.set_config(cfg)

    def set_suspended(self, value: bool) -> None:
        """Pauses trigger detection (e.g. while the shortcut recorder is open)."""
        with self._lock:
            self._suspended = value
            self._detector.reset()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._hook)

    # ---- hook thread ---------------------------------------------------------
    def _run(self) -> None:
        w = winapi
        self._thread_id = int(w.kernel32.GetCurrentThreadId())
        self._proc = w.HOOKPROC(self._callback)  # keep a reference: the GC must not free it
        self._hook = w.user32.SetWindowsHookExW(w.WH_KEYBOARD_LL, self._proc, w.kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            self._ready.set()
            self.failed.emit("Windows refused to install the keyboard listener (error %d)." % w.ctypes.get_last_error())
            return
        self._ready.set()
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
            if n_code == 0:  # HC_ACTION
                kb = w.ctypes.cast(l_param, w.ctypes.POINTER(w.KBDLLHOOKSTRUCT)).contents
                if kb.dwExtraInfo != w.INJECT_MARKER:
                    down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    up = w_param in (WM_KEYUP, WM_SYSKEYUP)
                    if (down or up) and self._handle(int(kb.vkCode), down):
                        return 1  # swallow
        except Exception:
            log.exception("keyboard hook callback failed")
        return w.user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _handle(self, vk: int, is_down: bool) -> bool:
        """Returns True if the event must be swallowed."""
        code = vk_to_code(vk)
        fam = modifier_family(code)

        # Track modifiers and physical key state even while disabled, so the state is right when enabled.
        if fam:
            self._mods[fam] = is_down
        repeat = False
        if is_down:
            repeat = vk in self._down
            self._down.add(vk)
        else:
            self._down.discard(vk)

        if is_down and self.watch_keys:
            self.watch_keys = False
            self.key_activity.emit()

        if vk in self._swallow_up:  # the completing key: swallow its auto-repeats and its key-up too
            if not is_down:
                self._swallow_up.discard(vk)
            return True

        with self._lock:
            cfg = self._cfg
            if self._suspended or not cfg.enabled:
                return False
            if is_down and not fam and code == cfg.code:
                self._mods = winapi.modifier_state()  # heal state after a lock screen / missed key-up
            info = KeyInfo(code, self._mods["Control"], self._mods["Shift"], self._mods["Alt"], self._mods["Meta"], repeat)
            now = time.monotonic() * 1000.0
            result = self._detector.on_key_down(info, now) if is_down else self._detector.on_key_up(info, now)

        if result != "completed":
            return False

        modifier_only = is_modifier_only(cfg)
        erase = 0
        if not modifier_only and not (cfg.ctrl or cfg.alt or cfg.meta) and types_a_character(cfg.code):
            erase = max(0, cfg.press_count - 1)  # earlier presses typed characters that must be removed
        self.triggered.emit(erase, cfg.activation_delay_ms)
        if modifier_only:
            return False
        self._swallow_up.add(vk)
        return True
