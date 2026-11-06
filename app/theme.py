"""Colour tokens and Qt style sheets (light + dark), matching the browser extension's look."""
from __future__ import annotations

LIGHT = {
    "bg": "#fbfaf8", "fg": "#1d2024", "muted": "#686d76", "line": "#e2e0db", "field": "#ffffff",
    "hover": "#f0eee9", "accent": "#0b6b5e", "accent_fg": "#ffffff", "accent_hover": "#0e8070",
    "danger": "#b42318", "danger_bg": "#fdecea", "warn": "#8a5a00", "warn_bg": "#fff4d6",
    "ok": "#11772f", "ok_bg": "#e5f5ea", "side": "#f3f1ec", "star": "#d99a00",
}
DARK = {
    "bg": "#1f2125", "fg": "#ecebe8", "muted": "#9aa0a9", "line": "#34373d", "field": "#17191c",
    "hover": "#2b2e33", "accent": "#3fc3ae", "accent_fg": "#0b1f1b", "accent_hover": "#5fd3c0",
    "danger": "#ff8a80", "danger_bg": "#3a1f1d", "warn": "#f3c969", "warn_bg": "#3a3017",
    "ok": "#6fd58b", "ok_bg": "#173223", "side": "#1a1c20", "star": "#e8b339",
}

FONT = '"Segoe UI Variable Text", "Segoe UI", "Nirmala UI", "Noto Sans", sans-serif'


def tokens(dark: bool) -> dict[str, str]:
    return DARK if dark else LIGHT


def app_qss(t: dict[str, str]) -> str:
    """Style sheet for the settings window, dialogs and menus."""
    return f"""
* {{ font-family: {FONT}; font-size: 13px; }}
QWidget {{ color: {t['fg']}; }}
QWidget#root, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t['bg']}; }}
QToolTip {{ color: {t['fg']}; background: {t['field']}; border: 1px solid {t['line']}; padding: 4px 6px; }}

QListWidget#nav {{ background: {t['side']}; border: 0; border-right: 1px solid {t['line']}; padding: 10px 8px; outline: 0; }}
QListWidget#nav::item {{ padding: 9px 12px; border-radius: 8px; margin: 1px 0; }}
QListWidget#nav::item:hover {{ background: {t['hover']}; }}
QListWidget#nav::item:selected {{ background: {t['accent']}; color: {t['accent_fg']}; }}

QLabel#h1 {{ font-size: 20px; font-weight: 700; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {t['muted']}; }}
QLabel[role="hint"] {{ color: {t['muted']}; font-size: 12px; }}
QLabel[role="label"] {{ font-weight: 600; }}
QLabel#kbd {{ background: {t['field']}; border: 1px solid {t['line']}; border-bottom-width: 2px; border-radius: 6px;
              padding: 2px 9px; font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; }}
QFrame#card {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: 12px; }}
QFrame#sep {{ background: {t['line']}; max-height: 1px; min-height: 1px; border: 0; }}

QLabel[note="ok"] {{ color: {t['ok']}; background: {t['ok_bg']}; border-radius: 8px; padding: 8px 10px; }}
QLabel[note="err"] {{ color: {t['danger']}; background: {t['danger_bg']}; border-radius: 8px; padding: 8px 10px; }}
QLabel[note="warn"] {{ color: {t['warn']}; background: {t['warn_bg']}; border-radius: 8px; padding: 8px 10px; }}
QLabel[note="info"] {{ color: {t['muted']}; background: {t['hover']}; border-radius: 8px; padding: 8px 10px; }}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
  background: {t['field']}; color: {t['fg']}; border: 1px solid {t['line']}; border-radius: 8px;
  padding: 6px 9px; selection-background-color: {t['accent']}; selection-color: {t['accent_fg']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox QAbstractItemView {{ background: {t['field']}; color: {t['fg']}; border: 1px solid {t['line']};
  selection-background-color: {t['hover']}; selection-color: {t['fg']}; outline: 0; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: 0; }}

QPushButton {{ background: transparent; color: {t['fg']}; border: 1px solid {t['line']}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:disabled {{ color: {t['muted']}; }}
QPushButton:focus {{ border: 1px solid {t['accent']}; }}
QPushButton[primary="true"] {{ background: {t['accent']}; color: {t['accent_fg']}; border-color: {t['accent']}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {t['accent_hover']}; }}
QPushButton[link="true"] {{ border: 0; padding: 0 2px; color: {t['accent']}; text-decoration: underline; background: transparent; }}
QPushButton[recording="true"] {{ border: 2px solid {t['accent']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['line']}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; width: 0; }}

QMenu {{ background: {t['bg']}; color: {t['fg']}; border: 1px solid {t['line']}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['hover']}; }}
QMenu::separator {{ height: 1px; background: {t['line']}; margin: 5px 6px; }}
QMessageBox {{ background: {t['bg']}; }}
"""


def panel_qss(t: dict[str, str]) -> str:
    """Style sheet for the floating translator panel."""
    return f"""
* {{ font-family: {FONT}; font-size: 13px; color: {t['fg']}; }}
QFrame#card {{ background: {t['bg']}; border: 1px solid {t['line']}; border-radius: 14px; }}
QWidget {{ background: transparent; }}

QPushButton#picker {{ border: 0; border-radius: 8px; padding: 4px 8px; font-weight: 600; text-align: left; background: transparent; }}
QPushButton#picker:hover, QPushButton#picker[open="true"] {{ background: {t['hover']}; }}
QPushButton#picker[tone="idle"] {{ font-weight: 500; color: {t['muted']}; }}
QPushButton#picker[tone="active"] {{ color: {t['accent']}; }}
QPushButton#icon {{ border: 0; border-radius: 8px; background: transparent; color: {t['muted']}; padding: 0; }}
QPushButton#icon:hover {{ background: {t['hover']}; }}
QPushButton#icon:disabled {{ color: {t['line']}; }}

QTextEdit#input {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: 10px;
  padding: 8px 44px 8px 8px; font-size: 14px; selection-background-color: {t['accent']}; selection-color: {t['accent_fg']}; }}
QTextEdit#input:focus {{ border: 1px solid {t['accent']}; }}
QPushButton#go {{ background: {t['accent']}; color: {t['accent_fg']}; border: 0; border-radius: 15px; padding: 0; }}
QPushButton#go:hover {{ background: {t['accent_hover']}; }}
QPushButton#go:disabled {{ background: {t['line']}; }}

QFrame#status {{ background: transparent; border-radius: 8px; }}
QFrame#status[error="true"] {{ background: {t['danger_bg']}; }}
QLabel#statusText {{ color: {t['muted']}; font-size: 12px; background: transparent; }}
QFrame#status[error="true"] QLabel#statusText {{ color: {t['danger']}; }}
QPushButton#statusBtn {{ border: 1px solid {t['muted']}; border-radius: 6px; padding: 1px 9px; font-size: 12px; color: {t['muted']}; background: transparent; }}
QFrame#status[error="true"] QPushButton#statusBtn {{ border-color: {t['danger']}; color: {t['danger']}; }}
QLabel#result {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: 8px; padding: 8px; }}

QFrame#pickerBox {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: 10px; }}
QLineEdit#search {{ background: {t['bg']}; border: 1px solid {t['line']}; border-radius: 8px; padding: 5px 8px; }}
QLineEdit#search:focus {{ border: 1px solid {t['accent']}; }}
QListWidget#langs {{ background: transparent; border: 0; outline: 0; }}
QListWidget#langs::item {{ padding: 0; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['line']}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; width: 0; }}
QToolTip {{ color: {t['fg']}; background: {t['field']}; border: 1px solid {t['line']}; padding: 3px 6px; }}
"""
