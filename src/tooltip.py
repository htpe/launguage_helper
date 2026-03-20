"""
Tooltip overlay window.

Shows a small, frameless, always-on-top Tkinter window positioned near
the mouse cursor with the translated text.  The window auto-closes after
*duration_ms* milliseconds.
"""

import tkinter as tk
from typing import Callable


class Tooltip:
    """Floating translation tooltip rendered with Tkinter."""

    def __init__(
        self,
        translations: dict[str, str],
        duration_ms: int = 4000,
        examples: list[str] | None = None,
    ):
        self._translations = translations
        self._duration_ms = duration_ms
        self._examples = examples or []
        self._root: tk.Tk | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self, x: int, y: int) -> None:
        """Create and display the tooltip at screen coordinates (*x*, *y*)."""
        if self._root is not None:
            self._close()

        root = tk.Tk()
        self._root = root

        root.overrideredirect(True)          # No title bar / decoration
        root.attributes("-topmost", True)    # Always on top
        root.attributes("-alpha", 0.92)      # Slight transparency

        # Build content
        frame = tk.Frame(root, bg="#1e1e2e", padx=10, pady=8)
        frame.pack()

        for lang, translated in self._translations.items():
            lang_label = tk.Label(
                frame,
                text=f"[{lang.upper()}]",
                font=("Segoe UI", 8, "bold"),
                bg="#1e1e2e",
                fg="#cba6f7",
                anchor="w",
            )
            lang_label.pack(fill="x")

            text_label = tk.Label(
                frame,
                text=translated,
                font=("Segoe UI", 10),
                bg="#1e1e2e",
                fg="#cdd6f4",
                wraplength=380,
                justify="left",
                anchor="w",
            )
            text_label.pack(fill="x", pady=(0, 4))

        # Examples section (single-word selections only)
        if self._examples:
            sep = tk.Frame(frame, bg="#45475a", height=1)
            sep.pack(fill="x", pady=(4, 6))

            ex_header = tk.Label(
                frame,
                text="EXAMPLES",
                font=("Segoe UI", 7, "bold"),
                bg="#1e1e2e",
                fg="#a6adc8",
                anchor="w",
            )
            ex_header.pack(fill="x")

            for i, sentence in enumerate(self._examples, 1):
                ex_label = tk.Label(
                    frame,
                    text=f"{i}. {sentence}",
                    font=("Segoe UI", 9, "italic"),
                    bg="#1e1e2e",
                    fg="#a6e3a1",
                    wraplength=380,
                    justify="left",
                    anchor="w",
                )
                ex_label.pack(fill="x", pady=(1, 2))

        close_btn = tk.Label(
            frame,
            text="✕",
            font=("Segoe UI", 8),
            bg="#1e1e2e",
            fg="#6c7086",
            cursor="hand2",
        )
        close_btn.pack(anchor="e")
        close_btn.bind("<Button-1>", lambda _: self._close())

        # Position: offset slightly from cursor so it doesn't cover text
        root.update_idletasks()
        w = root.winfo_reqwidth()
        h = root.winfo_reqheight()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()

        pos_x = min(x + 12, screen_w - w - 10)
        pos_y = min(y + 20, screen_h - h - 10)
        root.geometry(f"+{pos_x}+{pos_y}")

        # Auto-close after duration
        root.after(self._duration_ms, self._close)

        root.mainloop()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _close(self) -> None:
        if self._root is not None:
            try:
                self._root.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._root = None


def show_tooltip(
    translations: dict[str, str],
    x: int,
    y: int,
    duration_ms: int = 4000,
    examples: list[str] | None = None,
) -> None:
    """Convenience function — creates a Tooltip and shows it immediately."""
    Tooltip(translations, duration_ms, examples).show(x, y)
