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
