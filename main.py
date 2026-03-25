"""
Language Helper — entry point.

Starts the clipboard monitor (hotkey listener) in the background
and launches the system tray icon on the main thread.
"""

import ctypes
import os
import sys
from src import single_instance


def main() -> None:
    if sys.platform != "win32":
        # The app is built for Windows (pystray + win32 clipboard/mouse APIs).
        # On macOS pystray may hit unrecognized selector errors like:
        #   -[NSApplication macOSVersion]: unrecognized selector
        print("[main] Unsupported platform: Language Helper is Windows-only.")
        return

    # Import Windows-specific modules lazily to avoid macOS import crash paths.
    from src.clipboard_monitor import ClipboardMonitor
    from src.tray import TrayApp

    instance_lock = single_instance.acquire("language_helper")
    if instance_lock is None:
        print("[main] Language Helper is already running.")
        return

    # Windows console Ctrl events (CTRL_C_EVENT/CTRL_BREAK_EVENT) can surface as
    # KeyboardInterrupt inside pystray's GetMessage loop. Since this is a tray
    # app (Quit is handled via the tray menu), ignore those console events.
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

    monitor = ClipboardMonitor()
    monitor.start()

    tray = TrayApp(monitor)
    print("[main] Language Helper started. Look for the tray icon.")
    print(f"[main] Hotkey: {monitor.hotkey}")
    print("[main] Press the hotkey once to ENABLE auto-translation, again to DISABLE.")

    try:
        tray.run()          # Blocking — runs until Quit is selected
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
        print("[main] Language Helper stopped.")


if __name__ == "__main__":
    main()
