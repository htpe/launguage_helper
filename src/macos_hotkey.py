"""
macOS native hotkey monitoring via PyObjC + AppKit.

This module provides a native AppKit-based global hotkey listener for macOS,
replacing pynput for better reliability and native performance.

Requires Input Monitoring permission (System Preferences > Security & Privacy).
"""

import re
import threading
from typing import Callable, Optional

try:
    from AppKit import NSEvent, NSApplication, NSApp
    from Foundation import NSAutoreleasePool, NSRunLoop
    import objc
except ImportError:
    # Graceful fallback if PyObjC is not installed
    NSEvent = None
    NSApplication = None


# Mapping from user hotkey format to macOS modifier flags + keycodes
_MACOS_MODIFIERS = {
    "shift": 0x020000,  # NSEventModifierFlagShift
    "ctrl": 0x040000,   # NSEventModifierFlagControl
    "alt": 0x080000,    # NSEventModifierFlagOption
    "cmd": 0x100000,    # NSEventModifierFlagCommand
    "control": 0x040000,
    "option": 0x080000,
    "command": 0x100000,
}

# Keycode mapping (macOS Virtual Key Codes)
_MACOS_KEYCODES = {
    "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E, "f": 0x03,
    "g": 0x05, "h": 0x04, "i": 0x22, "j": 0x26, "k": 0x28, "l": 0x25,
    "m": 0x2E, "n": 0x2D, "o": 0x1F, "p": 0x23, "q": 0x0C, "r": 0x0F,
    "s": 0x01, "t": 0x11, "u": 0x20, "v": 0x09, "w": 0x0D, "x": 0x07,
    "y": 0x10, "z": 0x06,
    "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17,
    "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
    "space": 0x31,
    "enter": 0x24, "return": 0x24,
    "tab": 0x30,
    "esc": 0x35, "escape": 0x35,
    "backspace": 0x33, "delete": 0x33,
    "home": 0x73,
    "end": 0x77,
    "pageup": 0x74,
    "pagedown": 0x79,
    "up": 0x7E,
    "down": 0x7D,
    "left": 0x7B,
    "right": 0x7C,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60,
    "f6": 0x61, "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D,
    "f11": 0x67, "f12": 0x6F,
}


def _parse_hotkey(hotkey_str: str) -> tuple[int, int]:
    """
    Parse a hotkey string like 'cmd+alt+z' into (modifiers, keycode).

    Returns:
        (modifiers_int, keycode_int) or raises ValueError if unparseable.
    """
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    if not parts:
        raise ValueError(f"Invalid hotkey: {hotkey_str}")

    modifiers = 0
    keycode = None

    for part in parts:
        if part in _MACOS_MODIFIERS:
            modifiers |= _MACOS_MODIFIERS[part]
        elif part in _MACOS_KEYCODES:
            keycode = _MACOS_KEYCODES[part]
        else:
            raise ValueError(f"Unknown key in hotkey '{hotkey_str}': {part}")

    if keycode is None:
        raise ValueError(f"No main key in hotkey: {hotkey_str}")

    return modifiers, keycode


class MacOSHotkey:
    """Native macOS hotkey listener via AppKit."""

    def __init__(self, hotkey_str: str, callback: Callable[[], None]) -> None:
        """
        Initialize the macOS hotkey listener.

        Args:
            hotkey_str: e.g. 'cmd+alt+z'
            callback: Function to call when hotkey is pressed.

        Raises:
            ValueError: If hotkey string is invalid or PyObjC not available.
        """
        if NSEvent is None:
            raise ValueError("PyObjC AppKit not available. Install: pip install pyobjc-framework-Cocoa")

        self._hotkey_str = hotkey_str
        self._callback = callback
        self._modifiers, self._keycode = _parse_hotkey(hotkey_str)
        self._monitor_id: Optional[int] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start listening for the hotkey."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_listener, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop listening for the hotkey."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run_listener(self) -> None:
        """Run the event monitor in its own thread."""
        # Create autorelease pool for this thread
        pool = NSAutoreleasePool.alloc().init()

        try:
            def handler(event):
                # Check if this is the hotkey we're looking for
                if event.keyCode() == self._keycode:
                    event_modifiers = event.modifierFlags()
                    # Mask out irrelevant bits (keypad, function keys, etc.)
                    relevant_mods = event_modifiers & 0x1E0000
                    if relevant_mods == self._modifiers:
                        self._callback()

            # Register global event monitor
            # NSEventTypeKeyDown = 10
            self._monitor_id = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                1 << 10,  # NSEventMaskKeyDown
                handler,
            )

            # Keep the thread alive until stop() is called
            while self._running and not self._stop_event.wait(0.1):
                pass

            # Unregister the monitor
            if self._monitor_id is not None:
                NSEvent.removeMonitor_(self._monitor_id)
                self._monitor_id = None

        finally:
            pool.release()
