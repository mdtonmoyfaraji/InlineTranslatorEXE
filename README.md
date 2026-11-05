# Inline Translator for Windows

Press a shortcut in **any** program, type text in the small panel at your cursor, press **Enter**, and the
translation is inserted right where you were typing. Same panel, languages and AI connection as the browser
extension, but it works everywhere on your PC and lives in the system tray.

## Get the .exe (GitHub Actions)

1. Upload **everything in this folder** to the root of your GitHub repository
   (keep the hidden `.github` folder: in File Explorer enable *View → Show → Hidden items* before dragging).
2. Open the repo → **Actions** tab → **Build Windows EXE**. It starts by itself after the upload
   (or click *Run workflow*). It takes about 3–5 minutes.
3. Open the finished run → **Artifacts** → download **InlineTranslator-windows** → unzip → `InlineTranslator.exe`.
4. Optional: push a tag such as `v1.0.1` and the exe is also attached to a GitHub Release.

## First start

1. Run `InlineTranslator.exe`. The settings window opens (later launches go straight to the tray).
2. **AI connection** → pick a provider preset (or type the URL), enter the model name and API key → *Save*.
3. Click in any text field, press **Ctrl+Shift+Y**, type, press **Enter**.

Windows SmartScreen / antivirus may warn because the file is new and unsigned and uses a global keyboard
listener (needed for the shortcut). Choose *More info → Run anyway*; if Defender quarantines it, restore it and
add an exclusion for the file. You built it yourself from your own repository.

## Features

- Global shortcut: any combo, 1–5 presses, or a modifier double-tap (e.g. Ctrl ×2). Recorder + validation in Settings.
- Panel opens at the text cursor (falls back to the mouse), auto-growing box, RTL languages, IME typing.
- 100+ languages, auto-detect, swap, favourites (★), recent languages, any custom language name.
- Inserts by paste (your clipboard is restored) or by typing; if that fails the result stays in the panel with Copy.
- Tray icon, start with Windows, light/dark theme, single instance, rotating log file.
- API key encrypted with Windows DPAPI; HTTP keep-alive and a pre-warmed connection for fast replies; system or custom proxy.

## Good to know

- Programs running **as administrator** ignore input from normal programs (Windows rule). Run Inline Translator as
  administrator too if you need it there.
- Apps that do not expose a text caret (many browsers/Electron apps) open the panel at the mouse pointer instead.
- Settings live in `%APPDATA%\InlineTranslator\settings.json`, log in `app.log` next to it.

## Project layout (for future improvements)

```
main.py                    entry point
app/shortcut.py            key names, sequence detector, validation   (pure logic, tested)
app/ai.py                  OpenAI-compatible client, keep-alive, proxy (pure logic, tested)
app/settings.py            settings model + JSON store                (pure logic, tested)
app/languages.py           language list + search
app/winapi.py              all Win32 / ctypes code
app/hotkeys.py             global keyboard hook thread
app/inserter.py            focus restore + paste/type
app/panel.py               floating translator panel
app/settings_window.py     settings UI
app/controller.py          tray, wiring, translate flow
tests/                     python -m unittest discover -s tests
InlineTranslator.spec      PyInstaller build
.github/workflows/build.yml
```

Run from source: `pip install -r requirements.txt` then `python main.py`.

Ideas for later: pre-fill with the selected text, streaming results, per-app rules, history, signed builds.
