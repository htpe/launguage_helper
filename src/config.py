"""Config loader — reads config.json from the project root."""

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

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
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass  # Use defaults silently
    except json.JSONDecodeError as exc:
        print(f"[config] Invalid JSON in config.json: {exc}")
    return cfg
