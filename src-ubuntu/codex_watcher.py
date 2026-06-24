"""Codex session watcher — Python port of ``src-tauri/src/codex_watcher.rs``.

Tails ``rollout-*.jsonl`` files under ``~/.codex/sessions`` by byte offset,
parsing each JSON line into a session/status/tool-call event. Existing files
seen on the first poll are baselined (history not replayed). Stale Working
sessions flip to Error after 10 minutes; fully inactive non-Working sessions
are removed after 15 minutes — matching the Rust constants.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from logging_util import append_log
from model import Status, Tool

POLL_INTERVAL = 1.0
STALE_WORKING_AFTER = 10 * 60
REMOVE_INACTIVE_AFTER = 15 * 60


@dataclass
class CodexSessionMeta:
    session_id: str
    cwd: str


@dataclass
class WatchedRollout:
    offset: int = 0
    meta: Optional[CodexSessionMeta] = None
    added_to_aggregator: bool = False
    last_status: Optional[Status] = None
    last_activity_at: float = field(default_factory=time.monotonic)


def start_codex_watcher(aggregator) -> None:
    thread = threading.Thread(
        target=_run, args=(aggregator,), name="ai-light-codex-watcher", daemon=True
    )
    thread.start()


def _run(aggregator) -> None:
    files: Dict[str, WatchedRollout] = {}
    baseline = True
    while True:
        try:
            _poll(aggregator, files, baseline)
        except Exception as error:  # noqa: BLE001 - watcher must survive
            append_log(f"codex_watcher: poll error: {error}")
        baseline = False
        time.sleep(POLL_INTERVAL)


def _poll(aggregator, files: Dict[str, WatchedRollout], baseline: bool) -> None:
    root = _codex_sessions_dir()
    _poll_root(aggregator, files, baseline, root)


def _poll_root(aggregator, files, baseline, root) -> None:
    rollouts = _find_rollout_files(root)
    live = set(rollouts)
    for path in list(files.keys()):
        if path not in live:
            files.pop(path, None)

    for path in rollouts:
        if path in files:
            _process_new_lines(aggregator, files, path)
            watched = files.get(path)
            if watched is not None:
                _update_inactive(aggregator, watched, path)
            continue

        watched = WatchedRollout()
        if baseline:
            _initialize_existing(path, watched)
        files[path] = watched
        if not baseline:
            _process_new_lines(aggregator, files, path)
        watched = files.get(path)
        if watched is not None:
            _update_inactive(aggregator, watched, path)


def _initialize_existing(path: str, watched: WatchedRollout) -> None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                event = _parse_line(line)
                if isinstance(event, _Meta) and watched.meta is None:
                    watched.meta = event.meta
        watched.offset = os.path.getsize(path)
    except OSError:
        pass


def _process_new_lines(aggregator, files, path: str) -> None:
    watched = files.get(path)
    if watched is None:
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            handle.seek(watched.offset)
            for line in handle:
                # Incomplete trailing line — retry next poll.
                if not line.endswith("\n"):
                    break
                event = _parse_line(line)
                _apply_event(aggregator, watched, event)
            watched.offset = handle.tell()
    except OSError:
        pass


def _apply_event(aggregator, watched: WatchedRollout, event) -> None:
    if isinstance(event, _Meta):
        if not watched.added_to_aggregator:
            aggregator.add_session(
                event.meta.session_id, Tool.Codex, event.meta.cwd, Status.Idle
            )
            watched.added_to_aggregator = True
            watched.last_status = Status.Idle
        watched.last_activity_at = time.monotonic()
        watched.meta = event.meta
    elif isinstance(event, _Status):
        meta = watched.meta
        if meta is None:
            return
        if not watched.added_to_aggregator:
            aggregator.add_session(meta.session_id, Tool.Codex, meta.cwd, event.status)
            watched.added_to_aggregator = True
        else:
            aggregator.update_session_status(meta.session_id, event.status)
        watched.last_status = event.status
        watched.last_activity_at = time.monotonic()
    elif isinstance(event, _Tool):
        if watched.meta is not None:
            aggregator.set_last_tool_call(watched.meta.session_id, event.name)
        watched.last_activity_at = time.monotonic()
    # _Ignore: no-op


def _update_inactive(aggregator, watched: WatchedRollout, path: str) -> None:
    meta = watched.meta
    if meta is None:
        return
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return
    age = time.monotonic() - mtime  # rough proxy for file quiet time
    if watched.last_status == Status.Working and age >= STALE_WORKING_AFTER:
        aggregator.update_session_status(meta.session_id, Status.Error)
        watched.last_status = Status.Error
        watched.last_activity_at = time.monotonic()
        append_log(
            f"codex_watcher: marked stale session {meta.session_id} as error "
            f"after {int(age)}s without rollout updates"
        )

    inactive_for = time.monotonic() - watched.last_activity_at
    if inactive_for >= REMOVE_INACTIVE_AFTER and watched.last_status != Status.Working:
        aggregator.remove_session(meta.session_id)
        watched.added_to_aggregator = False
        watched.last_status = None
        watched.last_activity_at = time.monotonic()
        append_log(
            f"codex_watcher: removed inactive session {meta.session_id} "
            f"after {int(inactive_for)}s without rollout events"
        )


# --- line parsing -----------------------------------------------------------

class _Meta:
    def __init__(self, meta: CodexSessionMeta) -> None:
        self.meta = meta


class _Status:
    def __init__(self, status: Status) -> None:
        self.status = status


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Ignore:
    pass


def _parse_line(line: str):
    line = line.lstrip("﻿").strip()
    if not line:
        return _Ignore()
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return _Ignore()
    if not isinstance(value, dict):
        return _Ignore()
    line_type = value.get("type") or ""
    payload = value.get("payload") or {}

    if line_type == "session_meta":
        session_id = str(payload.get("id") or "unknown")
        cwd = payload.get("cwd") or os.getcwd()
        return _Meta(CodexSessionMeta(session_id=session_id, cwd=str(cwd)))

    if line_type == "event_msg":
        event_type = payload.get("type") or ""
        if event_type in ("task_started", "agent_message"):
            return _Status(Status.Working)
        if event_type == "task_complete":
            return _Status(Status.Done)
        if event_type in ("error", "stream_error", "turn_aborted"):
            return _Status(Status.Error)
        return _Ignore()

    if line_type == "response_item":
        if payload.get("type") == "function_call":
            name = str(payload.get("name") or "tool")
            return _Tool(name)
        return _Ignore()

    return _Ignore()


def _find_rollout_files(root: str):
    files = []
    if not root or not os.path.isdir(root):
        return files
    _collect(root, files)
    files.sort()
    return files


def _collect(directory: str, files) -> None:
    try:
        entries = os.listdir(directory)
    except OSError:
        return
    for name in entries:
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            _collect(path, files)
        elif os.path.isfile(path) and _is_rollout(name):
            files.append(path)


def _is_rollout(name: str) -> bool:
    return name.startswith("rollout-") and name.endswith(".jsonl")


def _codex_sessions_dir() -> str:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or "."
    return os.path.join(home, ".codex", "sessions")
