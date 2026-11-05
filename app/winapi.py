"""Thin ctypes layer over the Win32 calls the app needs.

Everything here is a no-op / returns neutral values on non-Windows platforms so
the rest of the code can be imported and unit-tested anywhere.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import NamedTuple

log = logging.getLogger("inline_translator.winapi")

IS_WINDOWS = sys.platform == "win32"

# Marker put into dwExtraInfo of every key event we inject, so our own keyboard
# hook can ignore them.
INJECT_MARKER = 0x49545253

AUTOSTART_VALUE = "InlineTranslator"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class Rect(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    ULONG_PTR = ctypes.c_size_t
    LRESULT = ctypes.c_ssize_t

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                    ("rcCaret", RECT)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    def _bind(fn, argtypes, restype):
        fn.argtypes = argtypes
        fn.restype = restype

    _bind(user32.GetForegroundWindow, [], wintypes.HWND)
    _bind(user32.SetForegroundWindow, [wintypes.HWND], wintypes.BOOL)
    _bind(user32.BringWindowToTop, [wintypes.HWND], wintypes.BOOL)
    _bind(user32.ShowWindow, [wintypes.HWND, ctypes.c_int], wintypes.BOOL)
    _bind(user32.IsIconic, [wintypes.HWND], wintypes.BOOL)
    _bind(user32.IsWindow, [wintypes.HWND], wintypes.BOOL)
    _bind(user32.GetWindowThreadProcessId, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD)
    _bind(user32.AttachThreadInput, [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL)
    _bind(user32.GetGUIThreadInfo, [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)], wintypes.BOOL)
    _bind(user32.ClientToScreen, [wintypes.HWND, ctypes.POINTER(POINT)], wintypes.BOOL)
    _bind(user32.GetWindowRect, [wintypes.HWND, ctypes.POINTER(RECT)], wintypes.BOOL)
    _bind(user32.GetAsyncKeyState, [ctypes.c_int], ctypes.c_short)
    _bind(user32.SendInput, [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int], wintypes.UINT)
    _bind(user32.SetWindowsHookExW, [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD], wintypes.HHOOK)
    _bind(user32.UnhookWindowsHookEx, [wintypes.HHOOK], wintypes.BOOL)
    _bind(user32.CallNextHookEx, [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM], LRESULT)
    _bind(user32.GetMessageW, [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], wintypes.BOOL)
    _bind(user32.TranslateMessage, [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL)
    _bind(user32.DispatchMessageW, [ctypes.POINTER(wintypes.MSG)], LRESULT)
    _bind(user32.PostThreadMessageW, [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL)
    _bind(kernel32.GetCurrentThreadId, [], wintypes.DWORD)
    _bind(kernel32.GetModuleHandleW, [wintypes.LPCWSTR], wintypes.HMODULE)
    _bind(kernel32.CreateMutexW, [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE)
    _bind(kernel32.CreateEventW, [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE)
    _bind(kernel32.SetEvent, [wintypes.HANDLE], wintypes.BOOL)
    _bind(kernel32.WaitForSingleObject, [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD)
    _bind(kernel32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL)

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    VK_BACK, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN, VK_V = 0x08, 0x0D, 0x10, 0x11, 0x12, 0x5B, 0x5C, 0x56
    SW_RESTORE = 9
    WH_KEYBOARD_LL = 13
    WM_QUIT = 0x0012
    ERROR_ALREADY_EXISTS = 183


# ---------------------------------------------------------------- windows / focus

def get_foreground() -> int:
    if not IS_WINDOWS:
        return 0
    return int(user32.GetForegroundWindow() or 0)


def is_window(hwnd: int) -> bool:
    return bool(IS_WINDOWS and hwnd and user32.IsWindow(hwnd))


def window_process_id(hwnd: int) -> int:
    if not IS_WINDOWS or not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def is_own_window(hwnd: int) -> bool:
    return bool(hwnd) and window_process_id(hwnd) == os.getpid()


def force_foreground(hwnd: int) -> bool:
    """Brings ``hwnd`` to the foreground even when we are a background process.

    Windows only allows SetForegroundWindow for the process that owns the current
    foreground window, so we briefly attach our input queue to it.
    """
    if not IS_WINDOWS or not hwnd or not user32.IsWindow(hwnd):
        return False
    try:
        cur_tid = kernel32.GetCurrentThreadId()
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = False
        if fg_tid and fg_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        return get_foreground() == hwnd
    except Exception:
        log.exception("force_foreground failed")
        return False


def get_caret_screen_rect() -> Rect | None:
    """Caret rectangle (physical screen pixels) of the foreground window, if it exposes one.

    Classic Win32 / WinForms / WPF-with-system-caret / Notepad / Office expose it.
    Chromium, Electron and many modern apps do not; callers fall back to the mouse.
    """
    if not IS_WINDOWS:
        return None
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.hwndCaret:
            return None
        rc = info.rcCaret
        if rc.right - rc.left <= 0 and rc.bottom - rc.top <= 0:
            return None
        tl = POINT(rc.left, rc.top)
        br = POINT(rc.right, rc.bottom)
        if not user32.ClientToScreen(info.hwndCaret, ctypes.byref(tl)) or not user32.ClientToScreen(info.hwndCaret, ctypes.byref(br)):
            return None
        if tl.x == 0 and tl.y == 0 and br.x <= 1:
            return None
        return Rect(tl.x, tl.y, max(br.x, tl.x + 1), max(br.y, tl.y + 1))
    except Exception:
        log.exception("get_caret_screen_rect failed")
        return None


# -------------------------------------------------------------------- key sending

def _kb(vk: int = 0, scan: int = 0, flags: int = 0) -> "INPUT":
    i = INPUT()
    i.type = INPUT_KEYBOARD
    i.ki = KEYBDINPUT(vk, scan, flags, 0, INJECT_MARKER)
    return i


def _send(events: list) -> int:
    if not events:
        return 0
    arr = (INPUT * len(events))(*events)
    return int(user32.SendInput(len(events), arr, ctypes.sizeof(INPUT)))


def physical_modifiers_down() -> bool:
    if not IS_WINDOWS:
        return False
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))


def modifier_state() -> dict[str, bool]:
    """Physical state of the modifier keys right now (used to heal missed key-up events)."""
    if not IS_WINDOWS:
        return {"Control": False, "Shift": False, "Alt": False, "Meta": False}
    down = lambda vk: bool(user32.GetAsyncKeyState(vk) & 0x8000)  # noqa: E731
    return {"Control": down(VK_CONTROL), "Shift": down(VK_SHIFT), "Alt": down(VK_MENU),
            "Meta": down(VK_LWIN) or down(VK_RWIN)}


def send_ctrl_v() -> bool:
    if not IS_WINDOWS:
        return False
    ev = [_kb(VK_CONTROL), _kb(VK_V), _kb(VK_V, flags=KEYEVENTF_KEYUP), _kb(VK_CONTROL, flags=KEYEVENTF_KEYUP)]
    return _send(ev) == len(ev)


def send_backspaces(count: int) -> None:
    if not IS_WINDOWS or count <= 0:
        return
    ev: list = []
    for _ in range(count):
        ev += [_kb(VK_BACK), _kb(VK_BACK, flags=KEYEVENTF_KEYUP)]
    _send(ev)


def type_text(text: str) -> bool:
    """Types text as Unicode key events (no clipboard involved). Newlines become Shift+Enter."""
    if not IS_WINDOWS:
        return False
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    events: list = []
    ok = True

    def flush() -> None:
        nonlocal events, ok
        if events:
            ok = _send(events) == len(events) and ok
            events = []
            time.sleep(0.004)

    for ch in text:
        if ch == "\n":
            events += [_kb(VK_SHIFT), _kb(VK_RETURN), _kb(VK_RETURN, flags=KEYEVENTF_KEYUP), _kb(VK_SHIFT, flags=KEYEVENTF_KEYUP)]
        else:
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):
                unit = data[i] | (data[i + 1] << 8)
                events += [_kb(0, unit, KEYEVENTF_UNICODE), _kb(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
        if len(events) >= 160:
            flush()
    flush()
    return ok


# ----------------------------------------------------------------------- autostart

def _exe_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}" --background'
    main = os.path.abspath(sys.argv[0])
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    interp = pyw if os.path.exists(pyw) else sys.executable
    return f'"{interp}" "{main}" --background'


def autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            value, _ = winreg.QueryValueEx(k, AUTOSTART_VALUE)
        return bool(value)
    except OSError:
        return False


def autostart_is_current() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            value, _ = winreg.QueryValueEx(k, AUTOSTART_VALUE)
        return value == _exe_command()
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, AUTOSTART_VALUE, 0, winreg.REG_SZ, _exe_command())
            else:
                try:
                    winreg.DeleteValue(k, AUTOSTART_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.exception("could not update autostart")
        return False


def system_prefers_dark() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            value, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return False


# ------------------------------------------------------------------ single instance

class SingleInstance:
    """Named mutex + event: a second launch asks the running instance to show its window."""

    MUTEX = "Local\\InlineTranslator.Mutex"
    EVENT = "Local\\InlineTranslator.ShowSettings"

    def __init__(self) -> None:
        self._mutex = None
        self._event = None
        self.is_primary = True
        if not IS_WINDOWS:
            return
        self._mutex = kernel32.CreateMutexW(None, False, self.MUTEX)
        self.is_primary = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        self._event = kernel32.CreateEventW(None, False, False, self.EVENT)

    def signal_primary(self) -> None:
        if IS_WINDOWS and self._event:
            kernel32.SetEvent(self._event)

    def wait_for_signal(self, timeout_ms: int = 500) -> bool:
        """Blocks up to timeout_ms; True if another launch asked us to show the window."""
        if not IS_WINDOWS or not self._event:
            time.sleep(timeout_ms / 1000)
            return False
        return kernel32.WaitForSingleObject(self._event, timeout_ms) == 0
