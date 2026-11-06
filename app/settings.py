"""Settings model and persistent store (no Qt imports)."""
from __future__ import annotations

import json
import locale as _locale
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import secure
from .languages import AUTO, NONE, default_target_for_locale, is_valid_language_code, is_valid_target_code
from .shortcut import ShortcutConfig
from .tones import TONE_DEFAULT, is_valid_tone_code

log = logging.getLogger("inline_translator.settings")

APP_NAME = "InlineTranslator"
SCHEMA_VERSION = 1


def config_dir() -> Path:
    override = os.environ.get("INLINE_TRANSLATOR_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


THEMES = ("system", "light", "dark")
INSERT_METHODS = ("paste", "type")
PANEL_POSITIONS = ("caret", "mouse", "center")
PROXY_MODES = ("system", "none", "custom")


def _choice(v: Any, allowed: tuple[str, ...], default: str) -> str:
    return v if isinstance(v, str) and v in allowed else default


def _bool(v: Any, default: bool) -> bool:
    return v if isinstance(v, bool) else default


def _code_list(v: Any, maximum: int) -> list[str]:
    out: list[str] = []
    if isinstance(v, list):
        for c in v:
            if is_valid_language_code(c) and c != AUTO and c not in out:
                out.append(c)
    return out[:maximum]


def _tone_list(v: Any, maximum: int) -> list[str]:
    out: list[str] = []
    if isinstance(v, list):
        for c in v:
            if is_valid_tone_code(c) and c != TONE_DEFAULT and c not in out:
                out.append(c)
    return out[:maximum]


@dataclass
class ApiConfig:
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    proxy_mode: str = "system"
    proxy_url: str = ""
    timeout_s: int = 60

    @property
    def is_complete(self) -> bool:
        return bool(self.base_url.strip()) and bool(self.model.strip())


@dataclass
class Prefs:
    source_lang: str = AUTO
    target_lang: str = "en"
    recent: list[str] = field(default_factory=list)
    favorites: list[str] = field(default_factory=list)
    tone: str = TONE_DEFAULT
    tone_recent: list[str] = field(default_factory=list)
    tone_favorites: list[str] = field(default_factory=list)
    theme: str = "system"


@dataclass
class AppOptions:
    start_with_windows: bool = False
    insert_method: str = "paste"
    restore_clipboard: bool = True
    panel_position: str = "caret"
    notifications: bool = True
    prefill_selection: bool = True
    selection_bubble: bool = True
    copy_fallback: bool = True


@dataclass
class Settings:
    api: ApiConfig = field(default_factory=ApiConfig)
    prefs: Prefs = field(default_factory=Prefs)
    shortcut: ShortcutConfig = field(default_factory=ShortcutConfig)
    app: AppOptions = field(default_factory=AppOptions)


def _system_locale() -> str:
    """BCP-47 name of the Windows user locale (e.g. "bn-BD"); falls back to "en"."""
    if sys.platform == "win32":
        try:  # pragma: no cover - Windows only
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                return buf.value or "en"
        except Exception:
            pass
    try:
        return (_locale.getlocale()[0] or os.environ.get("LANG", "en") or "en")
    except Exception:
        return "en"


def default_settings() -> Settings:
    s = Settings()
    s.prefs.target_lang = default_target_for_locale(_system_locale())
    return s


def sanitize(data: Any, base: Settings | None = None) -> Settings:
    """Builds a valid Settings object from untrusted JSON data."""
    base = base or default_settings()
    d = data if isinstance(data, dict) else {}

    a = d.get("api") if isinstance(d.get("api"), dict) else {}
    api = ApiConfig(
        base_url=str(a.get("base_url", base.api.base_url))[:500].strip(),
        model=str(a.get("model", base.api.model))[:200].strip(),
        api_key=str(a.get("api_key", base.api.api_key))[:2000].strip(),
        proxy_mode=_choice(a.get("proxy_mode"), PROXY_MODES, base.api.proxy_mode),
        proxy_url=str(a.get("proxy_url", base.api.proxy_url))[:500].strip(),
        timeout_s=max(5, min(300, int(a["timeout_s"]))) if isinstance(a.get("timeout_s"), (int, float)) and not isinstance(a.get("timeout_s"), bool) else base.api.timeout_s,
    )

    p = d.get("prefs") if isinstance(d.get("prefs"), dict) else {}
    src = p.get("source_lang")
    tgt = p.get("target_lang")
    prefs = Prefs(
        source_lang=src if is_valid_language_code(src) else base.prefs.source_lang,
        target_lang=tgt if is_valid_target_code(tgt) else base.prefs.target_lang,
        recent=_code_list(p["recent"], 8) if "recent" in p else list(base.prefs.recent),
        favorites=_code_list(p["favorites"], 30) if "favorites" in p else list(base.prefs.favorites),
        tone=p.get("tone") if is_valid_tone_code(p.get("tone")) else base.prefs.tone,
        tone_recent=_tone_list(p["tone_recent"], 8) if "tone_recent" in p else list(base.prefs.tone_recent),
        tone_favorites=_tone_list(p["tone_favorites"], 30) if "tone_favorites" in p else list(base.prefs.tone_favorites),
        theme=_choice(p.get("theme"), THEMES, base.prefs.theme),
    )

    o = d.get("app") if isinstance(d.get("app"), dict) else {}
    app = AppOptions(
        start_with_windows=_bool(o.get("start_with_windows"), base.app.start_with_windows),
        insert_method=_choice(o.get("insert_method"), INSERT_METHODS, base.app.insert_method),
        restore_clipboard=_bool(o.get("restore_clipboard"), base.app.restore_clipboard),
        panel_position=_choice(o.get("panel_position"), PANEL_POSITIONS, base.app.panel_position),
        notifications=_bool(o.get("notifications"), base.app.notifications),
        prefill_selection=_bool(o.get("prefill_selection"), base.app.prefill_selection),
        selection_bubble=_bool(o.get("selection_bubble"), base.app.selection_bubble),
        copy_fallback=_bool(o.get("copy_fallback"), base.app.copy_fallback),
    )
    shortcut = ShortcutConfig.from_dict(d.get("shortcut"), base.shortcut)
    return Settings(api=api, prefs=prefs, shortcut=shortcut, app=app)


class SettingsStore:
    """Loads and saves settings.json atomically. Listeners are called after every save."""

    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "settings.json")
        self.settings = default_settings()
        self._listeners: list[Callable[[Settings], None]] = []
        self.load()

    # ---- persistence -------------------------------------------------------
    def load(self) -> Settings:
        data: Any = None
        first_run = not self.path.exists()
        if not first_run:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                log.exception("settings.json is unreadable; keeping a backup and starting fresh")
                try:
                    self.path.replace(self.path.with_suffix(".broken.json"))
                except OSError:
                    pass
        self.first_run = first_run
        s = sanitize(data)
        # secrets
        if isinstance(data, dict) and isinstance(data.get("api"), dict):
            api = data["api"]
            token = api.get("api_key_dpapi")
            if isinstance(token, str) and token:
                s.api.api_key = (secure.unprotect(token) or "").strip()
            elif isinstance(api.get("api_key"), str):
                s.api.api_key = api["api_key"].strip()
        self.settings = s
        return s

    def _to_json(self) -> dict[str, Any]:
        s = self.settings
        api: dict[str, Any] = {
            "base_url": s.api.base_url, "model": s.api.model,
            "proxy_mode": s.api.proxy_mode, "proxy_url": s.api.proxy_url, "timeout_s": s.api.timeout_s,
        }
        if s.api.api_key:
            token = secure.protect(s.api.api_key)
            if token:
                api["api_key_dpapi"] = token
            else:
                api["api_key"] = s.api.api_key  # DPAPI unavailable (non-Windows / failure)
        return {
            "version": SCHEMA_VERSION,
            "api": api,
            "prefs": {
                "source_lang": s.prefs.source_lang, "target_lang": s.prefs.target_lang,
                "recent": s.prefs.recent, "favorites": s.prefs.favorites, "tone": s.prefs.tone,
                "tone_recent": s.prefs.tone_recent, "tone_favorites": s.prefs.tone_favorites,
                "theme": s.prefs.theme,
            },
            "shortcut": s.shortcut.to_dict(),
            "app": {
                "start_with_windows": s.app.start_with_windows, "insert_method": s.app.insert_method,
                "restore_clipboard": s.app.restore_clipboard, "panel_position": s.app.panel_position,
                "notifications": s.app.notifications, "prefill_selection": s.app.prefill_selection,
                "selection_bubble": s.app.selection_bubble, "copy_fallback": s.app.copy_fallback,
            },
        }

    def save(self, notify: bool = True) -> None:
        payload = json.dumps(self._to_json(), ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        if notify:
            for cb in list(self._listeners):
                try:
                    cb(self.settings)
                except Exception:
                    log.exception("settings listener failed")

    # ---- helpers -----------------------------------------------------------
    def subscribe(self, cb: Callable[[Settings], None]) -> None:
        self._listeners.append(cb)

    def push_recent(self, source: str, target: str, tone: str = TONE_DEFAULT) -> None:
        """Remembers the languages / tone that were just used (tone-only runs do not touch languages)."""
        def push(lst: list[str], code: str) -> list[str]:
            return ([code] + [c for c in lst if c != code])[:8]

        prefs = self.settings.prefs
        if target != NONE:
            recent = prefs.recent
            if source != AUTO:
                recent = push(recent, source)
            prefs.recent = push(recent, target)
        if tone != TONE_DEFAULT:
            prefs.tone_recent = push(prefs.tone_recent, tone)
        self.save(notify=False)
