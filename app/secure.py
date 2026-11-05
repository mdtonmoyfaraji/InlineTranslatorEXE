"""Protects the API key with Windows DPAPI (bound to the current Windows user).

The encrypted blob is useless on another account or another PC. On other
platforms (tests / development) the functions return ``None`` and the caller
falls back to plain storage.
"""
from __future__ import annotations

import base64
import sys

IS_WINDOWS = sys.platform == "win32"


def _blob_to_bytes(blob) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    return ctypes.string_at(blob.pbData, blob.cbData)


def protect(text: str) -> str | None:
    """Returns a base64 string, or None if DPAPI is not available."""
    if not IS_WINDOWS or not text:
        return None
    try:  # pragma: no cover - Windows only
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        data = text.encode("utf-8")
        buf = ctypes.create_string_buffer(data, len(data))
        src = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = DATA_BLOB()
        ok = crypt32.CryptProtectData(ctypes.byref(src), "InlineTranslator", None, None, None, 0, ctypes.byref(out))
        if not ok:
            return None
        try:
            return base64.b64encode(_blob_to_bytes(out)).decode("ascii")
        finally:
            kernel32.LocalFree(out.pbData)
    except Exception:
        return None


def unprotect(token: str) -> str | None:
    """Returns the original text, or None if it cannot be decrypted."""
    if not IS_WINDOWS or not token:
        return None
    try:  # pragma: no cover - Windows only
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        raw = base64.b64decode(token)
        buf = ctypes.create_string_buffer(raw, len(raw))
        src = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = DATA_BLOB()
        ok = crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out))
        if not ok:
            return None
        try:
            return _blob_to_bytes(out).decode("utf-8")
        finally:
            kernel32.LocalFree(out.pbData)
    except Exception:
        return None
