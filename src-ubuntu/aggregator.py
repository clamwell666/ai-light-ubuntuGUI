"""Session/light aggregation — Python port of ``src-tauri/src/aggregator.rs``.

Thread-safe (a single ``threading.Lock`` guards all state, mirroring the Rust
``RwLock``). Aggregation picks the max-severity status across sessions. Lights
preserve insertion order. An ``on_change`` callback is fired on every mutation
so the GUI can refresh.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

from model import LightState, SessionRef, Status, Tool


class StateAggregator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lights: Dict[str, LightState] = {}
        self._session_to_project: Dict[str, str] = {}
        self._light_order: List[str] = []
        self._on_change: Optional[Callable[[], None]] = None

    # --- change notification ------------------------------------------------
    def set_on_change(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._on_change = callback

    def _notify(self) -> None:
        # Snapshot callback under lock, invoke outside to avoid reentrancy.
        with self._lock:
            callback = self._on_change
        if callback:
            callback()

    # --- session lifecycle --------------------------------------------------
    def add_session(self, session_id: str, tool: Tool, cwd: str, status: Status) -> None:
        from project import identify_project

        with self._lock:
            self._remove_existing_session(session_id)
            project_id, project_label = identify_project(cwd)
            if project_id not in self._lights:
                self._light_order.append(project_id)
            light = self._lights.get(project_id)
            if light is None:
                light = LightState(project_id, project_label)
                self._lights[project_id] = light
            light.sessions.append(
                SessionRef(session_id=session_id, tool=tool, status=status)
            )
            light.last_event_at = time.monotonic()
            light.aggregate_status()
            self._session_to_project[session_id] = project_id
        self._notify()

    def update_session_status(self, session_id: str, new_status: Status) -> None:
        changed = False
        with self._lock:
            project_id = self._session_to_project.get(session_id)
            if project_id is None:
                return
            light = self._lights.get(project_id)
            if light is None:
                return
            for session in light.sessions:
                if session.session_id == session_id:
                    session.status = new_status
                    light.last_event_at = time.monotonic()
                    light.aggregate_status()
                    changed = True
                    break
        if changed:
            self._notify()

    def session_status(self, session_id: str) -> Optional[Status]:
        with self._lock:
            project_id = self._session_to_project.get(session_id)
            if project_id is None:
                return None
            light = self._lights.get(project_id)
            if light is None:
                return None
            for session in light.sessions:
                if session.session_id == session_id:
                    return session.status
            return None

    def remove_session(self, session_id: str) -> None:
        changed = False
        with self._lock:
            project_id = self._session_to_project.pop(session_id, None)
            if project_id is None:
                return
            light = self._lights.get(project_id)
            if light is not None:
                light.sessions = [s for s in light.sessions if s.session_id != session_id]
                light.last_event_at = time.monotonic()
                if not light.sessions:
                    self._remove_light_by_project(project_id)
                else:
                    light.aggregate_status()
            changed = True
        if changed:
            self._notify()

    def confirm_light(self, project_id: str) -> None:
        changed = False
        with self._lock:
            light = self._lights.get(project_id)
            if light is None:
                return
            if light.status == Status.Done:
                self._remove_light_by_project(project_id)
                changed = True
            elif light.status == Status.Error:
                if not light.sessions:
                    self._remove_light_by_project(project_id)
                    changed = True
                else:
                    for session in light.sessions:
                        if session.status == Status.Error:
                            session.status = Status.Idle
                            changed = True
                    if changed:
                        light.last_event_at = time.monotonic()
                        light.aggregate_status()
        if changed:
            self._notify()

    def remove_light(self, project_id: str) -> None:
        with self._lock:
            removed = self._remove_light_by_project(project_id)
        if removed:
            self._notify()

    def set_last_tool_call(self, session_id: str, tool_call: str) -> None:
        changed = False
        with self._lock:
            project_id = self._session_to_project.get(session_id)
            if project_id is None:
                return
            light = self._lights.get(project_id)
            if light is None:
                return
            light.last_tool_call = tool_call
            light.last_event_at = time.monotonic()
            changed = True
        if changed:
            self._notify()

    def get_lights(self) -> List[LightState]:
        with self._lock:
            return [self._lights[pid] for pid in self._light_order if pid in self._lights]

    def get_lights_json(self) -> List[dict]:
        with self._lock:
            return [self._lights[pid].to_json() for pid in self._light_order if pid in self._lights]

    # --- internals ----------------------------------------------------------
    def _remove_existing_session(self, session_id: str) -> None:
        """Caller must hold the lock."""
        project_id = self._session_to_project.pop(session_id, None)
        if project_id is None:
            return
        light = self._lights.get(project_id)
        if light is None:
            return
        light.sessions = [s for s in light.sessions if s.session_id != session_id]
        if not light.sessions:
            self._remove_light_by_project(project_id)
        else:
            light.aggregate_status()

    def _remove_light_by_project(self, project_id: str) -> bool:
        """Caller must hold the lock. Returns True if a light was removed."""
        light = self._lights.pop(project_id, None)
        if light is None:
            return False
        for session in light.sessions:
            self._session_to_project.pop(session.session_id, None)
        self._light_order = [p for p in self._light_order if p != project_id]
        return True
