"""
Tooltip overlay window.

Shows a small, frameless, always-on-top Tkinter window positioned near
the mouse cursor with the translated text.  The window auto-closes after
*duration_ms* milliseconds.
"""

import sys
import tkinter as tk


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

        if sys.platform == "win32":
            font_small_bold = ("Segoe UI", 8, "bold")
            font_body = ("Segoe UI", 10)
            font_examples_header = ("Segoe UI", 7, "bold")
            font_example = ("Segoe UI", 9, "italic")
            font_close = ("Segoe UI", 8)
        else:
            # Use Tk defaults on macOS/Linux to avoid missing-font fallbacks.
            font_small_bold = ("TkDefaultFont", 9, "bold")
            font_body = ("TkDefaultFont", 11)
            font_examples_header = ("TkDefaultFont", 8, "bold")
            font_example = ("TkDefaultFont", 10, "italic")
            font_close = ("TkDefaultFont", 9)

        for lang, translated in self._translations.items():
            lang_label = tk.Label(
                frame,
                text=f"[{lang.upper()}]",
                font=font_small_bold,
                bg="#1e1e2e",
                fg="#cba6f7",
                anchor="w",
            )
            lang_label.pack(fill="x")

            text_label = tk.Label(
                frame,
                text=translated,
                font=font_body,
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
                font=font_examples_header,
                bg="#1e1e2e",
                fg="#a6adc8",
                anchor="w",
            )
            ex_header.pack(fill="x")

            for i, sentence in enumerate(self._examples, 1):
                ex_label = tk.Label(
                    frame,
                    text=f"{i}. {sentence}",
                    font=font_example,
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
            font=font_close,
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
