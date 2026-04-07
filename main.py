"""
Language Helper — entry point.

Starts the clipboard monitor (hotkey listener) in the background
and launches the system tray icon on the main thread.
"""

import ctypes
import os
import sys
import faulthandler
import traceback
import threading

from src.clipboard_monitor import ClipboardMonitor
from src.tray import TrayApp
from src import single_instance
from src import tooltip

from PySide6 import QtWidgets

_FAULT_FILE = None


def _runtime_base_dir() -> str:
    """Best-effort directory for runtime-created files (logs).

    When frozen, prefer the executable directory; otherwise use the project
    root (directory containing main.py).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _install_crash_logging() -> None:
    """Write Python exceptions and faulthandler output to log files.

    This is especially helpful on macOS where GUI apps may crash without a
    visible console.
    """
    base_dir = _runtime_base_dir()
    log_dir = os.path.join(base_dir, "log")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = base_dir

    fault_path = os.path.join(log_dir, "faulthandler.log")
    exc_path = os.path.join(log_dir, "exceptions.log")

    global _FAULT_FILE
    try:
        _FAULT_FILE = open(fault_path, "a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE)
    except Exception:
        try:
            faulthandler.enable()
        except Exception:
            pass

    def _hook(exc_type, exc, tb) -> None:  # noqa: ANN001
        try:
            with open(exc_path, "a", encoding="utf-8") as f:
                f.write("\n" + ("=" * 80) + "\n")
                f.write("Uncaught exception:\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass

    sys.excepthook = _hook

    # Also log uncaught exceptions from background threads (Python 3.8+).
    def _thread_hook(args: threading.ExceptHookArgs) -> None:  # noqa: ANN001
        try:
            with open(exc_path, "a", encoding="utf-8") as f:
                f.write("\n" + ("=" * 80) + "\n")
                f.write(f"Uncaught thread exception: {getattr(args, 'thread', None)}\n")
                traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=f)
        except Exception:
            pass

    try:
        threading.excepthook = _thread_hook  # type: ignore[assignment]
    except Exception:
        pass


def main() -> None:
    _install_crash_logging()

    instance_lock = single_instance.acquire("language_helper")
    if instance_lock is None:
        print("[main] Language Helper is already running.")
        return

    # Windows console Ctrl events (CTRL_C_EVENT/CTRL_BREAK_EVENT) are not used
    # for app lifecycle (Quit is handled via the tray menu), so ignore them.
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetConsoleCtrlHandler(None, True)
        except Exception:
            pass

    # Optional: detach from the console (useful for long-running tray usage).
    # Detaching makes sys.stdout invalid, so only do it when explicitly enabled.
    if sys.platform == "win32" and os.environ.get("LANGUAGE_HELPER_DETACH_CONSOLE") == "1":
        try:
            ctypes.windll.kernel32.FreeConsole()
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
            sys.stderr = sys.stdout
        except Exception:
            pass

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)

    tooltip.init_qt()

    monitor = ClipboardMonitor()
    monitor.start()

    tray = TrayApp(monitor)
    tray.start()

    print("[main] Language Helper started. Look for the tray icon.")
    print(f"[main] Hotkey: {monitor.hotkey}")
    print("[main] Auto-translation starts ENABLED by default.")
    print("[main] Press the hotkey to toggle auto-translation ON/OFF.")

    try:
        app.exec()
    finally:
        monitor.stop()
        print("[main] Language Helper stopped.")


if __name__ == "__main__":
    main()
