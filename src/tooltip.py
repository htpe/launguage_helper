"""Tooltip overlay window (Qt).

Shows a small, frameless, always-on-top overlay window positioned near the
cursor with the translated text and optional example sentences.

This module keeps UI work on the Qt GUI thread and allows worker threads to
request a tooltip in a thread-safe way.
"""

from __future__ import annotations

import threading

from PySide6 import QtCore, QtGui, QtWidgets


_BG = "#1e1e2e"
_FG = "#cdd6f4"
_ACCENT = "#cba6f7"
_EXAMPLE = "#a6e3a1"
_MUTED = "#6c7086"
_SEP = "#45475a"


class _TooltipWidget(QtWidgets.QWidget):
    closed = QtCore.Signal()

    def __init__(
        self,
        translations: dict[str, str],
        x: int,
        y: int,
        duration_ms: int,
        examples: list[str] | None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        flags = (
            QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent=parent, f=flags)

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        self._duration_ms = int(duration_ms)
        self._x = int(x)
        self._y = int(y)
        self._timer: QtCore.QTimer | None = None

        container = QtWidgets.QFrame(self)
        container.setObjectName("tooltipContainer")
        container.setStyleSheet(
            """
            QFrame#tooltipContainer {
              background: %s;
              border-radius: 10px;
            }
            """ % _BG
        )

        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        font_small_bold = QtGui.QFont()
        font_small_bold.setPointSize(9)
        font_small_bold.setBold(True)

        font_body = QtGui.QFont()
        font_body.setPointSize(11)

        font_examples_header = QtGui.QFont()
        font_examples_header.setPointSize(8)
        font_examples_header.setBold(True)

        font_example = QtGui.QFont()
        font_example.setPointSize(10)
        font_example.setItalic(True)

        # Close button row
        close_row = QtWidgets.QHBoxLayout()
        close_row.setContentsMargins(0, 0, 0, 0)
        close_row.addStretch(1)

        close_btn = QtWidgets.QToolButton(container)
        close_btn.setText("✕")
        close_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        close_btn.setAutoRaise(True)
        close_btn.setStyleSheet(
            """
            QToolButton {
              color: %s;
              background: transparent;
              border: none;
              padding: 0px;
            }
            QToolButton:hover {
              color: %s;
            }
            """ % (_MUTED, _FG)
        )
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        for lang, translated in translations.items():
            lang_label = QtWidgets.QLabel(f"[{str(lang).upper()}]")
            lang_label.setFont(font_small_bold)
            lang_label.setStyleSheet(f"color: {_ACCENT};")
            layout.addWidget(lang_label)

            text_label = QtWidgets.QLabel(str(translated))
            text_label.setFont(font_body)
            text_label.setStyleSheet(f"color: {_FG};")
            text_label.setWordWrap(True)
            text_label.setMaximumWidth(380)
            layout.addWidget(text_label)

        ex_list = list(examples or [])
        if ex_list:
            sep = QtWidgets.QFrame(container)
            sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {_SEP}; background: {_SEP};")
            layout.addWidget(sep)

            ex_header = QtWidgets.QLabel("EXAMPLES")
            ex_header.setFont(font_examples_header)
            ex_header.setStyleSheet("color: #a6adc8;")
            layout.addWidget(ex_header)

            for i, sentence in enumerate(ex_list, 1):
                ex_label = QtWidgets.QLabel(f"{i}. {sentence}")
                ex_label.setFont(font_example)
                ex_label.setStyleSheet(f"color: {_EXAMPLE};")
                ex_label.setWordWrap(True)
                ex_label.setMaximumWidth(380)
                layout.addWidget(ex_label)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        self.setWindowOpacity(0.92)
        self._position_near_cursor()

        if self._duration_ms > 0:
            self._timer = QtCore.QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.close)
            self._timer.start(self._duration_ms)

    def _position_near_cursor(self) -> None:
        # Offset so it doesn't cover the selected text.
        desired = QtCore.QPoint(self._x + 12, self._y + 20)

        screen = QtGui.QGuiApplication.screenAt(QtCore.QPoint(self._x, self._y))
        if screen is None:
            screen = QtGui.QGuiApplication.primaryScreen()
        geom = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1920, 1080)

        self.adjustSize()
        size = self.sizeHint()
        x = min(desired.x(), geom.right() - size.width() - 10)
        y = min(desired.y(), geom.bottom() - size.height() - 10)
        x = max(geom.left() + 10, x)
        y = max(geom.top() + 10, y)
        self.move(x, y)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        try:
            self.closed.emit()
        finally:
            super().closeEvent(event)


class TooltipService(QtCore.QObject):
    """GUI-thread service to show at most one tooltip at a time."""

    request_show = QtCore.Signal(object, int, int, int, object, object)

    def __init__(self) -> None:
        super().__init__()
        self._current: _TooltipWidget | None = None
        self.request_show.connect(self._on_request_show, QtCore.Qt.ConnectionType.QueuedConnection)

    @QtCore.Slot(object, int, int, int, object, object)
    def _on_request_show(
        self,
        translations_obj: object,
        x: int,
        y: int,
        duration_ms: int,
        examples_obj: object,
        done_obj: object,
    ) -> None:
        translations = translations_obj if isinstance(translations_obj, dict) else {}
        examples = examples_obj if isinstance(examples_obj, list) else None
        done = done_obj if isinstance(done_obj, threading.Event) else None

        w = self._show(translations, x, y, duration_ms, examples)

        if done is not None:
            w.closed.connect(lambda: done.set())

    def _show(
        self,
        translations: dict[str, str],
        x: int,
        y: int,
        duration_ms: int,
        examples: list[str] | None,
    ) -> _TooltipWidget:
        if self._current is not None:
            try:
                self._current.close()
            except Exception:
                pass
            self._current = None

        w = _TooltipWidget(translations, x, y, duration_ms, examples)
        w.closed.connect(lambda: self._on_closed(w))
        self._current = w
        w.show()
        return w

    def _on_closed(self, w: _TooltipWidget) -> None:
        if self._current is w:
            self._current = None


_SERVICE: TooltipService | None = None


def init_qt() -> None:
    """Initialize the tooltip service.

    Must be called after `QApplication` is created.
    """
    global _SERVICE
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    if _SERVICE is None:
        _SERVICE = TooltipService()
        _SERVICE.moveToThread(app.thread())


def request_exit() -> None:
    """For compatibility with the old API."""
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.quit()


def show_tooltip(
    translations: dict[str, str],
    x: int,
    y: int,
    duration_ms: int = 4000,
    examples: list[str] | None = None,
) -> None:
    """Show the tooltip and block until it closes.

    The caller (often a worker thread) waits until the tooltip auto-closes or
    the user closes it, preserving previous behavior.
    """

    app = QtWidgets.QApplication.instance()
    if app is None:
        # Normal usage creates QApplication in main.py.
        return

    init_qt()
    if _SERVICE is None:
        return

    # If called on the GUI thread, don't block the event loop.
    if QtCore.QThread.currentThread() == app.thread():
        _SERVICE._show(translations, int(x), int(y), int(duration_ms), examples)
        return

    done = threading.Event()
    _SERVICE.request_show.emit(translations, int(x), int(y), int(duration_ms), examples, done)
    done.wait()
