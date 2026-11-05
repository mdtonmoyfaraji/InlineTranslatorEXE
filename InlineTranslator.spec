# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller InlineTranslator.spec --noconfirm
# Result:      dist/InlineTranslator.exe  (single file, no console window)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/icon.png", "assets"), ("assets/icon.ico", "assets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Things the app never uses: keeps the exe smaller and faster to start.
    excludes=[
        "tkinter",
        "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtSvg", "PySide6.QtOpenGL",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtBluetooth", "PySide6.QtSensors",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="InlineTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX-packed exes are flagged by antivirus far more often
    runtime_tmpdir=None,
    console=False,        # windowed app: no black console window
    icon="assets/icon.ico",
    version="version_info.txt",
)
