# Language Helper

A system-tray tool for Windows and macOS that translates selected text on-screen with a single hotkey toggle.

## How it works

The hotkey (configured via `config.json`, default is `ctrl+shift+t` if not set) acts as a **global toggle**.

- Windows/Linux: use `ctrl+...`
- macOS: use `cmd+...` (example: `cmd+shift+t`)

| Press | Effect |
|---|---|
| 1st press | **Enable** watch mode — tray icon turns green |
| 2nd press | **Disable** watch mode — tray icon turns purple |

While watch mode is **ON**, simply **select any text with the mouse**. The moment you release the mouse button the text is automatically copied, translated, and a floating tooltip appears near your cursor. Every translation is also written to the log file.

You can also toggle via the tray icon right-click menu.

### Typical workflow
1. Press your configured hotkey to turn on translation.
2. Select any text with the mouse — tooltip appears instantly.
3. Press the hotkey again when done.

## Quick start

### Windows (PowerShell)

```powershell
# 1. Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python main.py
```

### macOS (zsh/bash)

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
python -m pip install -r requirements.txt

# 3. Run
python main.py
```

> **Note:** Requires Python 3.10+. Translation uses Google Translate's public endpoint via the standard-library `urllib` — no API keys needed.

### macOS permissions

On macOS, automatic “copy selected text” and global hotkeys require OS permissions.

Grant these to the app you run it from (Terminal / iTerm / VS Code / the packaged app):

- **Privacy & Security → Input Monitoring**
- **Privacy & Security → Accessibility**

If permissions are missing, selecting text may not copy to the clipboard, and no tooltip will appear.

## Configuration — `config.json`

| Key | Type | Default | Description |
|---|---|---|---|
| `source_language` | string | `"auto"` | Language of selected text. Use `"auto"` for auto-detection, or an ISO 639-1 code (e.g. `"en"`, `"de"`). |
| `target_languages` | array | `["en","zh-CN"]` | 1–2 language codes to translate into. |
| `hotkey` | string | `"ctrl+alt+t"` | Global hotkey that toggles watch mode on/off. |
| `tooltip_duration_ms` | int | `4000` | Milliseconds the tooltip stays visible. |
| `max_chars` | int | `500` | Maximum characters of selected text to translate. |
| `exclusive_source_language` | bool | `false` | If `true`, only translate when the selected text is detected to be `source_language` (ignored when `source_language` is `"auto"`). |
| `log_file` | string | `"translations.log"` | Path to the log file. Relative paths are resolved from the project folder. Set to `""` to disable logging. |

### Example — translate English → German & Japanese

```json
{
  "source_language": "en",
  "target_languages": ["de", "ja"],
  "hotkey": "ctrl+shift+t",
  "tooltip_duration_ms": 5000,
  "max_chars": 500
}
```

### Common language codes

| Language | Code |
|---|---|
| English | `en` |
| French | `fr` |
| Spanish | `es` |
| German | `de` |
| Italian | `it` |
| Portuguese | `pt` |
| Japanese | `ja` |
| Chinese (Simplified) | `zh-CN` |
| Arabic | `ar` |
| Russian | `ru` |

> Full list: [Google Translate language codes](https://cloud.google.com/translate/docs/languages).  
> Use `"auto"` to let Google auto-detect the source language.

## Project structure

```
launguage_helper/
├── main.py                 # Entry point
├── config.json             # User configuration
├── requirements.txt
├── src/
│   ├── config.py           # Config loader
│   ├── translator.py       # Translation (Google public endpoint via urllib)
│   ├── clipboard_monitor.py# Hotkey listener + clipboard handling
│   ├── tooltip.py          # Floating Tkinter overlay
│   └── tray.py             # System tray icon (pystray)
└── .github/
    └── copilot-instructions.md
```

## Tray icon menu

- **Translation: ON / OFF** — same as pressing the hotkey; toggles watch mode. Icon turns green when active.
- **Reload Config** — picks up changes to `config.json` without restarting.
- **Quit** — stops the app cleanly.

## Troubleshooting

| Problem | Fix |
|---|---|
| Tooltip does not appear | Make sure text is actually selected *before* pressing the hotkey. |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` inside your virtual environment. |
| Hotkey conflicts | Change `hotkey` in `config.json` to a combination not used by other apps. |
| Translation errors | Check your internet connection — Google Translate requires network access. |
