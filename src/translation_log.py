"""
Translation log writer.

Appends every tooltip shown to a plain-text log file.

Format per entry
----------------
[2026-02-27 14:32:01]  (de → fr, es)
  Original : Guten Morgen
  fr       : Bonjour
  es       : Buenos días
"""

import os
from datetime import datetime

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "translations.log"
)


def _read_tail_text(log_path: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read()
        return data.decode("utf-8", errors="ignore")
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def recent_originals(log_path: str, max_entries: int = 10, max_bytes: int = 256_000) -> list[str]:
    """Return up to *max_entries* most recent Original strings in the log.

    Best-effort parser for the plain-text log format written by `log()`.
    Reads only the last *max_bytes* bytes for efficiency.
    """
    text = _read_tail_text(log_path, max_bytes=max_bytes)
    if not text:
        return []

    lines = text.splitlines()
    originals: list[str] = []
    prefix = "  Original : "

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(prefix):
            original = line[len(prefix):]
            j = i + 1
            # Handle multi-line originals: continuation lines appear as raw
            # lines until the next indented field (translations/examples) or
            # a blank separator.
            while j < len(lines):
                nxt = lines[j]
                if nxt == "":
                    break
                if nxt.startswith("  "):
                    break
                original += "\n" + nxt
                j += 1
            originals.append(original)
            i = j
            continue
        i += 1

    return originals[-max_entries:] if max_entries > 0 else []


def is_recent_duplicate(original: str, log_path: str, max_entries: int = 10) -> bool:
    """True if *original* appears in the last *max_entries* log entries."""
    if not original:
        return False
    try:
        recent = recent_originals(log_path, max_entries=max_entries)
        return original in recent
    except Exception:
        return False


def log(
    original: str,
    source: str,
    translations: dict[str, str],
    log_path: str = _DEFAULT_PATH,
    examples: list[str] | None = None,
) -> None:
    """Append one translation event to *log_path*."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        targets_str = ", ".join(translations.keys())
        lines = [
            f"[{timestamp}]  ({source} → {targets_str})",
            f"  Original : {original}",
        ]
        for lang, translated in translations.items():
            lines.append(f"  {lang:<9}: {translated}")
        if examples:
            lines.append("  Examples :")
            for i, sentence in enumerate(examples, 1):
                lines.append(f"    {i}. {sentence}")
        lines.append("")  # blank separator between entries

        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[log] Could not write to log file: {exc}")
