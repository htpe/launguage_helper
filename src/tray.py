"""
System tray icon.

Provides a tray icon with a context menu:
  • Translation: ON / OFF — toggles watch mode (same as the hotkey)
  • Reload Config          — re-reads config.json without restarting
  • Quit                   — stops everything cleanly

The icon and tooltip title update to reflect the current watch-mode state.
"""

import threading

import pystray
from PIL import Image, ImageDraw

from src import config as cfg_mod

_COLOR_ON  = "#22c55e"   # green  — watch mode active
_COLOR_OFF = "#7c3aed"   # purple — watch mode inactive


def _create_icon_image(active: bool) -> Image.Image:
    """Create the tray icon; green when active, purple when inactive."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _COLOR_ON if active else _COLOR_OFF
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    draw.text((20, 14), "T", fill="white")
    return img


class TrayApp:
    def __init__(self, monitor) -> None:
        self._monitor = monitor
        self._icon: pystray.Icon | None = None
        # Let the monitor call us back when the state flips
        monitor.set_toggle_callback(self._on_state_change)

    def run(self) -> None:
        """Build the tray icon and start its event loop (blocking)."""
        menu = pystray.Menu(
            pystray.MenuItem("Language Helper", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._toggle_label,
                self._toggle,
                checked=lambda item: self._monitor.is_active,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Reload Config", self._reload_config),
            pystray.MenuItem("Quit", self._quit),
        )
        self._icon = pystray.Icon(
            "language_helper",
            _create_icon_image(False),
            "Language Helper — OFF",
            menu,
        )
        self._icon.run()

    def stop(self) -> None:
        if self._icon:
            self._icon.stop()

    # ------------------------------------------------------------------
    # Menu helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _toggle_label(item) -> str:   # noqa: ARG004
        return "Translation: ON" if item.checked else "Translation: OFF"

    def _on_state_change(self, active: bool) -> None:
        """Called by ClipboardMonitor after each toggle — refresh icon & title."""
        if self._icon is None:
            return
        self._icon.icon = _create_icon_image(active)
        self._icon.title = f"Language Helper — {'ON' if active else 'OFF'}"
        self._icon.update_menu()

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _toggle(self, icon, item) -> None:  # noqa: ARG002
        threading.Thread(target=self._monitor.toggle, daemon=True).start()

    def _reload_config(self, icon, item) -> None:  # noqa: ARG002
        threading.Thread(target=self._monitor.reload_config, daemon=True).start()

    def _quit(self, icon, item) -> None:  # noqa: ARG002
        self._monitor.stop()
        if self._icon:
            self._icon.stop()
