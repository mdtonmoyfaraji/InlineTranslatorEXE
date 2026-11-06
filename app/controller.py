"""Ties everything together: tray icon, global shortcut, translator panel, insertion."""
from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import theme, winapi
from .ai import MAX_TRANSLATION_CHARS, AIClient, AIError
from .bubble import SelectionBubble
from .hotkeys import HotkeyService
from .inserter import CopyCapture, Inserter
from .mousewatch import MouseWatcher
from .panel import CARD_WIDTH, MARGIN, TranslatorPanel
from .uia import CARET, ELEMENT, SELECTION, WINDOW, Locator, Probe, looks_like_line_copy
from .settings import SettingsStore
from .settings_window import SettingsWindow
from .shortcut import format_shortcut

log = logging.getLogger("inline_translator.controller")


@dataclass
class Opening:
    """Everything the panel needs to know when it opens."""
    hwnd: int = 0
    standalone: bool = False
    anchor: winapi.Rect | None = None   # physical screen pixels (where the text cursor / selection is)
    text: str = ""                      # selected text to pre-fill
    editable: bool | None = None        # False = the selected text is read-only (web page, document)
    note: str = ""


class _Async(QObject):
    """Runs a function on a worker thread and delivers (result, error) on the Qt thread."""

    finished = Signal(int, object, object)

    def __init__(self) -> None:
        super().__init__()
        self._cbs: dict[int, Callable[[Any, Any], None]] = {}
        self._n = 0
        self.finished.connect(self._dispatch)

    def run(self, fn: Callable[[], Any], cb: Callable[[Any, Any], None]) -> None:
        self._n += 1
        i = self._n
        self._cbs[i] = cb

        def worker() -> None:
            try:
                self.finished.emit(i, fn(), None)
            except Exception as e:  # noqa: BLE001
                self.finished.emit(i, None, e)

        threading.Thread(target=worker, name="async-worker", daemon=True).start()

    def _dispatch(self, i: int, result: Any, error: Any) -> None:
        cb = self._cbs.pop(i, None)
        if cb:
            try:
                cb(result, error)
            except Exception:
                log.exception("async callback failed")


class Controller(QObject):
    show_settings_requested = Signal()

    def __init__(self, qapp: QApplication, store: SettingsStore, single, icon: QIcon, background: bool):
        super().__init__()
        self.qapp = qapp
        self.store = store
        self.single = single
        self.icon = icon
        self.background = background
        self.ai = AIClient()
        self.inserter = Inserter(self)
        self.copier = CopyCapture(self)
        self.locator = Locator()
        self._screens_cache: list[winapi.Rect] = []
        self.locator.set_screen_provider(lambda: self._screens_cache)
        self._async = _Async()
        self.panel: TranslatorPanel | None = None
        self.settings_window: SettingsWindow | None = None
        self._target_hwnd = 0
        self._standalone = False
        self._target_readonly = False
        self.bubble: SelectionBubble | None = None
        self._bubble_preset: Opening | None = None
        self._req_id = 0
        self._running = True

        s = store.settings
        self.hotkeys = HotkeyService(s.shortcut, self)
        self.hotkeys.triggered.connect(self._on_trigger)
        self.hotkeys.failed.connect(lambda m: self.notify("Shortcut listener", m))
        self.hotkeys.key_activity.connect(self._hide_bubble)
        self.show_settings_requested.connect(lambda: self.open_settings())

        self.mouse = MouseWatcher(self)
        self.mouse.selection_gesture.connect(self._on_selection_gesture)
        self.mouse.pressed.connect(self._on_mouse_pressed)

        self.tray = QSystemTrayIcon(icon, self)
        self._build_tray_menu()
        self.tray.activated.connect(self._on_tray_activated)

        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self._apply_theme())

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        s = self.store.settings
        if winapi.IS_WINDOWS:
            s.app.start_with_windows = winapi.autostart_enabled()
            if s.app.start_with_windows and not winapi.autostart_is_current():
                winapi.set_autostart(True)  # the exe was moved: keep the Run entry pointing at it
        self._apply_theme()
        self.tray.show()
        self._update_tray()
        self.hotkeys.start()
        self.mouse.start()
        threading.Thread(target=self._watch_second_launch, name="instance-watch", daemon=True).start()
        if not s.api.is_complete:
            if self.background:
                self.notify("Inline Translator", "Open the tray icon and add your AI connection to start translating.")
            else:
                self.open_settings("connection")
        elif not self.background:
            self.open_settings()

    def quit(self) -> None:
        self._running = False
        try:
            self.hotkeys.stop()
            self.mouse.stop()
            self.locator.stop()
            self.ai.close()
            self.tray.hide()
        finally:
            self.qapp.quit()

    def _watch_second_launch(self) -> None:
        while self._running:
            if self.single.wait_for_signal(500):
                self.show_settings_requested.emit()

    # --------------------------------------------------------------------- theme
    def is_dark(self) -> bool:
        pref = self.store.settings.prefs.theme
        if pref in ("dark", "light"):
            return pref == "dark"
        try:
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except Exception:
            return winapi.system_prefers_dark()

    def _apply_theme(self) -> None:
        dark = self.is_dark()
        self.qapp.setStyleSheet(theme.app_qss(theme.tokens(dark)))
        if self.settings_window:
            self.settings_window.apply_theme(dark)

    # ----------------------------------------------------------------- settings
    def apply_settings(self) -> None:
        s = self.store.settings
        try:
            self.store.save(notify=False)
        except OSError:
            log.exception("could not save settings")
            self.notify("Settings", "Could not save settings.json (is the folder writable?).")
        self.hotkeys.set_config(s.shortcut)
        self._apply_theme()
        self._update_tray()

    def hotkeys_set_suspended(self, value: bool) -> None:
        self.hotkeys.set_suspended(value)

    def restart_hotkeys(self) -> None:
        self.hotkeys.restart()
        self.notify("Inline Translator", "The shortcut listener was restarted.")

    def run_async(self, fn: Callable[[], Any], cb: Callable[[Any, Any], None]) -> None:
        self._async.run(fn, cb)

    def open_settings(self, page: str | None = None) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self)
            self.settings_window.apply_theme(self.is_dark())
        self.settings_window.present(page)

    # ---------------------------------------------------------------------- tray
    def _build_tray_menu(self) -> None:
        menu = QMenu()
        self.act_open = QAction("Open settings", menu)
        self.act_open.triggered.connect(lambda: self.open_settings())
        self.act_translate = QAction("Open translator (copies the result)", menu)
        self.act_translate.triggered.connect(lambda: self.activate(standalone=True))
        self.act_diag = QAction("Test cursor detection (in 3 seconds)", menu)
        self.act_diag.triggered.connect(lambda: QTimer.singleShot(3000, self._run_diagnostic))
        self.act_enabled = QAction("Shortcut enabled", menu)
        self.act_enabled.setCheckable(True)
        self.act_enabled.toggled.connect(self._on_toggle_enabled)
        self.act_autostart = QAction("Start with Windows", menu)
        self.act_autostart.setCheckable(True)
        self.act_autostart.toggled.connect(self._on_toggle_autostart)
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self.quit)
        for a in (self.act_open, self.act_translate):
            menu.addAction(a)
        menu.addAction(self.act_diag)
        menu.addSeparator()
        menu.addAction(self.act_enabled)
        menu.addAction(self.act_autostart)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self._menu = menu

    def _update_tray(self) -> None:
        s = self.store.settings
        sc = format_shortcut(s.shortcut) if s.shortcut.enabled else "shortcut off"
        self.tray.setToolTip(f"Inline Translator — {sc}")
        for act, val in ((self.act_enabled, s.shortcut.enabled), (self.act_autostart, s.app.start_with_windows)):
            act.blockSignals(True)
            act.setChecked(val)
            act.blockSignals(False)

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_settings()

    def _on_toggle_enabled(self, v: bool) -> None:
        self.store.settings.shortcut.enabled = v
        self.apply_settings()
        if self.settings_window:
            self.settings_window.refresh_all()

    def _on_toggle_autostart(self, v: bool) -> None:
        if winapi.IS_WINDOWS and not winapi.set_autostart(v):
            self._update_tray()
            return
        self.store.settings.app.start_with_windows = v
        self.apply_settings()
        if self.settings_window:
            self.settings_window.refresh_all()

    def notify(self, title: str, message: str) -> None:
        if self.store.settings.app.notifications and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)

    # ------------------------------------------------------------- shortcut → panel
    def _on_trigger(self, erase: int, delay_ms: int) -> None:
        QTimer.singleShot(max(0, delay_ms), lambda: self.activate(erase=erase))

    def activate(self, erase: int = 0, standalone: bool = False) -> None:
        if self.panel is not None and self.panel.is_open:
            self.panel.focus_input()
            return
        self._hide_bubble()
        hwnd = winapi.get_foreground()
        if (self.settings_window and self.settings_window.isVisible() and winapi.is_own_window(hwnd) and not standalone):
            self.settings_window.flash_trigger()  # "test the trigger" feedback
            return
        if erase > 0:
            winapi.send_backspaces(erase)  # remove the characters typed by earlier presses of a plain-key trigger
            QTimer.singleShot(50, lambda: self._begin(hwnd, standalone))
        else:
            self._begin(hwnd, standalone)

    # ---- step 1: find the text cursor and the selection of the program in front -----------
    def _begin(self, hwnd: int, standalone: bool, preset: Opening | None = None) -> None:
        if self.panel is not None and self.panel.is_open:
            return
        app = self.store.settings.app
        if standalone or not hwnd or winapi.is_own_window(hwnd):
            self._open(Opening(standalone=True))
            return
        if preset is not None:
            self._open(preset)
            return
        mode = app.panel_position
        classic = winapi.get_caret_screen_rect() if mode == "caret" else None
        want_sel = app.prefill_selection
        if not want_sel and (mode != "caret" or classic is not None):
            self._open(Opening(hwnd=hwnd, anchor=classic))
            return
        budget = 0.45 if (mode == "caret" and classic is None) else 0.30
        job = self._submit_probe(hwnd, want_sel, budget)
        self._poll(job, time.monotonic() + budget + 0.25, lambda probe: self._after_probe(hwnd, probe, classic, want_sel))

    def _submit_probe(self, hwnd: int, want_selection: bool, budget: float):
        self._screens_cache = self._physical_screens()
        return self.locator.submit(hwnd, want_selection, budget)

    def _poll(self, job, deadline: float, cb: Callable[[Probe], None]) -> None:
        if job.done.is_set() or time.monotonic() > deadline:
            cb(job.result)
            return
        QTimer.singleShot(15, lambda: self._poll(job, deadline, cb))

    @staticmethod
    def _physical_screens() -> list[winapi.Rect]:
        out = []
        for sc in QGuiApplication.screens():
            g, dpr = sc.geometry(), sc.devicePixelRatio()
            out.append(winapi.Rect(g.x(), g.y(), g.x() + round(g.width() * dpr), g.y() + round(g.height() * dpr)))
        return out

    # ---- step 2: decide the anchor and the pre-filled text, then open the panel -----------
    def _after_probe(self, hwnd: int, probe: Probe, classic: winapi.Rect | None, want_sel: bool) -> None:
        if self.panel is not None and self.panel.is_open:
            return
        app = self.store.settings.app
        log.info("cursor: source=%s precision=%s classic=%s selection_chars=%d selection_supported=%s editable=%s",
                 probe.source, probe.precision, classic is not None, len(probe.selection_text),
                 probe.selection_supported, probe.editable)
        anchor = (classic or probe.caret) if app.panel_position == "caret" else None
        op = Opening(hwnd=hwnd, anchor=anchor, editable=probe.editable)

        def finish(text: str) -> None:
            self._fill_selection(op, text)
            self._open(op)

        if want_sel and not probe.password:
            if probe.selection_text.strip():
                finish(probe.selection_text)
                return
            if not probe.selection_supported and app.copy_fallback and winapi.get_foreground() == hwnd:
                def copied(text: str | None) -> None:
                    if text and not looks_like_line_copy(text):
                        finish(text)
                    else:
                        self._open(op)

                self.copier.capture(copied)
                return
        self._open(op)

    @staticmethod
    def _fill_selection(op: Opening, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if len(text) > MAX_TRANSLATION_CHARS:
            text = text[:MAX_TRANSLATION_CHARS]
            op.note = f"The selection is longer than {MAX_TRANSLATION_CHARS} characters; only the first part was loaded."
        op.text = text

    def _open(self, op: Opening) -> None:
        if self.panel is not None and self.panel.is_open:
            return
        s = self.store.settings
        standalone = op.standalone or not op.hwnd
        anchor = self._anchor_rect(s.app.panel_position, standalone, op.anchor)
        avail = self._available_geometry(anchor.center())
        panel = TranslatorPanel(s.prefs, self.is_dark(), needs_setup=not s.api.is_complete, standalone=standalone)
        panel.submitted.connect(self._on_submit)
        panel.closed.connect(self._on_panel_closed)
        panel.prefs_changed.connect(self._on_prefs_changed)
        panel.open_settings.connect(lambda: self._settings_from_panel())
        panel.copy_requested.connect(self._on_copy_requested)
        self.panel = panel
        self._standalone = standalone
        self._target_hwnd = 0 if standalone else op.hwnd
        self._target_readonly = bool(op.text) and op.editable is False
        note = op.note
        if self._target_readonly:
            note = (note + " " if note else "") + "This text is read-only, so the translation will be shown here and copied."
        panel.open_at(anchor, avail, prefill=op.text, prefill_note=note.strip())
        if s.api.is_complete:
            cfg = deepcopy(s.api)
            threading.Thread(target=self.ai.warm, args=(cfg,), name="warm", daemon=True).start()

    def _settings_from_panel(self) -> None:
        if self.panel:
            self.panel.close_panel("outside")
        self.open_settings("connection")

    # -------------------------------------------------------------- positioning
    @staticmethod
    def physical_to_logical(x: int, y: int) -> QPoint:
        """Converts physical screen pixels (what Win32 reports) to Qt's logical coordinates."""
        for sc in QGuiApplication.screens():
            g = sc.geometry()
            dpr = sc.devicePixelRatio()
            native = QRect(g.topLeft(), QSize(round(g.width() * dpr), round(g.height() * dpr)))
            if native.contains(x, y):
                return QPoint(g.x() + round((x - g.x()) / dpr), g.y() + round((y - g.y()) / dpr))
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        return QPoint(round(x / dpr), round(y / dpr))

    @staticmethod
    def _available_geometry(point: QPoint) -> QRect:
        sc = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        return sc.availableGeometry()

    def _phys_rect_to_logical(self, rc: winapi.Rect) -> QRect:
        return QRect(self.physical_to_logical(rc.left, rc.top), self.physical_to_logical(rc.right, rc.bottom))

    def _anchor_rect(self, mode: str, standalone: bool, phys: winapi.Rect | None = None) -> QRect:
        """Logical-pixel rectangle the panel opens next to (below, or above when there is no room)."""
        panel_w = CARD_WIDTH + 2 * MARGIN
        if standalone or mode == "center":
            avail = self._available_geometry(QCursor.pos())
            cx, cy = avail.center().x(), avail.center().y()
            return QRect(cx - panel_w // 2 + MARGIN + 6, cy - 150 + MARGIN - 6 - 1, 1, 1)
        if mode == "caret" and phys is not None:
            return self._phys_rect_to_logical(phys)
        pos = QCursor.pos()  # "near the mouse" mode (or, as a last resort, when no text cursor could be found)
        return QRect(pos.x(), pos.y(), 1, 18)

    # ------------------------------------------------------------ panel callbacks
    def _on_prefs_changed(self, patch: dict) -> None:
        p = self.store.settings.prefs
        for k, v in patch.items():
            if hasattr(p, k):
                setattr(p, k, v)
        try:
            self.store.save(notify=False)
        except OSError:
            log.exception("could not save preferences")
        if self.settings_window:
            self.settings_window.refresh_all()

    def _on_copy_requested(self, text: str) -> None:
        Inserter.copy_for_user(text)

    def _on_panel_closed(self, reason: str) -> None:
        self._req_id += 1  # discard any in-flight translation
        target = self._target_hwnd
        self.panel = None
        self._target_hwnd = 0
        self._target_readonly = False
        if reason == "cancel" and target:
            winapi.force_foreground(target)  # give the cursor back exactly where it was

    def _on_submit(self, text: str, source: str, target: str, tone: str) -> None:
        panel = self.panel
        if panel is None:
            return
        self._req_id += 1
        rid = self._req_id
        cfg = deepcopy(self.store.settings.api)
        panel.set_busy(True)

        def work() -> str:
            return self.ai.translate(cfg, text, source, target, tone)

        def done(result: Any, error: Any) -> None:
            self._on_translated(rid, source, target, tone, result, error)

        self._async.run(work, done)

    def _on_translated(self, rid: int, source: str, target: str, tone: str, result: Any, error: Any) -> None:
        panel = self.panel
        if rid != self._req_id or panel is None or not panel.is_open:
            return  # closed or superseded while waiting
        if error is not None:
            if isinstance(error, AIError):
                panel.show_error(error.message, error.code != "config")
            else:
                log.error("translation failed", exc_info=error)
                panel.show_error(str(error) or "Unknown error.", True)
            return
        text: str = result
        self.store.push_recent(source, target, tone)
        panel.update_prefs(self.store.settings.prefs)

        if self._standalone or not self._target_hwnd or self._target_readonly:
            Inserter.copy_for_user(text)
            panel.show_result(text, "Done. The result was copied to the clipboard."
                              + (" (The selected text is read-only, so it cannot be replaced.)" if self._target_readonly else ""))
            return

        s = self.store.settings.app
        panel.busy = True  # keep the panel from closing itself while focus moves to the target
        panel.hide()

        def inserted(ok: bool, msg: str) -> None:
            p = self.panel
            if p is None or not p.is_open or rid != self._req_id:
                return
            if ok:
                p.close_panel("done")
                return
            p.show()
            p.show_result(text, f"{msg} The translation was copied: paste it with Ctrl+V.")
            p.focus_input()

        self.inserter.insert(self._target_hwnd, text, s.insert_method, s.restore_clipboard, inserted)

    # ----------------------------------------------------------- selection bubble
    def _on_selection_gesture(self, x: int, y: int) -> None:
        app = self.store.settings.app
        if not app.selection_bubble or (self.panel is not None and self.panel.is_open):
            return
        hwnd = winapi.get_foreground()
        if not hwnd or winapi.is_own_window(hwnd):
            return
        QTimer.singleShot(180, lambda: self._probe_for_bubble(hwnd, x, y))  # let the program finish selecting

    def _probe_for_bubble(self, hwnd: int, x: int, y: int) -> None:
        if winapi.get_foreground() != hwnd or (self.panel is not None and self.panel.is_open):
            return
        job = self._submit_probe(hwnd, True, 0.35)
        self._poll(job, time.monotonic() + 0.6, lambda probe: self._show_bubble(hwnd, probe, x, y))

    def _show_bubble(self, hwnd: int, probe: Probe, x: int, y: int) -> None:
        if probe.password or not probe.selection_text.strip() or winapi.get_foreground() != hwnd:
            return
        if self.panel is not None and self.panel.is_open:
            return
        anchor = probe.caret if probe.precision in (SELECTION, CARET) and probe.caret else winapi.Rect(x, y, x + 1, y + 20)
        op = Opening(hwnd=hwnd, anchor=anchor, editable=probe.editable)
        self._fill_selection(op, probe.selection_text)
        self._bubble_preset = op
        if self.bubble is None:
            self.bubble = SelectionBubble(self.icon, self.is_dark())
            self.bubble.clicked.connect(self._on_bubble_clicked)
        logical = self._phys_rect_to_logical(anchor)
        self.bubble.show_near(logical, self._available_geometry(logical.center()))
        self.hotkeys.watch_keys = True  # hide the bubble as soon as the user types

    def _hide_bubble(self) -> None:
        self.hotkeys.watch_keys = False
        if self.bubble is not None:
            self.bubble.hide_bubble()

    def _on_bubble_clicked(self) -> None:
        preset, self._bubble_preset = self._bubble_preset, None
        self._hide_bubble()
        if preset is None:
            return
        hwnd = preset.hwnd if winapi.is_window(preset.hwnd) else winapi.get_foreground()
        preset.hwnd = hwnd
        self._begin(hwnd, False, preset)

    def _on_mouse_pressed(self, x: int, y: int) -> None:
        if self.bubble is not None and self.bubble.isVisible():
            p = self.physical_to_logical(x, y)
            if not self.bubble.contains_global(p.x(), p.y()):
                self._hide_bubble()

    # --------------------------------------------------------------- diagnostics
    def _run_diagnostic(self) -> None:
        hwnd = winapi.get_foreground()
        classic = winapi.get_caret_screen_rect()
        job = self._submit_probe(hwnd, True, 0.8)

        def report(probe: Probe) -> None:
            where = classic or probe.caret
            msg = (f"Window class: {winapi.window_class(hwnd) or '?'}\n"
                   f"Text cursor: {'classic Win32' if classic else probe.source or 'not found'}"
                   f"{f' at {where.left},{where.top}' if where else ''}\n"
                   f"Selection: {len(probe.selection_text)} characters"
                   f"{'' if probe.selection_supported else ' (this program does not report selections)'}")
            log.info("diagnostic: %s", msg.replace("\n", " | "))
            self.tray.showMessage("Cursor detection", msg, QSystemTrayIcon.MessageIcon.Information, 9000)

        self._poll(job, time.monotonic() + 1.2, report)
