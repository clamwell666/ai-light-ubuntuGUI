"""opencode session watcher — new, Ubuntu-specific.

opencode (https://opencode.ai) stores its sessions in a SQLite database at
``~/.local/share/opencode/opencode.db`` using an event-sourced ``event`` table
(``session.created.1``, ``message.updated.1``, ``message.part.updated.1`` …).
It has no Claude-style lifecycle hook config, so like Codex we *watch* the
event log and drive the aggregator.

The watcher tails the ``event`` table by ``rowid`` (insertion order), parses
new rows per session (``aggregate_id`` = ``ses_…``), and infers status:

  session.created            -> Idle (new session)
  message.updated role=user  -> Working (prompt submitted)
  message.updated/.part role=assistant -> Working (streaming)
  quiet for ``DONE_QUIET_AFTER`` (8s) while Working -> Done
  stale Working 10min        -> Error
  inactive non-Working 15min -> remove
  session.time_archived set  -> remove

The DB is opened read-only so the running opencode process is never blocked.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from logging_util import append_log
from model import Status, Tool

POLL_INTERVAL = 1.0
DONE_QUIET_AFTER = 8.0           # Working -> Done when no events for this long
STALE_WORKING_AFTER = 10 * 60   # Working -> Error
REMOVE_INACTIVE_AFTER = 15 * 60  # idle sessions removed


@dataclass
class OpencodeSession:
    session_id: str
    cwd: Optional[str] = None
    added: bool = False
    last_status: Optional[Status] = None
    last_activity_at: float = field(default_factory=time.monotonic)


def start_opencode_watcher(aggregator) -> None:
    thread = threading.Thread(
        target=_run, args=(aggregator,), name="ai-light-opencode-watcher", daemon=True
    )
    thread.start()


def _run(aggregator) -> None:
    sessions: Dict[str, OpencodeSession] = {}
    last_rowid = 0
    # Baseline: start after the current max rowid so we don't replay history.
    db = _db_path()
    if db:
        try:
            con = _open_ro(db)
            cur = con.execute("SELECT MAX(rowid) FROM event")
            row = cur.fetchone()
            if row and row[0] is not None:
                last_rowid = int(row[0])
            con.close()
        except sqlite3.Error as error:
            append_log(f"opencode_watcher: baseline failed: {error}")

    while True:
        try:
            last_rowid = _poll(aggregator, sessions, last_rowid)
            _reap_inactive(aggregator, sessions)
            _reap_archived(aggregator, sessions)
        except Exception as error:  # noqa: BLE001 - watcher must survive
            append_log(f"opencode_watcher: poll error: {error}")
        time.sleep(POLL_INTERVAL)


def _poll(aggregator, sessions: Dict[str, OpencodeSession], last_rowid: int) -> int:
    db = _db_path()
    if not db or not os.path.exists(db):
        return last_rowid
    con = _open_ro(db)
    try:
        rows = con.execute(
            "SELECT rowid, aggregate_id, seq, type, data FROM event "
            "WHERE rowid > ? ORDER BY rowid",
            (last_rowid,),
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return last_rowid

    for rowid, aggregate_id, _seq, etype, data in rows:
        last_rowid = max(last_rowid, int(rowid))
        if not aggregate_id or not aggregate_id.startswith("ses_"):
            continue
        session = sessions.setdefault(aggregate_id, OpencodeSession(session_id=aggregate_id))
        _apply_event(aggregator, session, etype, data)

    return last_rowid


def _apply_event(aggregator, session: OpencodeSession, etype: str, data) -> None:
    payload = _loads(data)
    if payload is None:
        return

    if etype == "session.created.1":
        info = payload.get("info") or {}
        cwd = info.get("directory") or info.get("path") or session.cwd
        session.cwd = cwd or os.getcwd()
        if not session.added:
            aggregator.add_session(session.session_id, Tool.Opencode, session.cwd, Status.Idle)
            session.added = True
            session.last_status = Status.Idle
        session.last_activity_at = time.monotonic()
        return

    if etype in ("message.updated.1", "message.part.updated.1"):
        info = payload.get("info") or payload.get("part") or {}
        role = info.get("role")
        # Ensure session is registered even if we missed session.created.
        if not session.added:
            session.cwd = session.cwd or _lookup_cwd(session.session_id) or os.getcwd()
            aggregator.add_session(session.session_id, Tool.Opencode, session.cwd, Status.Idle)
            session.added = True
            session.last_status = Status.Idle

        # Tool call extraction (best-effort across part shapes).
        tool = _extract_tool(info) or _extract_tool(payload.get("part") or {})
        if tool:
            aggregator.set_last_tool_call(session.session_id, tool)

        if role == "user":
            _set(aggregator, session, Status.Working)
        elif role == "assistant":
            _set(aggregator, session, Status.Working)
        # Streaming parts keep status Working; quiet->Done handled in _reap_inactive.
        session.last_activity_at = time.monotonic()


def _set(aggregator, session: OpencodeSession, status: Status) -> None:
    if session.last_status != status:
        aggregator.update_session_status(session.session_id, status)
    session.last_status = status


def _reap_inactive(aggregator, sessions: Dict[str, OpencodeSession]) -> None:
    now = time.monotonic()
    for session in list(sessions.values()):
        quiet = now - session.last_activity_at
        if session.last_status == Status.Working and quiet >= DONE_QUIET_AFTER and quiet < STALE_WORKING_AFTER:
            _set(aggregator, session, Status.Done)
        if session.last_status == Status.Working and quiet >= STALE_WORKING_AFTER:
            _set(aggregator, session, Status.Error)
            append_log(
                f"opencode_watcher: marked stale session {session.session_id} "
                f"as error after {int(quiet)}s"
            )
        if session.last_status != Status.Working and quiet >= REMOVE_INACTIVE_AFTER:
            aggregator.remove_session(session.session_id)
            sessions.pop(session.session_id, None)
            append_log(
                f"opencode_watcher: removed inactive session {session.session_id} "
                f"after {int(quiet)}s"
            )


def _reap_archived(aggregator, sessions: Dict[str, OpencodeSession]) -> None:
    if not sessions:
        return
    db = _db_path()
    if not db or not os.path.exists(db):
        return
    ids = list(sessions.keys())
    placeholders = ",".join("?" * len(ids))
    try:
        con = _open_ro(db)
        rows = con.execute(
            f"SELECT id, time_archived FROM session WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return
    for session_id, archived in rows:
        if archived:
            aggregator.remove_session(session_id)
            sessions.pop(session_id, None)


def _lookup_cwd(session_id: str) -> Optional[str]:
    db = _db_path()
    if not db or not os.path.exists(db):
        return None
    try:
        con = _open_ro(db)
        row = con.execute(
            "SELECT directory FROM session WHERE id = ?", (session_id,)
        ).fetchone()
        con.close()
    except sqlite3.Error:
        return None
    return row[0] if row and row[0] else None


def _extract_tool(node) -> Optional[str]:
    if not isinstance(node, dict):
        return None
    # Common opencode part shapes for tool calls.
    if node.get("type") == "tool":
        tool = node.get("tool")
        if isinstance(tool, dict) and tool.get("name"):
            return str(tool["name"])
        if node.get("name"):
            return str(node["name"])
    return None


def _loads(data) -> Optional[dict]:
    if not data:
        return None
    if isinstance(data, (dict, list)):
        return data if isinstance(data, dict) else None
    try:
        value = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _open_ro(db_path: str) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=2.0)
    con.execute("PRAGMA busy_timeout = 2000")
    return con


def _db_path() -> Optional[str]:
    data_home = (
        os.environ.get("XDG_DATA_HOME")
        or os.path.join(os.environ.get("HOME") or "", ".local", "share")
    )
    return os.path.join(data_home, "opencode", "opencode.db")
