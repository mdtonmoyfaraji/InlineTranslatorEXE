"""Settings window: General, AI connection, Languages & tones, Shortcut, About & privacy."""
from __future__ import annotations

import logging
import os
from copy import deepcopy
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget, QCheckBox)

from . import __version__, theme, winapi
from .ai import validate_api_config
from .languages import AUTO, LANGUAGES, NONE, language_name
from .logging_setup import log_path
from .settings import config_dir
from .shortcut import ShortcutConfig, format_shortcut, is_modifier_only, validate_shortcut
from .tones import (MAX_CUSTOM_TONE_LENGTH, TONE_DEFAULT, TONES, is_custom_tone, make_custom_tone_code,
                    tone_name)
from .widgets import (ShortcutRecorder, ToggleRow, card, field, make_label, repolish, separator, set_note)

if TYPE_CHECKING:  # pragma: no cover
    from .controller import Controller

log = logging.getLogger("inline_translator.settings_window")

PRESETS = [
    ("Choose a provider…", ""),
    ("OpenAI", "https://api.openai.com/v1"),
    ("OpenRouter", "https://openrouter.ai/api/v1"),
    ("Groq", "https://api.groq.com/openai/v1"),
    ("Google Gemini (OpenAI-compatible)", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("DeepSeek", "https://api.deepseek.com/v1"),
    ("Mistral", "https://api.mistral.ai/v1"),
    ("Together AI", "https://api.together.xyz/v1"),
    ("Ollama (local)", "http://localhost:11434/v1"),
    ("LM Studio (local)", "http://localhost:1234/v1"),
]


def _combo(items: list[tuple[str, str]], current: str) -> QComboBox:
    c = QComboBox()
    for label, data in items:
        c.addItem(label, data)
    i = c.findData(current)
    c.setCurrentIndex(max(0, i))
    return c


def _spin(lo: int, hi: int, value: int, suffix: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    s.setSuffix(suffix)
    s.setMinimumWidth(110)
    s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    return s


def _page(title: str, subtitle: str) -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    body.setObjectName("page")
    lay = QVBoxLayout(body)
    lay.setContentsMargins(28, 24, 28, 28)
    lay.setSpacing(14)
    lay.addWidget(make_label(title, name="h1"))
    if subtitle:
        lay.addWidget(make_label(subtitle, "muted"))
    area.setWidget(body)
    return area, lay


class SettingsWindow(QWidget):
    def __init__(self, ctrl: "Controller"):
        super().__init__()
        self.ctrl = ctrl
        self.store = ctrl.store
        self.t = theme.tokens(ctrl.is_dark())
        self.setObjectName("root")
        self.setWindowTitle("Inline Translator")
        self.setWindowIcon(ctrl.icon)
        self.resize(900, 640)
        self.setMinimumSize(780, 540)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(210)
        self.nav.setIconSize(QSize(0, 0))
        self.stack = QStackedWidget()
        outer.addWidget(self.nav)
        outer.addWidget(self.stack, 1)

        self._pages: dict[str, int] = {}
        for key, title, builder in (
            ("general", "General", self._build_general),
            ("connection", "AI connection", self._build_connection),
            ("languages", "Languages & tones", self._build_languages),
            ("shortcut", "Shortcut", self._build_shortcut),
            ("about", "About & privacy", self._build_about),
        ):
            self._pages[key] = self.stack.addWidget(builder())
            self.nav.addItem(QListWidgetItem(title))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.refresh_all()

    # ---- navigation ---------------------------------------------------------------------
    def show_page(self, key: str) -> None:
        self.nav.setCurrentRow(self._pages.get(key, 0))

    def present(self, page: str | None = None) -> None:
        if page:
            self.show_page(page)
        self.refresh_all()
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        winapi.force_foreground(int(self.winId()))

    def closeEvent(self, e: QCloseEvent):  # noqa: N802
        e.ignore()  # the app keeps running in the tray
        self.recorder.stop()
        self.hide()

    def refresh_all(self) -> None:
        s = self.store.settings
        self.row_autostart.set_checked(winapi.autostart_enabled() if winapi.IS_WINDOWS else s.app.start_with_windows)
        self.cb_insert.setCurrentIndex(max(0, self.cb_insert.findData(s.app.insert_method)))
        self.row_restore.set_checked(s.app.restore_clipboard)
        self.cb_pos.setCurrentIndex(max(0, self.cb_pos.findData(s.app.panel_position)))
        self.cb_theme.setCurrentIndex(max(0, self.cb_theme.findData(s.prefs.theme)))
        self.row_notify.set_checked(s.app.notifications)
        self.row_prefill.set_checked(s.app.prefill_selection)
        self.row_bubble.set_checked(s.app.selection_bubble)
        self.row_copyfb.set_checked(s.app.copy_fallback)
        self._load_connection()
        self._load_languages()
        self.sc_cfg = deepcopy(s.shortcut)
        self._load_shortcut()

    def apply_theme(self, dark: bool) -> None:
        self.t = theme.tokens(dark)
        for row in (self.row_autostart, self.row_restore, self.row_notify, self.row_sc_enabled,
                    self.row_prefill, self.row_bubble, self.row_copyfb):
            row.switch.set_tokens(self.t)

    # ===================================================================== General
    def _build_general(self) -> QWidget:
        s = self.store.settings
        area, lay = _page("General", "How the app starts and how translations are inserted.")
        self.row_autostart = ToggleRow("Start with Windows",
                                       "Launches silently in the system tray when you sign in.", self.t)
        self.row_autostart.toggled.connect(self._on_autostart)
        self.cb_insert = _combo([("Paste (fast, recommended)", "paste"), ("Type characters (no clipboard)", "type")], s.app.insert_method)
        self.cb_insert.currentIndexChanged.connect(lambda _=0: self._save_app("insert_method", self.cb_insert.currentData()))
        self.row_restore = ToggleRow("Restore my clipboard after pasting",
                                     "Your previous clipboard content is put back a moment after the translation is pasted.", self.t)
        self.row_restore.toggled.connect(lambda v: self._save_app("restore_clipboard", v))
        self.cb_pos = _combo([("Near the text cursor", "caret"), ("Near the mouse pointer", "mouse"),
                              ("Centre of the screen", "center")], s.app.panel_position)
        self.cb_pos.currentIndexChanged.connect(lambda _=0: self._save_app("panel_position", self.cb_pos.currentData()))
        self.cb_theme = _combo([("Follow Windows", "system"), ("Light", "light"), ("Dark", "dark")], s.prefs.theme)
        self.cb_theme.currentIndexChanged.connect(self._on_theme)
        self.row_notify = ToggleRow("Show tray notifications",
                                    "Tells you when a translation could not be inserted or the shortcut listener stops.", self.t)
        self.row_notify.toggled.connect(lambda v: self._save_app("notifications", v))

        lay.addWidget(card(self.row_autostart, separator(),
                           make_label("The tray icon is always available. If Windows hides it, drag it from the “^” overflow "
                                      "area onto the taskbar to pin it there.", "hint")))
        lay.addWidget(card(field("Insert method", self.cb_insert,
                                 "Paste works in almost every program. “Type” sends the text as keystrokes; use it where Ctrl+V is blocked."),
                           self.row_restore))
        self.row_prefill = ToggleRow("Load the selected text into the panel",
                                     "Select text in any program and press the shortcut: it appears in the panel, and Enter replaces the "
                                     "selection with the result. Read-only text (web pages) shows the result in the panel instead.", self.t)
        self.row_prefill.toggled.connect(lambda v: self._save_app("prefill_selection", v))
        self.row_bubble = ToggleRow("Show a translate bubble next to selected text",
                                    "After you select text with the mouse a small round button appears; click it to translate the selection. "
                                    "Works in programs that report their selection (browsers, Office, Notepad…).", self.t)
        self.row_bubble.toggled.connect(lambda v: self._save_app("selection_bubble", v))
        self.row_copyfb = ToggleRow("Copy the selection with Ctrl+Insert in other programs",
                                    "For programs that cannot report their selection (many editors). Your clipboard is restored afterwards.", self.t)
        self.row_copyfb.toggled.connect(lambda v: self._save_app("copy_fallback", v))
        lay.addWidget(card(field("Where the translator opens", self.cb_pos,
                                 "“Near the text cursor” finds the cursor in browsers and modern apps too. Use the tray item "
                                 "“Test cursor detection” if a program opens it in the wrong place."), field("Appearance", self.cb_theme)))
        lay.addWidget(card(make_label("Selected text", name="h2"), self.row_prefill, separator(), self.row_bubble, separator(), self.row_copyfb))
        lay.addWidget(card(self.row_notify))
        lay.addStretch(1)
        return area

    def _save_app(self, name: str, value) -> None:
        setattr(self.store.settings.app, name, value)
        self.ctrl.apply_settings()

    def _on_autostart(self, v: bool) -> None:
        ok = winapi.set_autostart(v) if winapi.IS_WINDOWS else True
        if not ok:
            self.row_autostart.set_checked(not v)
            return
        self._save_app("start_with_windows", v)

    def _on_theme(self, _=0) -> None:
        self.store.settings.prefs.theme = self.cb_theme.currentData()
        self.ctrl.apply_settings()

    # ============================================================== AI connection
    def _build_connection(self) -> QWidget:
        area, lay = _page("AI connection", "Any OpenAI-compatible chat endpoint works. Your key stays on this PC.")
        self.cb_preset = QComboBox()
        for label, url in PRESETS:
            self.cb_preset.addItem(label, url)
        self.cb_preset.currentIndexChanged.connect(self._on_preset)
        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("https://api.openai.com/v1")
        self.ed_model = QLineEdit()
        self.ed_model.setPlaceholderText("the model name your provider offers, e.g. gpt-4o-mini")
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_key.setPlaceholderText("sk-…")
        for e in (self.ed_url, self.ed_model, self.ed_key):
            e.setClearButtonEnabled(False)
        self.btn_show = QPushButton("Show key")
        self.btn_show.setProperty("link", True)
        self.btn_show.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show.clicked.connect(self._toggle_key)
        key_box = QWidget()
        kl = QVBoxLayout(key_box)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setSpacing(4)
        kl.addWidget(make_label("API key", "label"))
        kl.addWidget(self.ed_key)
        row = QHBoxLayout()
        row.addWidget(make_label("Encrypted with Windows (DPAPI) for your user account only.", "hint"), 1)
        row.addWidget(self.btn_show)
        kl.addLayout(row)

        self.cb_proxy = _combo([("Use the Windows proxy settings", "system"), ("No proxy", "none"), ("Custom HTTP proxy", "custom")], "system")
        self.cb_proxy.currentIndexChanged.connect(self._on_proxy_mode)
        self.ed_proxy = QLineEdit()
        self.ed_proxy.setPlaceholderText("http://127.0.0.1:7890")
        self.sp_timeout = _spin(5, 300, 60, " s")

        self.conn_status = make_label()
        set_note(self.conn_status, None)
        self.btn_test = QPushButton("Test connection")
        self.btn_save = QPushButton("Save")
        self.btn_save.setProperty("primary", True)
        self.btn_clear = QPushButton("Remove saved credentials")
        self.btn_test.clicked.connect(lambda: self._check(False))
        self.btn_save.clicked.connect(lambda: self._check(True))
        self.btn_clear.clicked.connect(self._clear_credentials)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_test)
        btns.addWidget(self.btn_save)
        btns.addStretch(1)
        btns.addWidget(self.btn_clear)

        lay.addWidget(card(field("Provider preset", self.cb_preset, "Only fills in the address. You still choose the model and paste your key."),
                           field("API Base URL", self.ed_url,
                                 "“/v1” and “/chat/completions” are added automatically. Plain http:// is only allowed for localhost."),
                           field("Model", self.ed_model), key_box))
        self.proxy_field = field("Proxy address", self.ed_proxy, "HTTP proxies only (SOCKS is not supported).")
        lay.addWidget(card(field("Network", self.cb_proxy), self.proxy_field, field("Timeout", self.sp_timeout)))
        lay.addWidget(self.conn_status)
        lay.addLayout(btns)
        lay.addStretch(1)
        return area

    def _load_connection(self) -> None:
        a = self.store.settings.api
        self.ed_url.setText(a.base_url)
        self.ed_model.setText(a.model)
        self.ed_key.setText(a.api_key)
        self.cb_proxy.setCurrentIndex(max(0, self.cb_proxy.findData(a.proxy_mode)))
        self.ed_proxy.setText(a.proxy_url)
        self.sp_timeout.setValue(a.timeout_s)
        self.cb_preset.setCurrentIndex(0)
        self._on_proxy_mode()

    def _toggle_key(self) -> None:
        hidden = self.ed_key.echoMode() == QLineEdit.EchoMode.Password
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.btn_show.setText("Hide key" if hidden else "Show key")

    def _on_preset(self, _=0) -> None:
        url = self.cb_preset.currentData()
        if url:
            self.ed_url.setText(url)
            self.ed_model.setFocus()

    def _on_proxy_mode(self, _=0) -> None:
        self.proxy_field.setVisible(self.cb_proxy.currentData() == "custom")

    def _read_api(self):
        a = deepcopy(self.store.settings.api)
        a.base_url = self.ed_url.text().strip()
        a.model = self.ed_model.text().strip()
        a.api_key = self.ed_key.text().strip()
        a.proxy_mode = self.cb_proxy.currentData()
        a.proxy_url = self.ed_proxy.text().strip()
        a.timeout_s = self.sp_timeout.value()
        return a

    def _check(self, persist: bool) -> None:
        cfg = self._read_api()
        problems = validate_api_config(cfg)
        if problems:
            set_note(self.conn_status, "err", problems[0])
            return
        if persist:
            self.store.settings.api = cfg
            self.ctrl.apply_settings()
        self.btn_test.setEnabled(False)
        self.btn_save.setEnabled(False)
        set_note(self.conn_status, "info", "Testing the connection…")

        def work():
            return self.ctrl.ai.test_connection(cfg)

        def done(result, error):
            self.btn_test.setEnabled(True)
            self.btn_save.setEnabled(True)
            if error is not None:
                set_note(self.conn_status, "err", str(error))
                return
            ok, msg = result
            if ok:
                set_note(self.conn_status, "ok", ("Saved. " if persist else "") + msg)
            else:
                set_note(self.conn_status, "warn" if persist else "err", (f"Saved, but the test failed: {msg}" if persist else msg))

        self.ctrl.run_async(work, done)

    def _clear_credentials(self) -> None:
        self.store.settings.api.api_key = ""
        self.ed_key.clear()
        self.ctrl.apply_settings()
        set_note(self.conn_status, "info", "The saved API key was removed.")

    # =========================================================== Languages & tones
    def _build_languages(self) -> QWidget:
        area, lay = _page("Languages & tones", "Defaults for the translator panel, your favourites, and the writing tones.")
        self.cb_src = QComboBox()
        self.cb_src.addItem("Detect language", AUTO)
        self.cb_dst = QComboBox()
        self.cb_dst.addItem("No translation (tone only)", NONE)
        for l in LANGUAGES:
            label = l.name if l.native == l.name else f"{l.name} — {l.native}"
            self.cb_src.addItem(label, l.code)
            self.cb_dst.addItem(label, l.code)
        self.cb_src.setMaxVisibleItems(16)
        self.cb_dst.setMaxVisibleItems(16)
        self.cb_src.currentIndexChanged.connect(lambda _=0: self._save_pref("source_lang", self.cb_src.currentData()))
        self.cb_dst.currentIndexChanged.connect(lambda _=0: self._save_pref("target_lang", self.cb_dst.currentData()))
        self.cb_tone = QComboBox()
        self.cb_tone.addItem("Default (no tone)", TONE_DEFAULT)
        for t in TONES:
            self.cb_tone.addItem(f"{t.name} – {t.hint}", t.code)
        self.cb_tone.setMaxVisibleItems(16)
        self.cb_tone.currentIndexChanged.connect(lambda _=0: self._save_pref("tone", self.cb_tone.currentData()))

        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(field("Default source language", self.cb_src), 1)
        row.addWidget(field("Default target language", self.cb_dst), 1)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        tone_holder = field("Default tone", self.cb_tone,
                            "Pick “No translation (tone only)” as the target to rewrite text in the language you typed, using the tone.")

        # ---- favourite languages
        self.fav_list = QListWidget()
        self.fav_list.setFixedHeight(130)
        self.cb_fav_add = QComboBox()
        self.cb_fav_add.setMaxVisibleItems(16)
        for l in LANGUAGES:
            self.cb_fav_add.addItem(l.name, l.code)
        btn_add = QPushButton("Add favourite")
        btn_add.clicked.connect(self._add_favorite)
        btn_rm = QPushButton("Remove selected")
        btn_rm.clicked.connect(self._remove_favorite)
        btn_clear_recent = QPushButton("Clear recent languages")
        btn_clear_recent.clicked.connect(self._clear_recent)
        add_row = QHBoxLayout()
        add_row.addWidget(self.cb_fav_add, 1)
        add_row.addWidget(btn_add)
        rm_row = QHBoxLayout()
        rm_row.addWidget(btn_rm)
        rm_row.addWidget(btn_clear_recent)
        rm_row.addStretch(1)
        fav_card = card(make_label("Favourite languages", name="h2"),
                        make_label("Favourites are listed first in the language picker. You can also star languages directly in the panel.", "hint"))
        fav_card.layout().addWidget(self.fav_list)
        fav_card.layout().addLayout(add_row)
        fav_card.layout().addLayout(rm_row)

        # ---- tones
        self.ed_tone = QLineEdit()
        self.ed_tone.setMaxLength(MAX_CUSTOM_TONE_LENGTH)
        self.ed_tone.setPlaceholderText("e.g. friendly but firm, pirate, Shakespearean…")
        self.ed_tone.returnPressed.connect(self._add_custom_tone)
        btn_tone = QPushButton("Add custom tone")
        btn_tone.clicked.connect(self._add_custom_tone)
        self.tone_msg = make_label("", "hint")
        tone_row = QHBoxLayout()
        tone_row.addWidget(self.ed_tone, 1)
        tone_row.addWidget(btn_tone)
        self.tone_fav_list = QListWidget()
        self.tone_fav_list.setFixedHeight(110)
        btn_tone_rm = QPushButton("Remove selected tone")
        btn_tone_rm.clicked.connect(self._remove_tone_favorite)
        btn_tone_clear = QPushButton("Clear recent tones")
        btn_tone_clear.clicked.connect(self._clear_recent_tones)
        tone_rm_row = QHBoxLayout()
        tone_rm_row.addWidget(btn_tone_rm)
        tone_rm_row.addWidget(btn_tone_clear)
        tone_rm_row.addStretch(1)
        tone_card = card(make_label("Tones", name="h2"),
                         make_label("Built-in tones: " + ", ".join(t.name for t in TONES) + ". In the panel you can also type any tone "
                                    "into the tone search. Describe how the text should sound; it is saved to your favourite tones and "
                                    "becomes the default tone.", "hint"),
                         make_label("Custom tone", "label"))
        tone_card.layout().addLayout(tone_row)
        tone_card.layout().addWidget(self.tone_msg)
        tone_card.layout().addWidget(make_label("Favourite tones (including your own)", "label"))
        tone_card.layout().addWidget(self.tone_fav_list)
        tone_card.layout().addLayout(tone_rm_row)

        lay.addWidget(card(holder, tone_holder))
        lay.addWidget(fav_card)
        lay.addWidget(tone_card)
        lay.addStretch(1)
        return area

    @staticmethod
    def _select_data(cb: QComboBox, code: str, label: str) -> None:
        """Selects ``code`` in a combo box, adding a one-off entry for custom values."""
        cb.blockSignals(True)
        i = cb.findData(code)
        if i < 0:
            cb.addItem(label, code)
            i = cb.count() - 1
        cb.setCurrentIndex(i)
        cb.blockSignals(False)

    def _load_languages(self) -> None:
        p = self.store.settings.prefs
        self._select_data(self.cb_src, p.source_lang, language_name(p.source_lang))
        self._select_data(self.cb_dst, p.target_lang, language_name(p.target_lang))
        self._select_data(self.cb_tone, p.tone, "Custom: " + tone_name(p.tone))
        self._refresh_favorites()

    def _refresh_favorites(self) -> None:
        p = self.store.settings.prefs
        self.fav_list.clear()
        for code in p.favorites:
            it = QListWidgetItem(language_name(code))
            it.setData(Qt.ItemDataRole.UserRole, code)
            self.fav_list.addItem(it)
        self.tone_fav_list.clear()
        for code in p.tone_favorites:
            it = QListWidgetItem(tone_name(code) + ("   (custom)" if is_custom_tone(code) else ""))
            it.setData(Qt.ItemDataRole.UserRole, code)
            self.tone_fav_list.addItem(it)

    def _save_pref(self, name: str, value) -> None:
        setattr(self.store.settings.prefs, name, value)
        self.ctrl.apply_settings()

    def _add_favorite(self) -> None:
        code = self.cb_fav_add.currentData()
        favs = self.store.settings.prefs.favorites
        if code and code not in favs:
            favs.append(code)
            self.store.settings.prefs.favorites = favs[-30:]
            self.ctrl.apply_settings()
            self._refresh_favorites()

    def _remove_favorite(self) -> None:
        it = self.fav_list.currentItem()
        if it:
            code = it.data(Qt.ItemDataRole.UserRole)
            self.store.settings.prefs.favorites = [c for c in self.store.settings.prefs.favorites if c != code]
            self.ctrl.apply_settings()
            self._refresh_favorites()

    def _clear_recent(self) -> None:
        self.store.settings.prefs.recent = []
        self.ctrl.apply_settings()

    def _add_custom_tone(self) -> None:
        text = self.ed_tone.text().strip()
        if not text:
            self.tone_msg.setText("Describe the tone first.")
            return
        code = make_custom_tone_code(text)
        p = self.store.settings.prefs
        p.tone_favorites = ([code] + [c for c in p.tone_favorites if c != code])[:30]
        p.tone = code
        self.ed_tone.clear()
        self.tone_msg.setText(f"Added “{tone_name(code)}” and set it as the default tone.")
        self.ctrl.apply_settings()
        self._load_languages()

    def _remove_tone_favorite(self) -> None:
        it = self.tone_fav_list.currentItem()
        if it:
            code = it.data(Qt.ItemDataRole.UserRole)
            p = self.store.settings.prefs
            p.tone_favorites = [c for c in p.tone_favorites if c != code]
            self.ctrl.apply_settings()
            self._refresh_favorites()

    def _clear_recent_tones(self) -> None:
        self.store.settings.prefs.tone_recent = []
        self.ctrl.apply_settings()

    # ===================================================================== Shortcut
    def _build_shortcut(self) -> QWidget:
        area, lay = _page("Shortcut", "Press it in any program to open the translator at your text cursor.")
        self.sc_cfg = deepcopy(self.store.settings.shortcut)
        self.row_sc_enabled = ToggleRow("Enable the global shortcut", "When off, use “Open translator” from the tray menu.", self.t)
        self.row_sc_enabled.toggled.connect(self._sc_changed)
        self.sc_label = make_label("", name="kbd", wrap=False)
        self.recorder = ShortcutRecorder()
        self.recorder.recorded.connect(self._on_recorded)
        self.recorder.recording_changed.connect(self.ctrl.hotkeys_set_suspended)
        trig = QHBoxLayout()
        trig.addWidget(self.sc_label)
        trig.addWidget(self.recorder)
        trig.addStretch(1)
        trig_w = QWidget()
        trig_w.setLayout(trig)
        trig.setContentsMargins(0, 0, 0, 0)

        self.sp_presses = _spin(1, 5, 1)
        self.sp_interval = _spin(100, 2000, 400, " ms")
        self.sp_delay = _spin(0, 1000, 0, " ms")
        for sp in (self.sp_presses, self.sp_interval, self.sp_delay):
            sp.valueChanged.connect(self._sc_changed)
        grid = QHBoxLayout()
        grid.setSpacing(14)
        grid.addWidget(field("Presses", self.sp_presses, "How many times in a row (1–5)."))
        grid.addWidget(field("Max delay between presses", self.sp_interval))
        grid.addWidget(field("Delay after last press", self.sp_delay))
        grid.addStretch(1)
        grid_w = QWidget()
        grid_w.setLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)
        self.ck_bare = QCheckBox("I understand that a plain typing key can trigger while I write normally")
        self.ck_bare.toggled.connect(self._sc_changed)
        self.sc_notes = make_label()
        set_note(self.sc_notes, None)
        self.sc_flash = make_label("✓ Trigger detected", "label")
        self.sc_flash.setStyleSheet(f"color: {self.t['ok']}; font-weight: 700;")
        self.sc_flash.hide()
        self.btn_sc_save = QPushButton("Save shortcut")
        self.btn_sc_save.setProperty("primary", True)
        self.btn_sc_save.clicked.connect(self._save_shortcut)
        self.btn_sc_reset = QPushButton("Reset to Ctrl+Shift+Y")
        self.btn_sc_reset.clicked.connect(self._reset_shortcut)
        row = QHBoxLayout()
        row.addWidget(self.btn_sc_save)
        row.addWidget(self.btn_sc_reset)
        row.addStretch(1)

        lay.addWidget(card(self.row_sc_enabled))
        lay.addWidget(card(field("Trigger", trig_w, "Click Record, then press a combination (for example Ctrl+Shift+Y), or tap a modifier on its own "
                                                    "(for example Ctrl twice by setting Presses to 2)."), grid_w, self.ck_bare))
        lay.addWidget(self.sc_notes)
        lay.addLayout(row)
        test = card(make_label("Test the trigger", name="h2"),
                    make_label("With this window in front, press your shortcut. The translator does not open while this window is active.", "hint"),
                    self.sc_flash)
        lay.addWidget(test)
        lay.addStretch(1)
        return area

    def _load_shortcut(self) -> None:
        c = self.sc_cfg
        for w in (self.row_sc_enabled.switch, self.sp_presses, self.sp_interval, self.sp_delay, self.ck_bare):
            w.blockSignals(True)
        self.row_sc_enabled.switch.setChecked(c.enabled)
        self.sp_presses.setValue(c.press_count)
        self.sp_interval.setValue(c.max_interval_ms)
        self.sp_delay.setValue(c.activation_delay_ms)
        self.ck_bare.setChecked(c.acknowledged_bare_key_risk)
        for w in (self.row_sc_enabled.switch, self.sp_presses, self.sp_interval, self.sp_delay, self.ck_bare):
            w.blockSignals(False)
        self._refresh_shortcut_view()

    def _refresh_shortcut_view(self) -> None:
        c = self.sc_cfg
        self.sc_label.setText(format_shortcut(c))
        self.recorder.set_idle_text("Record…")
        self.sp_interval.setEnabled(c.press_count > 1)
        v = validate_shortcut(c)
        self.ck_bare.setVisible(v.bare_typing_key)
        if v.errors:
            set_note(self.sc_notes, "err", "\n".join("• " + e for e in v.errors))
        elif v.warnings:
            set_note(self.sc_notes, "warn", "\n".join("• " + w for w in v.warnings))
        else:
            set_note(self.sc_notes, None)

    def _sc_changed(self, *_):
        c = self.sc_cfg
        c.enabled = self.row_sc_enabled.is_checked()
        c.press_count = self.sp_presses.value()
        c.max_interval_ms = self.sp_interval.value()
        c.activation_delay_ms = self.sp_delay.value()
        c.acknowledged_bare_key_risk = self.ck_bare.isChecked()
        self._refresh_shortcut_view()

    def _on_recorded(self, code: str, ctrl: bool, shift: bool, alt: bool, meta: bool) -> None:
        c = self.sc_cfg
        c.code, c.ctrl, c.shift, c.alt, c.meta = code, ctrl, shift, alt, meta
        if is_modifier_only(c) and c.press_count < 2:
            c.press_count = 2
            self.sp_presses.blockSignals(True)
            self.sp_presses.setValue(2)
            self.sp_presses.blockSignals(False)
        c.acknowledged_bare_key_risk = False
        self.ck_bare.blockSignals(True)
        self.ck_bare.setChecked(False)
        self.ck_bare.blockSignals(False)
        self._refresh_shortcut_view()

    def _save_shortcut(self) -> None:
        self._sc_changed()
        v = validate_shortcut(self.sc_cfg)
        if v.errors and self.sc_cfg.enabled:
            set_note(self.sc_notes, "err", "Not saved:\n" + "\n".join("• " + e for e in v.errors))
            return
        self.store.settings.shortcut = deepcopy(self.sc_cfg)
        self.ctrl.apply_settings()
        set_note(self.sc_notes, "ok", f"Saved. The shortcut is now {format_shortcut(self.sc_cfg)}.")

    def _reset_shortcut(self) -> None:
        self.sc_cfg = ShortcutConfig()
        self._load_shortcut()
        self._save_shortcut()

    def flash_trigger(self) -> None:
        self.show_page("shortcut")
        self.sc_flash.show()
        QTimer.singleShot(1600, self.sc_flash.hide)

    # ======================================================================== About
    def _build_about(self) -> QWidget:
        area, lay = _page("About & privacy", f"Inline Translator for Windows · version {__version__}")
        privacy = [
            "Nothing on your screen is read or sent until you press Enter or the arrow in the translator panel. Only the text you typed in the panel "
            "goes to the AI provider you configured.",
            "Your API key is encrypted with Windows DPAPI: it can only be decrypted by your Windows user account on this PC.",
            "The shortcut works through a keyboard listener that compares each key press with your trigger. Keystrokes are never stored, logged or sent.",
            "Pasting uses the clipboard for a moment and then restores what was there. The translation is kept out of Windows clipboard history and cloud clipboard.",
            "Programs running as administrator ignore keystrokes from normal programs (a Windows security rule). To translate inside them, start "
            "Inline Translator as administrator too.",
            "Plain-text storage for settings: " + str(config_dir() / "settings.json") + " (without the key in readable form).",
        ]
        lay.addWidget(card(*[make_label("• " + p) for p in privacy]))
        b1 = QPushButton("Open settings folder")
        b1.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir()))))
        b2 = QPushButton("Open log file")
        b2.clicked.connect(self._open_log)
        b3 = QPushButton("Restart shortcut listener")
        b3.clicked.connect(self.ctrl.restart_hotkeys)
        b4 = QPushButton("Quit Inline Translator")
        b4.clicked.connect(self.ctrl.quit)
        row = QHBoxLayout()
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b4)
        lay.addLayout(row)
        lay.addStretch(1)
        return area

    def _open_log(self) -> None:
        p = log_path()
        if not os.path.exists(p):
            open(p, "a", encoding="utf-8").close()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
