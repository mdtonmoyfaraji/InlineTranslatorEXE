"""Shortcut model, sequence detection and validation (no Windows / Qt imports).

Keys are identified by browser-style "codes" (``KeyY``, ``ControlLeft``, ``F9`` ...)
so the settings file stays readable. ``vk_to_code`` converts Windows virtual-key
codes to those names.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

# --------------------------------------------------------------------------- keys

MODIFIER_FAMILIES = {
    "ControlLeft": "Control", "ControlRight": "Control", "Control": "Control",
    "ShiftLeft": "Shift", "ShiftRight": "Shift", "Shift": "Shift",
    "AltLeft": "Alt", "AltRight": "Alt", "Alt": "Alt",
    "MetaLeft": "Meta", "MetaRight": "Meta", "Meta": "Meta",
}


def modifier_family(code: str) -> str | None:
    return MODIFIER_FAMILIES.get(code)


_SPECIAL_VK = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "CapsLock",
    0x1B: "Escape", 0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End",
    0x24: "Home", 0x25: "ArrowLeft", 0x26: "ArrowUp", 0x27: "ArrowRight", 0x28: "ArrowDown",
    0x2C: "PrintScreen", 0x2D: "Insert", 0x2E: "Delete", 0x5D: "ContextMenu",
    0x6A: "NumpadMultiply", 0x6B: "NumpadAdd", 0x6D: "NumpadSubtract",
    0x6E: "NumpadDecimal", 0x6F: "NumpadDivide", 0x90: "NumLock", 0x91: "ScrollLock",
    0xBA: "Semicolon", 0xBB: "Equal", 0xBC: "Comma", 0xBD: "Minus", 0xBE: "Period",
    0xBF: "Slash", 0xC0: "Backquote", 0xDB: "BracketLeft", 0xDC: "Backslash",
    0xDD: "BracketRight", 0xDE: "Quote",
    # modifiers (low-level hooks report the left/right variants)
    0x10: "Shift", 0x11: "Control", 0x12: "Alt",
    0xA0: "ShiftLeft", 0xA1: "ShiftRight", 0xA2: "ControlLeft", 0xA3: "ControlRight",
    0xA4: "AltLeft", 0xA5: "AltRight", 0x5B: "MetaLeft", 0x5C: "MetaRight",
}


def vk_to_code(vk: int) -> str:
    if vk in _SPECIAL_VK:
        return _SPECIAL_VK[vk]
    if 0x41 <= vk <= 0x5A:
        return "Key" + chr(vk)
    if 0x30 <= vk <= 0x39:
        return "Digit" + chr(vk)
    if 0x60 <= vk <= 0x69:
        return "Numpad" + str(vk - 0x60)
    if 0x70 <= vk <= 0x87:
        return "F" + str(vk - 0x70 + 1)
    return f"VK{vk:02X}"


# Keys that produce a character when pressed alone (used to decide whether a
# plain-key trigger such as "jj" left typed characters behind that must be erased).
def types_a_character(code: str) -> bool:
    return (
        code.startswith("Key") or code.startswith("Digit") or code == "Space"
        or code in {"Semicolon", "Equal", "Comma", "Minus", "Period", "Slash", "Backquote",
                    "BracketLeft", "Backslash", "BracketRight", "Quote"}
    )


_CODE_LABELS = {
    "Space": "Space", "Enter": "Enter", "Tab": "Tab", "Backspace": "Backspace", "Escape": "Esc",
    "Delete": "Del", "ArrowUp": "↑", "ArrowDown": "↓", "ArrowLeft": "←", "ArrowRight": "→",
    "Minus": "-", "Equal": "=", "Comma": ",", "Period": ".", "Slash": "/", "Backslash": "\\",
    "Semicolon": ";", "Quote": "'", "BracketLeft": "[", "BracketRight": "]", "Backquote": "`",
}


def code_label(code: str) -> str:
    if code in _CODE_LABELS:
        return _CODE_LABELS[code]
    if code.startswith("Key"):
        return code[3:]
    if code.startswith("Digit"):
        return code[5:]
    if code.startswith("Numpad"):
        return "Num " + code[6:]
    return code


# ------------------------------------------------------------------------- config

@dataclass
class ShortcutConfig:
    enabled: bool = True
    code: str = "KeyY"
    ctrl: bool = True
    shift: bool = True
    alt: bool = False
    meta: bool = False
    press_count: int = 1
    max_interval_ms: int = 400
    activation_delay_ms: int = 0
    acknowledged_bare_key_risk: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Any, base: "ShortcutConfig | None" = None) -> "ShortcutConfig":
        base = base or ShortcutConfig()
        d = data if isinstance(data, dict) else {}
        out = {}
        for f in fields(ShortcutConfig):
            default = getattr(base, f.name)
            v = d.get(f.name, default)
            if isinstance(default, bool):
                out[f.name] = v if isinstance(v, bool) else default
            elif isinstance(default, int):
                out[f.name] = _clamp(v, _LIMITS[f.name][0], _LIMITS[f.name][1], default)
            else:
                out[f.name] = v if isinstance(v, str) and 0 < len(v) <= 32 else default
        return ShortcutConfig(**out)


_LIMITS = {"press_count": (1, 5), "max_interval_ms": (100, 2000), "activation_delay_ms": (0, 1000)}


def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        n = default
    else:
        n = int(round(v))
    return max(lo, min(hi, n))


def is_modifier_only(cfg: ShortcutConfig) -> bool:
    return modifier_family(cfg.code) is not None


# ----------------------------------------------------------------------- detector

@dataclass
class KeyInfo:
    code: str
    ctrl: bool = False
    shift: bool = False
    alt: bool = False
    meta: bool = False
    repeat: bool = False


class SequenceDetector:
    """Counts consecutive presses of the configured key/combo.

    * Any other (non-modifier) key resets the count.
    * Pressing only a modifier between presses does not reset it.
    * Held keys (auto-repeat) never count.
    * Modifier-only triggers (e.g. Ctrl, Ctrl) count clean taps only: the
      modifier must be pressed and released without any other key in between.
    """

    def __init__(self, cfg: ShortcutConfig):
        self.cfg = cfg
        self.reset()

    def set_config(self, cfg: ShortcutConfig) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.count = 0
        self.last = float("-inf")
        self.mod_down = False
        self.mod_clean = False

    def _register(self, now_ms: float) -> str:
        if now_ms - self.last > self.cfg.max_interval_ms:
            self.count = 0
        self.count += 1
        self.last = now_ms
        if self.count >= self.cfg.press_count:
            self.count = 0
            self.last = float("-inf")
            return "completed"
        return "progress"

    def on_key_down(self, k: KeyInfo, now_ms: float) -> str:
        if not self.cfg.enabled:
            return "ignored"
        fam = modifier_family(k.code)
        if is_modifier_only(self.cfg):
            if fam == self.cfg.code:
                if k.repeat:
                    self.mod_clean = False
                    return "ignored"
                others = ((k.ctrl and fam != "Control") or (k.shift and fam != "Shift")
                          or (k.alt and fam != "Alt") or (k.meta and fam != "Meta"))
                self.mod_down = True
                self.mod_clean = not others
                return "ignored"
            # any other key breaks the tap and the sequence
            self.mod_clean = False
            self.count = 0
            self.last = float("-inf")
            return "reset"
        if fam is not None:
            return "ignored"  # bare modifier presses do not break combos
        c = self.cfg
        matches = (k.code == c.code and k.ctrl == c.ctrl and k.shift == c.shift
                   and k.alt == c.alt and k.meta == c.meta)
        if not matches:
            self.count = 0
            self.last = float("-inf")
            return "reset"
        if k.repeat:
            return "ignored"
        return self._register(now_ms)

    def on_key_up(self, k: KeyInfo, now_ms: float) -> str:
        if not self.cfg.enabled or not is_modifier_only(self.cfg):
            return "ignored"
        if modifier_family(k.code) != self.cfg.code:
            return "ignored"
        clean = self.mod_down and self.mod_clean
        self.mod_down = False
        self.mod_clean = False
        if not clean:
            return "ignored"
        return self._register(now_ms)


# --------------------------------------------------------------------- validation

_RESERVED_BARE = {
    "Tab", "Escape", "Enter", "Backspace", "Delete", "Insert", "Home", "End", "PageUp", "PageDown",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "CapsLock", "NumLock", "ScrollLock",
    "ContextMenu", "PrintScreen", "Pause", "F1", "F3", "F5", "F6", "F7", "F10", "F11", "F12",
}
# Ctrl+<key> combinations every application relies on.
_RESERVED_CTRL = {
    "KeyA", "KeyC", "KeyV", "KeyX", "KeyZ", "KeyY", "KeyT", "KeyN", "KeyW", "KeyR", "KeyF",
    "KeyL", "KeyP", "KeyS", "KeyD", "KeyH", "KeyK", "KeyU", "KeyO", "KeyE", "KeyG", "KeyB",
    "KeyI", "KeyM", "Tab", "Space", "Backspace", "Delete", "Home", "End",
    "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown",
}


def format_shortcut(cfg: ShortcutConfig) -> str:
    fam = modifier_family(cfg.code)
    names = {"Control": "Ctrl", "Shift": "Shift", "Alt": "Alt", "Meta": "Win"}
    if fam:
        base = names[fam]
    else:
        parts = []
        if cfg.ctrl:
            parts.append("Ctrl")
        if cfg.alt:
            parts.append("Alt")
        if cfg.shift:
            parts.append("Shift")
        if cfg.meta:
            parts.append("Win")
        parts.append(code_label(cfg.code))
        base = "+".join(parts)
    return f"{base} × {cfg.press_count}" if cfg.press_count > 1 else base


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bare_typing_key: bool = False


def validate_shortcut(cfg: ShortcutConfig) -> Validation:
    v = Validation()
    if not cfg.code:
        v.errors.append("Choose a trigger key.")
        return v
    if not 1 <= cfg.press_count <= 5:
        v.errors.append("Number of presses must be between 1 and 5.")
    if cfg.press_count > 1 and not 100 <= cfg.max_interval_ms <= 2000:
        v.errors.append("The maximum delay between presses must be between 100 and 2000 ms.")
    if not 0 <= cfg.activation_delay_ms <= 1000:
        v.errors.append("The delay after the last press must be between 0 and 1000 ms.")

    fam = modifier_family(cfg.code)
    if fam:
        if cfg.press_count < 2:
            v.errors.append(f"Tapping {fam} once would trigger constantly. Use at least 2 presses for a modifier-only trigger.")
        if fam == "Meta":
            v.errors.append("The Windows key alone is reserved by the operating system.")
        if fam == "Shift" and cfg.press_count >= 5:
            v.errors.append("Pressing Shift five times turns on Sticky Keys in Windows.")
        if fam == "Alt":
            v.warnings.append("Tapping Alt focuses the menu bar in many programs. It may conflict.")
        if fam == "Control":
            v.warnings.append("Double-tapping Ctrl can conflict with other tools (remote desktop, IME or clipboard managers).")
        return v

    has_action = cfg.ctrl or cfg.alt or cfg.meta
    if not has_action and not cfg.shift and cfg.code in _RESERVED_BARE:
        v.errors.append(f"“{code_label(cfg.code)}” is a navigation/editing key used by almost every program.")
    if cfg.meta:
        v.errors.append("Windows-key shortcuts are reserved by the operating system.")
    if cfg.alt and not cfg.ctrl and cfg.code in {"Tab", "F4", "Space", "ArrowLeft", "ArrowRight"}:
        v.errors.append("This Alt combination is reserved by Windows.")
    if cfg.ctrl and cfg.alt and cfg.code == "Delete":
        v.errors.append("Ctrl+Alt+Delete is reserved by Windows.")
    if cfg.ctrl and cfg.shift and cfg.code in {"Escape"}:
        v.errors.append("Ctrl+Shift+Esc opens the Task Manager.")
    if cfg.ctrl and not cfg.alt and not cfg.shift and cfg.code in _RESERVED_CTRL:
        v.errors.append(f"{format_shortcut(cfg)} is a standard editing shortcut used by almost every program.")

    if not has_action and not cfg.shift and cfg.code not in _RESERVED_BARE:
        v.bare_typing_key = True
        if cfg.press_count < 2:
            v.errors.append("A single press of an unmodified key would trigger whenever you type it. Use at least 2 presses or add a modifier (Ctrl/Alt).")
        elif cfg.press_count == 2:
            v.warnings.append("Pressing this key twice in a row happens while typing normally (double letters). A modifier combination is safer; 3 presses is the minimum recommended for a plain key.")
        if not cfg.acknowledged_bare_key_risk:
            v.errors.append("Confirm the warning about using a plain typing key before enabling it.")
    elif cfg.shift and not has_action and types_a_character(cfg.code):
        v.errors.append("Shift + a typing key is used for capital letters. Add Ctrl or Alt.")

    if cfg.alt and not cfg.ctrl:
        v.warnings.append("Alt+key can open menus in some programs.")
    if cfg.ctrl and cfg.alt:
        v.warnings.append("Ctrl+Alt is the same as AltGr on many keyboard layouts and can interfere with typing special characters.")
    return v
