# Language Helper - Copilot Instructions

## Project Overview
A Windows + macOS system tray application that monitors clipboard text selections and shows a floating translation tooltip near the cursor. Languages are configured via `config.json`.

## Architecture
- `main.py` — Entry point, launches tray + clipboard monitor
- `src/config.py` — Config loader (reads `config.json`)
- `src/translator.py` — Translation logic using Google Translate public endpoint (urllib)
- `src/clipboard_monitor.py` — Global toggle: hotkey flips watch mode on/off; pynput mouse listener detects text selection and auto-translates on mouse release
- `src/tooltip.py` — Tkinter floating overlay window shown near cursor
- `src/tray.py` — System tray icon via `pystray`; green when active, purple when inactive

## Tech Stack
- Python 3.10+
- `urllib.request` (stdlib) for translation via Google Translate's public endpoint — no API key needed
- `pyperclip` for clipboard access
- `pystray` + `Pillow` for system tray icon
- `tkinter` for floating tooltip UI (built-in)
- `keyboard` for global hotkey support on Windows (configurable)
- `pynput` for global mouse listener (left-button release triggers translation)
- No platform-specific cursor dependency (cursor position via `pynput`)

## Config
Edit `config.json` to change:
- `source_language`: language code of selected text (e.g. `"auto"`, `"en"`, `"fr"`)
- `target_languages`: list of 1–2 language codes to translate into (e.g. `["fr", "es"]`)
- `hotkey`: global hotkey to trigger translation (e.g. `"ctrl+shift+t"`)
- `tooltip_duration_ms`: how long the tooltip stays visible

## Development Notes
- Run `pip install -r requirements.txt` before starting
- Windows + macOS
- The app runs as a background system tray process
