"""System tray icon (Qt).

Provides a tray icon with a context menu:
  • Translation: ON / OFF — toggles watch mode (same as the hotkey)
  • Reload Config          — re-reads config.json without restarting
  • Quit                   — stops everything cleanly

The icon and tooltip title update to reflect the current watch-mode state.
"""

from __future__ import annotations

import threading

from PySide6 import QtCore, QtGui, QtWidgets


_COLOR_ON = "#22c55e"   # green  — watch mode active
_COLOR_OFF = "#7c3aed"  # purple — watch mode inactive


def _create_tray_icon(active: bool) -> QtGui.QIcon:
    size = 64
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

    color = QtGui.QColor(_COLOR_ON if active else _COLOR_OFF)
    painter.setBrush(QtGui.QBrush(color))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, size - 8, size - 8)

    painter.setPen(QtGui.QPen(QtGui.QColor("white")))
    font = QtGui.QFont()
    font.setBold(True)
    font.setPointSize(20)
    painter.setFont(font)
    painter.drawText(QtCore.QRect(0, 0, size, size), QtCore.Qt.AlignmentFlag.AlignCenter, "T")
    painter.end()

    return QtGui.QIcon(pix)


class TrayApp(QtCore.QObject):
    state_changed = QtCore.Signal(bool)

    def __init__(self, monitor) -> None:
        super().__init__()
        self._monitor = monitor
        self._tray: QtWidgets.QSystemTrayIcon | None = None
        self._menu: QtWidgets.QMenu | None = None
        self._toggle_action: QtGui.QAction | None = None

        self.state_changed.connect(self._apply_state, QtCore.Qt.ConnectionType.QueuedConnection)
        monitor.set_toggle_callback(self._on_state_change_from_any_thread)

    def start(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication must be created before starting TrayApp")

        active = self._monitor.is_active
        tray = QtWidgets.QSystemTrayIcon(_create_tray_icon(active))
        tray.setToolTip(f"Language Helper — {'ON' if active else 'OFF'}")

        menu = QtWidgets.QMenu()
        title = QtGui.QAction("Language Helper")
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()

        toggle_action = QtGui.QAction("Translation: ON" if active else "Translation: OFF")
        toggle_action.setCheckable(True)
        toggle_action.setChecked(active)
        toggle_action.triggered.connect(self._toggle)
        menu.addAction(toggle_action)
        menu.addSeparator()

        reload_action = QtGui.QAction("Reload Config")
        reload_action.triggered.connect(self._reload_config)
        menu.addAction(reload_action)

        quit_action = QtGui.QAction("Quit")
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        tray.show()

        self._tray = tray
        self._menu = menu
        self._toggle_action = toggle_action

    @QtCore.Slot(bool)
    def _apply_state(self, active: bool) -> None:
        if self._tray is None:
            return
        self._tray.setIcon(_create_tray_icon(active))
        self._tray.setToolTip(f"Language Helper — {'ON' if active else 'OFF'}")
        if self._toggle_action is not None:
            self._toggle_action.blockSignals(True)
            try:
                self._toggle_action.setChecked(active)
                self._toggle_action.setText("Translation: ON" if active else "Translation: OFF")
            finally:
                self._toggle_action.blockSignals(False)

    def _on_state_change_from_any_thread(self, active: bool) -> None:
        # Hotkey callbacks can come from non-GUI threads.
        self.state_changed.emit(bool(active))

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        threading.Thread(target=self._monitor.toggle, daemon=True).start()

    def _reload_config(self) -> None:
        threading.Thread(target=self._monitor.reload_config, daemon=True).start()

    def _quit(self) -> None:
        try:
            self._monitor.stop()
        finally:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.quit()
