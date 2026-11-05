"""Inline Translator for Windows - entry point."""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Must be set before Qt starts: keep Qt's own scaling, but never let it round fractional DPI badly.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--background", action="store_true", help="start hidden in the tray")
    args, _unknown = parser.parse_known_args()

    from app import winapi
    from app.logging_setup import setup_logging

    setup_logging()
    log = logging.getLogger("inline_translator")

    single = winapi.SingleInstance()
    if not single.is_primary:
        single.signal_primary()  # ask the running instance to show its window
        return 0

    if winapi.IS_WINDOWS:
        try:  # proper taskbar / notification identity
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("InlineTranslator.Desktop")
        except Exception:
            pass

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from app.controller import Controller
    from app.settings import SettingsStore

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("Inline Translator")
    qapp.setOrganizationName("InlineTranslator")
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setStyle("Fusion")
    icon = QIcon(resource_path(os.path.join("assets", "icon.png")))
    qapp.setWindowIcon(icon)

    store = SettingsStore()
    controller = Controller(qapp, store, single, icon, background=args.background)
    controller.start()
    log.info("Inline Translator started (background=%s)", args.background)
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
