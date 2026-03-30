"""Config loader.

Selects an OS-specific config file when present:
    - Windows: config.windows.json
    - macOS  : config.macos.json
Fallback: config.json
"""

import json
import os
import sys

_FALLBACK_NAME = "config.json"
_WINDOWS_NAME = "config.windows.json"
_MACOS_NAME = "config.macos.json"

_DEFAULTS = {
    "source_language": "auto",
    "target_languages": ["fr", "es"],
    "hotkey": "ctrl+shift+t",
    "tooltip_duration_ms": 4000,
    "max_chars": 500,
    "exclusive_source_language": False,
}


def load() -> dict:
    """Return the merged configuration (file settings override defaults)."""
    cfg = dict(_DEFAULTS)

    bases: list[str] = []

    # Frozen apps: prefer config files next to the executable (user-editable),
    # then fall back to PyInstaller's extracted bundle dir (sys._MEIPASS).
    if getattr(sys, "frozen", False):
        try:
            bases.append(os.path.dirname(sys.executable))
        except Exception:
            pass
        if hasattr(sys, "_MEIPASS"):
            try:
                bases.append(getattr(sys, "_MEIPASS"))  # type: ignore[arg-type]
            except Exception:
                pass

    # Non-frozen: project root (directory containing config.json).
    bases.append(os.path.dirname(os.path.dirname(__file__)))

    if sys.platform == "win32":
        preferred = _WINDOWS_NAME
    elif sys.platform == "darwin":
        preferred = _MACOS_NAME
    else:
        preferred = _FALLBACK_NAME

    try:
        candidates: list[str] = []
        for base_dir in bases:
            candidates.append(os.path.join(base_dir, preferred))
            candidates.append(os.path.join(base_dir, _FALLBACK_NAME))

        config_path = next((p for p in candidates if os.path.exists(p)), candidates[-1])
        with open(config_path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass  # Use defaults silently
    except json.JSONDecodeError as exc:
        print(f"[config] Invalid JSON in config file: {exc}")
    return cfg
