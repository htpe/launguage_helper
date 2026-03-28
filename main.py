"""
Language Helper — entry point.

Starts the clipboard monitor (hotkey listener) in the background
and launches the system tray icon on the main thread.
"""

import ctypes
import os
import sys
import faulthandler

from src.clipboard_monitor import ClipboardMonitor
from src.tray import TrayApp
from src import single_instance
from src import tooltip

from PySide6 import QtWidgets


def main() -> None:
    # Helpful for diagnosing hard crashes/segfaults (common with GUI toolkits).
    try:
        faulthandler.enable()
    except Exception:
        pass

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
