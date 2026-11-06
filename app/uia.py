"""Finds the text caret and the selected text of the focused control through accessibility APIs.

Classic Win32 controls report their caret through ``GetGUIThreadInfo`` (see winapi).
Browsers, Electron apps, WPF/WinUI/Office and most modern programs do not, so we
ask them through:

  1. UI Automation  TextPattern2.GetCaretRange / TextPattern.GetSelection
  2. MSAA           OBJID_CARET
  3. UI Automation  bounding rectangle of the focused element
  4. the foreground window itself

Everything runs on one dedicated COM thread. Every step is wrapped so a failure only
means "try the next source"; the panel never waits longer than the caller's budget.
The COM code talks to the interfaces through raw v-table calls (no extra packages).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

from . import winapi
from .winapi import IS_WINDOWS, Rect

log = logging.getLogger("inline_translator.uia")

MAX_SELECTION_CHARS = 8000

# precision levels, best first
CARET, SELECTION, ELEMENT, WINDOW, NONE = "caret", "selection", "element", "window", "none"


# --------------------------------------------------------------------------- pure helpers

def anchor_from_ui_rects(rects: list[tuple[float, float, float, float]], at_end: bool = True) -> Rect | None:
    """Turns UIA bounding rectangles (left, top, width, height) into a 1px-wide anchor.

    A selection spanning several lines returns one rectangle per line: the anchor is the
    END of the last line, so the panel opens below the selection instead of covering it.
    """
    good = [r for r in rects if r[3] > 0 and r[0] == r[0] and r[1] == r[1]]
    if not good:
        return None
    left, top, width, height = good[-1] if at_end else good[0]
    x = left + (max(width, 0) if at_end else 0)
    if height > 400:  # not a text line (a whole block): not a usable anchor
        return None
    return Rect(int(x), int(top), int(x) + 1, int(top + height))


def anchor_from_element(rect: Rect | None) -> Rect | None:
    """Anchor for a focused control whose caret is unknown: just under its top-left area."""
    if rect is None or rect.width <= 0 or rect.height <= 0:
        return None
    if rect.height > 220:  # large editor / page: open near its top-left, not below the whole thing
        return Rect(rect.left + 14, rect.top + 14, rect.left + 15, rect.top + 36)
    return Rect(rect.left + 6, rect.top, rect.left + 7, rect.bottom)


def anchor_from_window(rect: Rect | None) -> Rect | None:
    if rect is None or rect.width <= 0 or rect.height <= 0:
        return None
    cx = rect.left + rect.width // 2
    cy = rect.top + int(rect.height * 0.30)
    return Rect(cx, cy, cx + 1, cy + 22)


def is_plausible_screen_rect(rect: Rect | None, screens: list[Rect]) -> bool:
    if rect is None or rect.height <= 0 or rect.height > 600 or rect.width < 0:
        return False
    if rect.left == 0 and rect.top == 0 and rect.right <= 1 and rect.bottom <= 1:
        return False
    return any(rect.left < s.right and rect.right > s.left and rect.top < s.bottom and rect.bottom > s.top for s in screens)


def looks_like_line_copy(text: str) -> bool:
    """Editors such as VS Code copy the whole line when nothing is selected: "line\\r\\n"."""
    t = text.replace("\r\n", "\n")
    return t.endswith("\n") and "\n" not in t[:-1]


# ------------------------------------------------------------------------------ results

@dataclass
class Probe:
    caret: Rect | None = None          # physical screen pixels
    precision: str = NONE              # CARET | SELECTION | ELEMENT | WINDOW | NONE
    source: str = ""                   # for the log / diagnostics
    selection_text: str = ""
    selection_supported: bool = False  # the focused control exposes UIA text selection
    editable: bool | None = None       # None = unknown
    password: bool = False
    element_rect: Rect | None = None


class Job:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Probe = Probe(source="not-run")

    def finish(self, result: Probe) -> None:
        self.result = result
        self.done.set()


# ------------------------------------------------------------------------- COM plumbing

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.WinDLL("ole32")
    oleaut32 = ctypes.WinDLL("oleaut32")
    oleacc = ctypes.WinDLL("oleacc")

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8)]

    class VARIANT(ctypes.Structure):  # 24 bytes on 64-bit Windows
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                    ("val", ctypes.c_longlong), ("pad", ctypes.c_longlong)]

    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(GUID)]
    ole32.CLSIDFromString.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long
    oleaut32.SafeArrayGetLBound.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_long)]
    oleaut32.SafeArrayGetUBound.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_long)]
    oleaut32.SafeArrayAccessData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    oleaut32.SafeArrayUnaccessData.argtypes = [ctypes.c_void_p]
    oleaut32.SafeArrayDestroy.argtypes = [ctypes.c_void_p]
    oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
    oleaut32.SysFreeString.restype = None
    for _fn in (oleaut32.SafeArrayGetLBound, oleaut32.SafeArrayGetUBound, oleaut32.SafeArrayAccessData,
                oleaut32.SafeArrayUnaccessData, oleaut32.SafeArrayDestroy):
        _fn.restype = ctypes.c_long
    oleacc.AccessibleObjectFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.POINTER(GUID),
                                                  ctypes.POINTER(ctypes.c_void_p)]
    oleacc.AccessibleObjectFromWindow.restype = ctypes.c_long

    def _guid(text: str) -> "GUID":
        g = GUID()
        ole32.CLSIDFromString(text, ctypes.byref(g))
        return g

    CLSID_UIAUTOMATION = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
    IID_IUIAUTOMATION = "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}"
    IID_TEXTPATTERN = "{32eba289-3583-42c9-9c59-3b6d9a1e9b6a}"
    IID_TEXTPATTERN2 = "{506a921a-fcc9-409f-b23b-37eb74106872}"
    IID_VALUEPATTERN = "{a94cd8b1-0844-4cd6-9d2d-640537ab39e9}"
    IID_IACCESSIBLE = "{618736e0-3c3d-11cf-810c-00aa00389b71}"

    UIA_VALUE_PATTERN, UIA_TEXT_PATTERN, UIA_TEXT_PATTERN2 = 10002, 10014, 10024
    CT_EDIT, CT_COMBOBOX, CT_TEXT, CT_DOCUMENT = 50004, 50003, 50020, 50030
    OBJID_CARET = 0xFFFFFFF8

    class _Ptr:
        """An interface pointer; ``call(index, argtypes, *args)`` invokes v-table slot ``index``."""

        __slots__ = ("ptr",)

        def __init__(self, ptr: int):
            self.ptr = ptr

        def call(self, index: int, argtypes: tuple, *args) -> int:
            vtbl = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
            return proto(vtbl[index])(self.ptr, *args)

        def query(self, iid: str) -> "_Ptr | None":
            out = ctypes.c_void_p()
            g = _guid(iid)
            hr = self.call(0, (ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(g), ctypes.byref(out))
            return _Ptr(out.value) if hr >= 0 and out.value else None

        def release(self) -> None:
            try:
                self.call(2, ())
            except Exception:
                pass

    class _Scope:
        """Collects interface pointers and releases them all at the end."""

        def __init__(self) -> None:
            self._items: list[_Ptr] = []

        def add(self, p: "_Ptr | None") -> "_Ptr | None":
            if p is not None:
                self._items.append(p)
            return p

        def close(self) -> None:
            for p in reversed(self._items):
                p.release()
            self._items.clear()

    def _out_ptr(parent: _Ptr, index: int, *args_before) -> "_Ptr | None":
        """Calls a method of the form HRESULT M(<args_before...>, IFoo** out)."""
        out = ctypes.c_void_p()
        types = tuple(t for t, _ in args_before) + (ctypes.POINTER(ctypes.c_void_p),)
        values = tuple(v for _, v in args_before) + (ctypes.byref(out),)
        hr = parent.call(index, types, *values)
        return _Ptr(out.value) if hr >= 0 and out.value else None

    def _range_rects(rng: _Ptr) -> list[tuple[float, float, float, float]]:
        psa = ctypes.c_void_p()
        if rng.call(10, (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(psa)) < 0 or not psa.value:
            return []
        try:
            lb, ub = ctypes.c_long(), ctypes.c_long()
            if oleaut32.SafeArrayGetLBound(psa, 1, ctypes.byref(lb)) < 0 or oleaut32.SafeArrayGetUBound(psa, 1, ctypes.byref(ub)) < 0:
                return []
            n = ub.value - lb.value + 1
            if n < 4 or n > 4000:
                return []
            data = ctypes.c_void_p()
            if oleaut32.SafeArrayAccessData(psa, ctypes.byref(data)) < 0 or not data.value:
                return []
            try:
                vals = list((ctypes.c_double * n).from_address(data.value))
            finally:
                oleaut32.SafeArrayUnaccessData(psa)
        finally:
            oleaut32.SafeArrayDestroy(psa)
        return [(vals[i], vals[i + 1], vals[i + 2], vals[i + 3]) for i in range(0, n - 3, 4)]

    def _range_text(rng: _Ptr, limit: int) -> str:
        bstr = ctypes.c_void_p()
        if rng.call(12, (ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)), limit, ctypes.byref(bstr)) < 0 or not bstr.value:
            return ""
        try:
            return ctypes.wstring_at(bstr.value)
        finally:
            oleaut32.SysFreeString(bstr)

    def _pattern(scope: _Scope, elem: _Ptr, pattern_id: int, iid: str) -> "_Ptr | None":
        unk = scope.add(_out_ptr(elem, 16, (ctypes.c_int, pattern_id)))  # GetCurrentPattern
        if unk is None:
            return None
        return scope.add(unk.query(iid))


# ------------------------------------------------------------------------------ worker

class Locator:
    """Runs accessibility queries on a dedicated COM thread.

    ``submit`` never blocks. If the previous query is stuck (an unresponsive target app)
    new jobs finish immediately as "busy"; after a few seconds a fresh worker is started.
    """

    STUCK_AFTER_S = 4.0

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple[Job, dict] | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._busy_since = 0.0
        self._lock = threading.Lock()
        self._generation = 0
        self._screens: Callable[[], list[Rect]] = lambda: []

    def set_screen_provider(self, fn: Callable[[], list[Rect]]) -> None:
        self._screens = fn

    def submit(self, fg_hwnd: int, want_selection: bool, budget_s: float = 0.45) -> Job:
        job = Job()
        if not IS_WINDOWS:
            job.finish(Probe(source="not-windows"))
            return job
        with self._lock:
            now = time.monotonic()
            if self._busy_since and now - self._busy_since > self.STUCK_AFTER_S:
                self._generation += 1  # abandon the stuck worker
                self._q = queue.Queue()
                self._thread = None
                self._busy_since = 0.0
            elif self._busy_since:
                job.finish(Probe(source="busy"))
                return job
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, args=(self._generation, self._q),
                                                name="uia-worker", daemon=True)
                self._thread.start()
            self._q.put((job, {"fg": fg_hwnd, "want_selection": want_selection, "budget": budget_s}))
        return job

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            try:
                self._q.put(None)
            except Exception:
                pass

    # ---- worker thread ---------------------------------------------------------------
    def _run(self, generation: int, q: "queue.Queue") -> None:
        ole32.CoInitializeEx(None, 0)  # multi-threaded apartment
        automation: _Ptr | None = None
        try:
            clsid, iid = _guid(CLSID_UIAUTOMATION), _guid(IID_IUIAUTOMATION)
            out = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(out))
            if hr >= 0 and out.value:
                automation = _Ptr(out.value)
            else:
                log.warning("UI Automation is not available (HRESULT 0x%08X)", hr & 0xFFFFFFFF)
            while generation == self._generation:
                item = q.get()
                if item is None:
                    break
                job, args = item
                with self._lock:
                    self._busy_since = time.monotonic()
                try:
                    job.finish(self._probe(automation, **args))
                except Exception:
                    log.exception("probe failed")
                    job.finish(Probe(source="error"))
                finally:
                    with self._lock:
                        if generation == self._generation:
                            self._busy_since = 0.0
        finally:
            if automation:
                automation.release()
            ole32.CoUninitialize()

    # ---- one probe: several attempts within the budget ---------------------------------
    def _probe(self, automation: "_Ptr | None", fg: int, want_selection: bool, budget: float) -> Probe:
        deadline = time.monotonic() + max(0.05, budget)
        best = Probe(source="none")
        attempt = 0
        while True:
            attempt += 1
            try:
                res = self._probe_once(automation, fg, want_selection)
            except Exception:
                log.exception("probe attempt failed")
                res = Probe(source="error")
            best = _better(best, res)
            precise = best.precision in (CARET, SELECTION)
            decided = (not want_selection) or best.selection_supported or attempt >= 2
            if (precise and decided) or time.monotonic() + 0.13 > deadline or best.password:
                break
            # Chromium/Electron only build their accessibility tree after the first query.
            time.sleep(0.12)
        if best.precision in (NONE, ELEMENT):
            fallback = anchor_from_window(winapi.window_rect(fg))
            if best.precision == NONE and fallback is not None:
                best.caret, best.precision, best.source = fallback, WINDOW, "window"
        return best

    def _probe_once(self, automation: "_Ptr | None", fg: int, want_selection: bool) -> Probe:
        res = Probe()
        screens = self._screens()
        scope = _Scope()
        try:
            elem = None
            if automation is not None:
                elem = scope.add(_out_ptr(automation, 8))  # IUIAutomation::GetFocusedElement
            if elem is not None:
                self._read_element(scope, elem, res, want_selection, screens)
            if res.precision not in (CARET, SELECTION):
                msaa = self._msaa_caret(fg)
                if msaa is not None and is_plausible_screen_rect(msaa, screens):
                    res.caret, res.precision, res.source = msaa, CARET, "msaa"
            if res.precision not in (CARET, SELECTION):
                a = anchor_from_element(res.element_rect)
                if a is not None and is_plausible_screen_rect(a, screens):
                    res.caret, res.precision, res.source = a, ELEMENT, "element"
        finally:
            scope.close()
        return res

    def _read_element(self, scope: "_Scope", elem: "_Ptr", res: Probe, want_selection: bool, screens: list[Rect]) -> None:
        # password fields: never read them
        pw = ctypes.c_int(0)
        if elem.call(35, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(pw)) >= 0 and pw.value:
            res.password = True
            res.source = "password"
        rc = wintypes.RECT()
        if elem.call(43, (ctypes.POINTER(wintypes.RECT),), ctypes.byref(rc)) >= 0:
            res.element_rect = Rect(rc.left, rc.top, rc.right, rc.bottom)
        ctype = ctypes.c_int(0)
        if elem.call(21, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(ctype)) >= 0:
            res.editable = self._editable(scope, elem, ctype.value)
        if res.password:
            return

        text_pattern = _pattern(scope, elem, UIA_TEXT_PATTERN, IID_TEXTPATTERN)
        res.selection_supported = text_pattern is not None

        # 1) selection (also gives the selected text)
        if text_pattern is not None:
            arr = scope.add(_out_ptr(text_pattern, 5))  # GetSelection
            length = ctypes.c_int(0)
            if arr is not None and arr.call(3, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(length)) >= 0 and length.value > 0:
                rng = scope.add(_out_ptr(arr, 4, (ctypes.c_int, 0)))  # GetElement(0)
                if rng is not None:
                    res.selection_text = _range_text(rng, MAX_SELECTION_CHARS + 1)
                    anchor = anchor_from_ui_rects(_range_rects(rng), at_end=True)
                    if res.selection_text.strip() and anchor is not None and is_plausible_screen_rect(anchor, screens):
                        res.caret, res.precision, res.source = anchor, SELECTION, "uia-selection"
                        return
                    if not res.selection_text.strip():
                        res.selection_text = ""
                        # collapsed selection = the caret
                        anchor = anchor_from_ui_rects(_range_rects(rng), at_end=True)
                        if anchor is None:
                            rng.call(6, (ctypes.c_int,), 0)  # ExpandToEnclosingUnit(Character)
                            anchor = anchor_from_ui_rects(_range_rects(rng), at_end=False)
                        if anchor is not None and is_plausible_screen_rect(anchor, screens):
                            res.caret, res.precision, res.source = anchor, CARET, "uia-selection-caret"
                            return

        # 2) TextPattern2 caret range
        tp2 = _pattern(scope, elem, UIA_TEXT_PATTERN2, IID_TEXTPATTERN2)
        if tp2 is not None:
            active = ctypes.c_int(0)
            out = ctypes.c_void_p()
            if tp2.call(10, (ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p)),
                        ctypes.byref(active), ctypes.byref(out)) >= 0 and out.value:
                rng = scope.add(_Ptr(out.value))
                anchor = anchor_from_ui_rects(_range_rects(rng), at_end=True)
                if anchor is None:
                    rng.call(6, (ctypes.c_int,), 0)
                    anchor = anchor_from_ui_rects(_range_rects(rng), at_end=False)
                if anchor is not None and is_plausible_screen_rect(anchor, screens):
                    res.caret, res.precision, res.source = anchor, CARET, "uia-caret"

    @staticmethod
    def _editable(scope: "_Scope", elem: "_Ptr", control_type: int) -> bool | None:
        value = _pattern(scope, elem, UIA_VALUE_PATTERN, IID_VALUEPATTERN)
        if value is not None:
            ro = ctypes.c_int(0)
            if value.call(5, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(ro)) >= 0:  # get_CurrentIsReadOnly
                return not bool(ro.value)
        if control_type in (CT_EDIT, CT_COMBOBOX):
            return True
        if control_type in (CT_DOCUMENT, CT_TEXT):
            return False  # page text / read-only document
        return None

    @staticmethod
    def _msaa_caret(fg: int) -> Rect | None:
        hwnd = winapi.focused_control(fg) or fg
        if not hwnd:
            return None
        scope = _Scope()
        try:
            pv = ctypes.c_void_p()
            g = _guid(IID_IACCESSIBLE)
            hr = oleacc.AccessibleObjectFromWindow(hwnd, OBJID_CARET, ctypes.byref(g), ctypes.byref(pv))
            if hr < 0 or not pv.value:
                return None
            acc = scope.add(_Ptr(pv.value))
            l, t, w, h = (ctypes.c_long() for _ in range(4))
            child = VARIANT(vt=3, val=0)  # VT_I4, CHILDID_SELF
            ptr_long = ctypes.POINTER(ctypes.c_long)
            hr = acc.call(22, (ptr_long, ptr_long, ptr_long, ptr_long, VARIANT),
                          ctypes.byref(l), ctypes.byref(t), ctypes.byref(w), ctypes.byref(h), child)  # accLocation
            if hr < 0 or h.value <= 0:
                return None
            return Rect(l.value, t.value, l.value + max(w.value, 1), t.value + h.value)
        except Exception:
            return None
        finally:
            scope.close()


def _rank(p: str) -> int:
    return {CARET: 0, SELECTION: 0, ELEMENT: 1, WINDOW: 2, NONE: 3}.get(p, 3)


def _better(a: Probe, b: Probe) -> Probe:
    """Keeps the most precise anchor, but accumulates what each attempt learned."""
    best = b if _rank(b.precision) < _rank(a.precision) else a
    other = a if best is b else b
    best.selection_supported = best.selection_supported or other.selection_supported
    best.password = best.password or other.password
    if best.editable is None:
        best.editable = other.editable
    if not best.selection_text and other.selection_text:
        best.selection_text = other.selection_text
    if best.element_rect is None:
        best.element_rect = other.element_rect
    return best
