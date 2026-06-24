"""Append-only log writer — Python port of ``src-tauri/src/logging.rs``.

Writes ``<unix_seconds> <message>`` lines to ``~/.ai_light/ai-light.log``.
"""
from __future__ import annotations

import os
import time

from config import get_log_path


def append_log(message: str) -> None:
    try:
        log_path = get_log_path()
        parent = os.path.dirname(log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        timestamp = int(time.time())
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except OSError:
        pass
