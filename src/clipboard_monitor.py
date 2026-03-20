"""
Clipboard monitor — Windows & macOS compatible.

The global hotkey (default Ctrl+Alt+T) TOGGLES translation on / off:
  • First press  → enable watch mode  (tray icon turns green)
  • Second press → disable watch mode  (tray icon turns purple)

While watch mode is ON:
  A pynput mouse listener watches for left-button releases.
  On each release it waits briefly, simulates the system copy shortcut
  (Ctrl+C on Windows/Linux, Cmd+C on macOS), and if the clipboard
  changed it translates immediately and shows a tooltip.
  Every translation is also appended to the log file.

The user workflow:
  1. Press the hotkey to enable (or use the tray menu toggle).
  2. Select any text with the mouse — tooltip appears automatically.
  3. Press the hotkey again to disable.

Platform notes:
  - Windows : pywin32 not required; pynput handles everything.
  - macOS   : grant Input Monitoring + Accessibility in System Preferences.
"""

import os
import re
import sys
import threading
import time
from collections import deque

import pyperclip
from pynput import mouse as pynput_mouse
from pynput.keyboard import Key, Controller as _KeyboardController

from src import config as cfg_mod
from src import translator
from src import tooltip
from src import translation_log

_kb = _KeyboardController()
_mouse_ctrl = pynput_mouse.Controller()

# macOS uses Cmd+C; Windows/Linux use Ctrl+C
_COPY_MOD = Key.cmd if sys.platform == "darwin" else Key.ctrl

# ---------------------------------------------------------------------------
# Platform-specific hotkey backend
#
# On Windows, pynput.keyboard.GlobalHotKeys creates its own win32 keyboard
# hook with a message pump that conflicts with pystray's GetMessage loop,
# causing a crash in pystray._win32._mainloop.  The `keyboard` module handles
# hotkeys differently (via a low-level keyboard hook in its own thread) and
# has no conflict with pystray on Windows.
#
# On macOS, `keyboard` requires root / sudo; pynput.GlobalHotKeys is the
# correct cross-platform approach there.
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import keyboard as _keyboard_win  # type: ignore[import]
    _HOTKEY_BACKEND = "keyboard"
    _GlobalHotKeys = None  # type: ignore[assignment]

    import ctypes as _ctypes
    _k32 = _ctypes.windll.kernel32
else:
    from pynput.keyboard import GlobalHotKeys as _GlobalHotKeys
    _HOTKEY_BACKEND = "pynput"

_SPECIAL_KEYS = {
    "ctrl", "alt", "shift", "cmd", "win", "super",
    "control", "option", "command",
    "enter", "space", "tab", "esc", "backspace", "delete",
    "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
}
_FKEY_RE = re.compile(r"^f\d+$")


def _to_pynput_hotkey(hotkey_str: str) -> str:
    """Convert 'ctrl+alt+t' style string to pynput '<ctrl>+<alt>+t' format."""
    parts = hotkey_str.lower().split("+")
    converted = []
    for part in parts:
        part = part.strip()
        # Common aliases (especially on macOS)
        part = {
            "control": "ctrl",
            "option": "alt",
            "command": "cmd",
            "escape": "esc",
        }.get(part, part)
        if part in _SPECIAL_KEYS or _FKEY_RE.match(part):
            converted.append(f"<{part}>")
        else:
            converted.append(part)
    return "+".join(converted)


def _inject_copy() -> None:
    """
    Inject the system copy shortcut (Ctrl+C on Windows/Linux, Cmd+C on macOS)
    without letting the keystroke generate a SIGINT / KeyboardInterrupt.

    On Windows, Ctrl+C sent via SendInput triggers CTRL_C_EVENT for any
    process attached to a console.  Python converts that to SIGINT, which
    surfaces as a KeyboardInterrupt inside pystray's blocking GetMessage()
    call.  We guard around the injection with SetConsoleCtrlHandler(NULL,
    TRUE/FALSE) which suppresses the Ctrl+C console event for our process
    for the duration of the keystroke only.
    """
    if sys.platform == "win32":
        # Ignore CTRL_C_EVENT during injection. We intentionally do not
        # restore the handler because this is a tray app and restoring can
        # re-enable KeyboardInterrupt inside pystray's GetMessage loop.
        _k32.SetConsoleCtrlHandler(None, True)
        with _kb.pressed(_COPY_MOD):
            _kb.press('c')
            _kb.release('c')
    else:
        with _kb.pressed(_COPY_MOD):
            _kb.press('c')
            _kb.release('c')

class ClipboardMonitor:
    def __init__(self) -> None:
        self._cfg = cfg_mod.load()
        self._running = False
        self._active = False
        self._last_text: str = ""
        self._recent_selections: deque[str] = deque(maxlen=10)
        self._mouse_listener: pynput_mouse.Listener | None = None
        self._hotkey_listener = None   # GlobalHotKeys (macOS/Linux) or thread (Windows)
        self._hotkey_str: str = ""
        self._hotkey_handle = None     # keyboard.add_hotkey handle (Windows only)
        self._hotkey_watchdog_stop = threading.Event()
        self._hotkey_watchdog_thread: threading.Thread | None = None
        self._last_hotkey_ts = 0.0
        self._on_toggle_callback = None
        self._translate_lock = threading.Lock()
        self._pending_text: str | None = None
        self._pending_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_toggle_callback(self, cb) -> None:
        self._on_toggle_callback = cb

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def hotkey(self) -> str:
        """The configured hotkey string (e.g. 'ctrl+alt+z')."""
        return str(self._cfg.get("hotkey", "ctrl+alt+t"))

    def start(self) -> None:
        """Register the global hotkey and immediately enable watch mode."""
        if self._running:
            return

        self._running = True
        self._hotkey_watchdog_stop.clear()
        self._register_hotkey(force=True)
        if _HOTKEY_BACKEND == "keyboard":
            self._start_hotkey_watchdog()

        if self._hotkey_str:
            print(f"[monitor] Hotkey '{self._hotkey_str}' registered — toggles translation on/off.")
        # Start active so the user can translate immediately without pressing the hotkey
        self.toggle()

    def stop(self) -> None:
        """Disable watch mode and clean up all listeners."""
        self._running = False
        self._active = False
        self._hotkey_watchdog_stop.set()
        if _HOTKEY_BACKEND == "keyboard":
            try:
                if self._hotkey_handle is not None:
                    try:
                        _keyboard_win.remove_hotkey(self._hotkey_handle)
                    except Exception:
                        pass
                self._hotkey_handle = None
                self._hotkey_str = ""
                _keyboard_win.unhook_all_hotkeys()
            except Exception:
                pass
        else:
            self._stop_hotkey_listener()
        self._stop_mouse_listener()

    def toggle(self, source: str | None = None) -> bool:
        """Flip watch mode on/off. Returns the new state."""
        self._active = not self._active
        if self._active:
            try:
                self._last_text = pyperclip.paste() or ""
            except Exception:
                self._last_text = ""
            self._start_mouse_listener()
            if source == "hotkey":
                print("[monitor] (hotkey) Auto-translation ENABLED.", flush=True)
        else:
            self._stop_mouse_listener()
            if source == "hotkey":
                print("[monitor] (hotkey) Auto-translation DISABLED.", flush=True)
        if self._on_toggle_callback:
            self._on_toggle_callback(self._active)
        return self._active

    def reload_config(self) -> None:
        """Re-read config.json at runtime (called by tray menu)."""
        was_active = self._active
        self.stop()
        self._cfg = cfg_mod.load()
        self.start()          # sets self._running = True internally
        # start() always enables watch mode; only toggle if we were previously inactive.
        if not was_active:
            self.toggle(source="reload")
        print(f"[monitor] Config reloaded. targets={self._cfg.get('target_languages')}")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _on_hotkey(self) -> None:
        # Guard against key-repeat, unlock floods, or duplicate hook callbacks.
        now = time.monotonic()
        if now - self._last_hotkey_ts < 0.5:
            return
        self._last_hotkey_ts = now
        # Run synchronously so the console status prints immediately.
        self.toggle(source="hotkey")

    def _register_hotkey(self, force: bool = False) -> None:
        """(Re)register the hotkey for the current config.

        On Windows we use the `keyboard` backend which can occasionally stop
        receiving events after sleep/lock cycles. Re-registering is a cheap and
        effective recovery.
        """
        hotkey = self._cfg.get("hotkey", "ctrl+alt+t")

        if not force and hotkey == self._hotkey_str:
            return

        if _HOTKEY_BACKEND == "keyboard":
            # Remove the previous handler first to avoid duplicate toggles.
            if self._hotkey_handle is not None:
                try:
                    _keyboard_win.remove_hotkey(self._hotkey_handle)
                except Exception:
                    pass
                self._hotkey_handle = None

            try:
                # The `keyboard` library may map a letter to multiple scan codes
                # (e.g. on systems with multiple layouts), which can make a hotkey
                # appear like it triggers on both 'y' and 'z'. To avoid that, we
                # parse once and restrict the last key to a single scan code.
                parsed = _keyboard_win.parse_hotkey(hotkey)
                if parsed and len(parsed) == 1 and parsed[0]:
                    step = list(parsed[0])
                    last = step[-1]
                    if isinstance(last, tuple) and len(last) > 1:
                        step[-1] = (last[0],)
                    parsed = (tuple(step),)

                self._hotkey_handle = _keyboard_win.add_hotkey(
                    parsed,
                    self._on_hotkey,
                    suppress=False,
                    trigger_on_release=True,
                )
                self._hotkey_str = hotkey
            except Exception as exc:  # noqa: BLE001
                self._hotkey_handle = None
                self._hotkey_str = ""
                print(f"[monitor] Failed to register hotkey '{hotkey}': {exc}", flush=True)

        elif _HOTKEY_BACKEND == "pynput":
            # macOS/Linux via pynput
            self._stop_hotkey_listener()
            try:
                pynput_hotkey = _to_pynput_hotkey(hotkey)
                self._hotkey_listener = _GlobalHotKeys({pynput_hotkey: self._on_hotkey})
                self._hotkey_listener.start()
                self._hotkey_str = hotkey
            except Exception as exc:  # noqa: BLE001
                self._hotkey_str = ""
                print(f"[monitor] Failed to register hotkey '{hotkey}': {exc}")

    def _start_hotkey_watchdog(self) -> None:
        if self._hotkey_watchdog_thread and self._hotkey_watchdog_thread.is_alive():
            return

        def _watchdog() -> None:
            # Re-register occasionally to recover from Windows lock/sleep cycles.
            interval_s = 20 * 60
            while self._running and not self._hotkey_watchdog_stop.wait(interval_s):
                if not self._running:
                    return
                if _HOTKEY_BACKEND == "keyboard":
                    self._register_hotkey(force=True)

        self._hotkey_watchdog_thread = threading.Thread(
            target=_watchdog,
            name="hotkey-watchdog",
            daemon=True,
        )
        self._hotkey_watchdog_thread.start()

    def _start_mouse_listener(self) -> None:
        if self._mouse_listener and self._mouse_listener.is_alive():
            return
        self._mouse_listener = pynput_mouse.Listener(on_click=self._on_mouse_click)
        self._mouse_listener.start()

    def _stop_mouse_listener(self) -> None:
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    def _stop_hotkey_listener(self) -> None:
        if self._hotkey_listener:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None

    def _on_mouse_click(self, x, y, button, pressed) -> None:
        if not self._active:
            return
        if button != pynput_mouse.Button.left or pressed:
            return
        threading.Thread(target=self._capture_selection, daemon=True).start()

    def _capture_selection(self) -> None:
        """Wait briefly, copy selected text, translate if something changed."""
        time.sleep(0.18)

        _inject_copy()
        time.sleep(0.15)

        try:
            after = pyperclip.paste() or ""
        except Exception:
            return

        text = after.strip()
        if not text:
            return

        self._last_text = after
        threading.Thread(target=self._show_translation, args=(text,), daemon=True).start()

    def _get_cursor_pos(self) -> tuple[int, int]:
        """Get current cursor position using pynput (cross-platform)."""
        try:
            pos = _mouse_ctrl.position
            return int(pos[0]), int(pos[1])
        except Exception:
            return 100, 100

    def _show_translation(self, text: str) -> None:
        """Translate *text*, display the tooltip, and append to the log file."""
        if not self._translate_lock.acquire(blocking=False):
            # A tooltip is currently being shown (Tk mainloop blocks). Queue the
            # latest selection so it will still be translated/shown afterwards.
            with self._pending_lock:
                self._pending_text = text
            return
        try:
            max_chars = self._cfg.get("max_chars", 500)
            text = text[:max_chars]

            # Keep last 10 selections in memory. Only log if this selection is
            # not within the last 10.
            should_log = True
            try:
                if text in self._recent_selections:
                    should_log = False
                    # Maintain recency (LRU behavior).
                    try:
                        self._recent_selections.remove(text)
                    except ValueError:
                        pass
                self._recent_selections.append(text)
            except Exception:
                # Never let de-dupe logic break translation.
                should_log = True

            source = self._cfg.get("source_language", "auto")
            targets = self._cfg.get("target_languages", ["fr"])
            translations = translator.translate(text, source, targets)

            is_single_word = len(text.split()) == 1
            examples = translator.get_examples(text, source) if is_single_word else []

            log_cfg = self._cfg.get("log_file", "log/translations.log")
            if log_cfg and should_log:
                # Determine base directory (executable dir when frozen, project root otherwise)
                if getattr(sys, 'frozen', False):
                    base_dir = os.path.dirname(sys.executable)
                else:
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                
                log_path = log_cfg if os.path.isabs(log_cfg) else os.path.join(base_dir, log_cfg)
                
                # Create log directory if it doesn't exist
                log_dir = os.path.dirname(log_path)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)
                
                translation_log.log(text, source, translations, log_path=log_path, examples=examples)

            x, y = self._get_cursor_pos()
            duration_ms = self._cfg.get("tooltip_duration_ms", 4000)
            tooltip.show_tooltip(translations, x, y, duration_ms, examples=examples)
        finally:
            self._translate_lock.release()

            # If something was selected while we were busy, process the newest
            # queued selection next.
            pending: str | None = None
            with self._pending_lock:
                pending = self._pending_text
                self._pending_text = None
            if pending:
                threading.Thread(target=self._show_translation, args=(pending,), daemon=True).start()
