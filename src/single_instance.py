"""Cross-platform single-instance guard.

Uses a lock file in the OS temp directory.

- Windows: msvcrt.locking
- macOS/Linux: fcntl.flock

Keep the returned file handle open for the lifetime of the process.
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import IO


def acquire(app_id: str) -> IO[str] | None:
    """Acquire a non-blocking lock for *app_id*.

    Returns an open file handle if the lock is acquired, else None.
    """

    lock_path = os.path.join(tempfile.gettempdir(), f"{app_id}.lock")

    # Ensure the directory exists (temp should, but be defensive).
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)

    f = open(lock_path, "a+", encoding="utf-8")

    try:
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                f.close()
                return None
        else:
            import fcntl

            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                return None

        # Record PID for debugging/inspection.
        try:
            f.seek(0)
            f.truncate(0)
            f.write(str(os.getpid()))
            f.flush()
        except Exception:
            pass

        return f
    except Exception:
        try:
            f.close()
        except Exception:
            pass
        return None
