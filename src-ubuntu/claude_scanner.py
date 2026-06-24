"""Claude Code session scanner — detects sessions that started before AI Light.

When AI Light launches after Claude Code is already running, the session-start
hook event has already been sent and lost.  This scanner reads the JSONL
session logs under ``~/.claude/projects/`` to discover recently-active
sessions and register them with the aggregator.

Each project directory is named after the encoded working directory path.
Session files are ``<session-id>.jsonl``.  A session is considered "active"
if its JSONL file was modified within the last ``ACTIVE_THRESHOLD`` seconds
(5 minutes by default).  The scanner reads the last few lines of each active
file to determine the current status (Working if the last line is an
assistant response, Done if the last message has stop_reason="end_turn",
Error if there's a permission block, or Idle as fallback).
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Optional, Tuple

from logging_util import append_log
from model import Status, Tool

ACTIVE_THRESHOLD = 5 * 60  # session file modified within 5 min → active


def _claude_projects_dir() -> str:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    return os.path.join(home, ".claude", "projects")


def _find_real_path(encoded: str) -> Optional[str]:
    """Reverse Claude's project directory encoding to find the real filesystem
    path.  Claude replaces ``/`` with ``-`` in the path, but original hyphens
    in directory names also become ``-`` (lossy encoding).  We recover the real
    path by testing candidate directory paths on the filesystem, greedily
    matching the longest valid prefix at each step.
    """
    if not encoded.startswith("-"):
        return None

    parts = encoded[1:].split("-")
    if len(parts) < 2:
        return None

    # The first two segments are always /home/<user> (no hyphens in typical
    # Linux usernames or "home").
    base = "/" + parts[0] + "/" + parts[1]
    if not os.path.isdir(base):
        return None

    # Remaining encoded text after "/home/<user>-"
    skip = len(parts[0]) + len(parts[1]) + 2  # 2 for the two slashes
    remaining = encoded[skip + 1:]  # +1 for the '-' separator we consumed

    return _resolve_remaining(base, remaining) if remaining else base


def _resolve_remaining(base: str, remaining: str) -> Optional[str]:
    """Recursively resolve the rest of the encoded path by trying both
    ``/`` (segment boundary) and ``-`` (hyphen within a segment name) at
    each dash position, checking against the real filesystem.
    """
    if not remaining:
        return base if os.path.isdir(base) else None

    # Try progressively longer segments (treating initial '-' as name chars)
    # until we find a real directory.
    dash_pos = remaining.find("-")
    if dash_pos == -1:
        # No more dashes — the whole remainder is one segment.
        candidate = os.path.join(base, remaining)
        return candidate if os.path.isdir(candidate) else None

    # First try: treat the dash as a path separator (/)
    segment = remaining[:dash_pos]
    rest = remaining[dash_pos + 1:]
    candidate = os.path.join(base, segment)
    if os.path.isdir(candidate):
        result = _resolve_remaining(candidate, rest)
        if result is not None:
            return result

    # Second try: the dash is part of the current segment name (original
    # hyphen in the directory name).  Extend the segment to include more
    # characters past each subsequent dash until we hit a real directory.
    pos = dash_pos + 1
    while pos <= len(remaining):
        next_dash = remaining.find("-", pos)
        if next_dash == -1:
            # Last segment attempt — use the entire remainder.
            candidate = os.path.join(base, remaining)
            if os.path.isdir(candidate):
                return candidate
            break
        segment = remaining[:next_dash]
        rest = remaining[next_dash + 1:]
        candidate = os.path.join(base, segment)
        if os.path.isdir(candidate):
            result = _resolve_remaining(candidate, rest)
            if result is not None:
                return result
        pos = next_dash + 1

    return None


def scan_active_sessions() -> List[Tuple[str, str, Status]]:
    """Return ``[(session_id, cwd, status), ...]`` for recently-active Claude
    sessions whose JSONL files were modified within ``ACTIVE_THRESHOLD``.
    """
    projects_dir = _claude_projects_dir()
    if not os.path.isdir(projects_dir):
        return []

    results: List[Tuple[str, str, Status]] = []
    now = time.time()

    for entry in os.listdir(projects_dir):
        project_path = os.path.join(projects_dir, entry)
        if not os.path.isdir(project_path):
            continue

        cwd = _find_real_path(entry)
        if cwd is None:
            # Can't reverse the encoding — skip this project.
            continue

        for name in os.listdir(project_path):
            if not name.endswith(".jsonl"):
                continue
            session_id = name[:-6]  # strip ".jsonl" (6 chars)
            filepath = os.path.join(project_path, name)
            try:
                mtime = os.path.getmtime(filepath)
            except OSError:
                continue
            if now - mtime > ACTIVE_THRESHOLD:
                continue
            status = _infer_status(filepath)
            results.append((session_id, cwd, status))

    return results


def _infer_status(filepath: str) -> Status:
    """Read the tail of a JSONL session file to infer current status.

    Strategy: scan the last ~50 lines, looking for:
      - ``stop_reason: "end_turn"`` → Done
      - ``type: "user"`` → Working (last action was user prompt)
      - ``type: "assistant"`` with tool_use → Working
      - ``type: "assistant"`` with no tool and stop_reason → Done
      - ``subtype: "permission"`` → Error
      Fallback: Idle
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            lines = f.readlines()
    except OSError:
        return Status.Idle

    last_assistant_stop = None
    has_permission_block = False

    for line in reversed(lines):
        try:
            data = json.loads(line.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue

        msg_type = data.get("type", "")

        if msg_type == "system":
            subtype = data.get("subtype", "")
            if subtype == "permission":
                has_permission_block = True
                break

        if msg_type == "assistant":
            message = data.get("message") or {}
            stop_reason = message.get("stop_reason")
            content = message.get("content") or []
            has_tool_use = any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                for b in (content if isinstance(content, list) else [])
            )
            if has_tool_use:
                return Status.Working
            if stop_reason in ("end_turn", "stop", "tool_use"):
                last_assistant_stop = stop_reason
                continue

        if msg_type == "user":
            return Status.Working

    if has_permission_block:
        return Status.Error
    if last_assistant_stop in ("end_turn", "stop"):
        return Status.Done
    return Status.Idle


def register_existing_sessions(aggregator) -> int:
    """Scan for and register Claude sessions that started before AI Light.

    Returns the number of sessions registered.
    """
    sessions = scan_active_sessions()
    count = 0
    for session_id, cwd, status in sessions:
        aggregator.add_session(session_id, Tool.ClaudeCode, cwd, status)
        append_log(
            f"claude_scanner: registered existing session {session_id} "
            f"for project {cwd} with status {status.name}"
        )
        count += 1
    if count:
        append_log(f"claude_scanner: found {count} active Claude session(s)")
    return count
