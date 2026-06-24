"""Local hook HTTP receiver — Python port of ``src-tauri/src/http_server.rs``.

Endpoints:
  GET  /health -> "ok"
  GET  /state  -> JSON array of lights
  POST /events -> parse a HookEvent, drive the aggregator

The bound port is persisted to ``runtime.json`` so the (Rust or Python)
``ai-light-hook`` binary can find this server. ``existing_instance_is_healthy``
is used at startup to exit when another live instance is already running.
"""
from __future__ import annotations

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from config import AppConfig, RuntimeConfig, load_runtime_config, save_runtime_config
from logging_util import append_log
from model import Status, Tool


# (claude hook event name, normalized event) — mirrors hook_installer.rs HOOK_EVENTS.
_EVENT_STATUS_MAP = {
    "session-start": Status.Idle,
    "prompt-submit": Status.Working,
    "pre-tool-use": Status.Working,
    "permission-request": Status.Error,
    "post-tool-use": Status.Working,
    "notification": Status.Error,
    "stop": Status.Done,
}
_LATE_EVENTS = {
    "pre-tool-use",
    "permission-request",
    "post-tool-use",
    "notification",
}


class HookEvent:
    def __init__(self, event_type: str, session_id: str,
                 cwd: Optional[str] = None, tool_call: Optional[str] = None) -> None:
        self.event_type = event_type
        self.session_id = session_id
        self.cwd = cwd
        self.tool_call = tool_call

    @staticmethod
    def from_payload(payload: dict) -> "HookEvent":
        data = payload or {}
        event_type = str(data.get("event_type") or "")
        session_id = (
            data.get("session_id")
            or data.get("sessionId")
            or "unknown"
        )
        cwd = data.get("cwd")
        tool_call = (
            data.get("tool_call")
            or data.get("tool")
            or data.get("toolName")
            or data.get("tool_name")
        )
        if cwd is not None:
            cwd = str(cwd)
        if tool_call is not None:
            tool_call = str(tool_call)
        return HookEvent(
            event_type=str(event_type),
            session_id=str(session_id),
            cwd=cwd,
            tool_call=tool_call,
        )


def existing_instance_is_healthy() -> bool:
    runtime = load_runtime_config()
    if runtime is None:
        return False
    try:
        with socket.create_connection(("127.0.0.1", runtime.http_port), timeout=0.25) as sock:
            sock.settimeout(0.25)
            sock.sendall(
                b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            response = sock.recv(4096).decode("utf-8", "replace")
    except OSError:
        return False
    return response.startswith("HTTP/1.1 200 OK")


def start_http_server(aggregator, app_config: AppConfig) -> int:
    bind = (app_config.http_bind, app_config.http_port or 0)
    server = ThreadingHTTPServer(bind, _make_handler(aggregator))
    server.daemon_threads = True
    port = server.server_address[1]
    save_runtime_config(RuntimeConfig(http_port=port))
    thread = threading.Thread(
        target=server.serve_forever, name="ai-light-http-server", daemon=True
    )
    thread.start()
    append_log(f"http server listening on {app_config.http_bind}:{port}")
    return port


def _make_handler(aggregator):
    class Handler(BaseHTTPRequestHandler):
        # Quiet logging.
        def log_message(self, *args):  # noqa: A003 - signature override
            return

        def _send(self, code: int, reason: str, body: bytes,
                  content_type: str = "text/plain; charset=utf-8") -> None:
            self.send_response(code, reason)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler convention
            if self.path == "/health":
                self._send(200, "OK", b"ok")
            elif self.path == "/state":
                body = json.dumps(aggregator.get_lights_json()).encode("utf-8")
                self._send(200, "OK", body, "application/json; charset=utf-8")
            else:
                self._send(404, "Not Found", b"not found")

        def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler convention
            if self.path != "/events":
                self._send(404, "Not Found", b"not found")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, "Bad Request", b"invalid json")
                return
            if not isinstance(payload, dict):
                self._send(400, "Bad Request", b"invalid json")
                return
            event = HookEvent.from_payload(payload)
            apply_hook_event(aggregator, event)
            self._send(200, "OK", b"ok")

    return Handler


def apply_hook_event(aggregator, event: HookEvent) -> None:
    if event.event_type == "session-start":
        cwd = event.cwd or os.getcwd()
        aggregator.add_session(event.session_id, Tool.ClaudeCode, cwd, Status.Idle)
        return
    if event.event_type == "session-end":
        aggregator.remove_session(event.session_id)
        return
    # If this event references a session we don't know about (e.g. Claude
    # Code was already running before AI Light started, so we missed the
    # session-start hook), auto-register it so subsequent events aren't
    # silently dropped.
    if aggregator.session_status(event.session_id) is None:
        cwd = event.cwd or os.getcwd()
        aggregator.add_session(event.session_id, Tool.ClaudeCode, cwd, Status.Idle)
    if _should_ignore_late_event_after_done(aggregator, event):
        return
    status = _EVENT_STATUS_MAP.get(event.event_type)
    if status is not None:
        aggregator.update_session_status(event.session_id, status)
    if event.tool_call:
        aggregator.set_last_tool_call(event.session_id, event.tool_call)


def _should_ignore_late_event_after_done(aggregator, event: HookEvent) -> bool:
    if aggregator.session_status(event.session_id) != Status.Done:
        return False
    return event.event_type in _LATE_EVENTS
