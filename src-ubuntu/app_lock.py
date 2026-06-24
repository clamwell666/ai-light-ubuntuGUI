"""Single-instance lock — Python port of ``src-tauri/src/app_lock.rs``.

Uses an exclusive ``fcntl`` lock on ``~/.ai_light/ai-light.lock``. Combined with
the HTTP ``/health`` probe in :func:`existing_instance_is_healthy`, launching the
GUI a second time exits immediately when the first instance is alive.
"""
from __future__ import annotations

import errno
import fcntl
import os
from typing import Optional

from config import get_lock_path


class AppLock:
    """Exclusive file lock held for the lifetime of the process."""

    def __init__(self, handle) -> None:
        self._handle = handle

    @classmethod
    def acquire(cls) -> Optional["AppLock"]:
        lock_path = get_lock_path()
        parent = os.path.dirname(lock_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        handle = open(lock_path, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
        except OSError as error:
            handle.close()
            if error.errno in (errno.EAGAIN, errno.EACCES):
                return None
            raise
        return cls(handle)

    def release(self) -> None:
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
