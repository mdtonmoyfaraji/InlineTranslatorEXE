"""Ties everything together: tray icon, global shortcut, translator panel, insertion."""
from __future__ import annotations

import logging
import threading
from copy import deepcopy
from typing import Any, Callable

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import theme, winapi
from .ai import AIClient, AIError
from .hotkeys import HotkeyService
from .inserter import Inserter
from .panel import CARD_WIDTH, MARGIN, TranslatorPanel
from .settings import SettingsStore
from .settings_window import SettingsWindow
from .shortcut import format_shortcut

log = logging.getLogger("inline_translator.controller")


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
        self._async = _Async()
        self.panel: TranslatorPanel | None = None
        self.settings_window: SettingsWindow | None = None
        self._target_hwnd = 0
        self._standalone = False
        self._req_id = 0
        self._running = True

        s = store.settings
        self.hotkeys = HotkeyService(s.shortcut, self)
        self.hotkeys.triggered.connect(self._on_trigger)
        self.hotkeys.failed.connect(lambda m: self.notify("Shortcut listener", m))
        self.show_settings_requested.connect(lambda: self.open_settings())

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
        hwnd = winapi.get_foreground()
        if (self.settings_window and self.settings_window.isVisible() and winapi.is_own_window(hwnd) and not standalone):
            self.settings_window.flash_trigger()  # "test the trigger" feedback
            return
        if erase > 0:
            winapi.send_backspaces(erase)  # remove the characters typed by earlier presses of a plain-key trigger
            QTimer.singleShot(50, lambda: self._open_panel(hwnd, standalone))
        else:
            self._open_panel(hwnd, standalone)

    def _open_panel(self, hwnd: int, standalone: bool) -> None:
        if self.panel is not None and self.panel.is_open:
            return
        s = self.store.settings
        standalone = standalone or not hwnd or winapi.is_own_window(hwnd)
        anchor = self._anchor_rect(s.app.panel_position, standalone)
        avail = self._available_geometry(anchor.center())
        panel = TranslatorPanel(s.prefs, self.is_dark(), needs_setup=not s.api.is_complete, standalone=standalone)
        panel.submitted.connect(self._on_submit)
        panel.closed.connect(self._on_panel_closed)
        panel.prefs_changed.connect(self._on_prefs_changed)
        panel.open_settings.connect(lambda: self._settings_from_panel())
        panel.copy_requested.connect(self._on_copy_requested)
        self.panel = panel
        self._standalone = standalone
        self._target_hwnd = 0 if standalone else hwnd
        panel.open_at(anchor, avail)
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

    def _anchor_rect(self, mode: str, standalone: bool) -> QRect:
        panel_w = CARD_WIDTH + 2 * MARGIN
        if standalone or mode == "center":
            avail = self._available_geometry(QCursor.pos())
            cx, cy = avail.center().x(), avail.center().y()
            return QRect(cx - panel_w // 2 + MARGIN + 6, cy - 150 + MARGIN - 6 - 1, 1, 1)
        if mode == "caret":
            rc = winapi.get_caret_screen_rect()
            if rc is not None:
                tl = self.physical_to_logical(rc.left, rc.top)
                br = self.physical_to_logical(rc.right, rc.bottom)
                return QRect(tl, br)
        pos = QCursor.pos()
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
        if reason == "cancel" and target:
            winapi.force_foreground(target)  # give the cursor back exactly where it was

    def _on_submit(self, text: str, source: str, target: str) -> None:
        panel = self.panel
        if panel is None:
            return
        self._req_id += 1
        rid = self._req_id
        cfg = deepcopy(self.store.settings.api)
        panel.set_busy(True)

        def work() -> str:
            return self.ai.translate(cfg, text, source, target)

        def done(result: Any, error: Any) -> None:
            self._on_translated(rid, source, target, result, error)

        self._async.run(work, done)

    def _on_translated(self, rid: int, source: str, target: str, result: Any, error: Any) -> None:
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
        self.store.push_recent(source, target)
        panel.update_prefs(self.store.settings.prefs)

        if self._standalone or not self._target_hwnd:
            Inserter.copy_for_user(text)
            panel.show_result(text, "Translated and copied to the clipboard.")
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
