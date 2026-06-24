from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

from model import LightState, SessionRef, Status, Tool, composite_key


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
            key = composite_key(project_id, tool)
            if key not in self._lights:
                self._light_order.append(key)
            light = self._lights.get(key)
            if light is None:
                light = LightState(project_id, project_label, tool)
                self._lights[key] = light
            light.sessions.append(
                SessionRef(session_id=session_id, tool=tool, status=status)
            )
            light.last_event_at = time.monotonic()
            light.aggregate_status()
            self._session_to_project[session_id] = key
        self._notify()

    def update_session_status(self, session_id: str, new_status: Status) -> None:
        changed = False
        with self._lock:
            key = self._session_to_project.get(session_id)
            if key is None:
                return
            light = self._lights.get(key)
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
            key = self._session_to_project.get(session_id)
            if key is None:
                return None
            light = self._lights.get(key)
            if light is None:
                return None
            for session in light.sessions:
                if session.session_id == session_id:
                    return session.status
            return None

    def remove_session(self, session_id: str) -> None:
        changed = False
        with self._lock:
            key = self._session_to_project.pop(session_id, None)
            if key is None:
                return
            light = self._lights.get(key)
            if light is not None:
                light.sessions = [s for s in light.sessions if s.session_id != session_id]
                light.last_event_at = time.monotonic()
                if not light.sessions:
                    self._remove_light_by_key(key)
                else:
                    light.aggregate_status()
            changed = True
        if changed:
            self._notify()

    def confirm_light(self, key: str) -> None:
        changed = False
        with self._lock:
            light = self._lights.get(key)
            if light is None:
                return
            if light.status in (Status.Done, Status.Error):
                self._remove_light_by_key(key)
                changed = True
        if changed:
            self._notify()

    def remove_light(self, key: str) -> None:
        with self._lock:
            removed = self._remove_light_by_key(key)
        if removed:
            self._notify()

    def set_last_tool_call(self, session_id: str, tool_call: str) -> None:
        changed = False
        with self._lock:
            key = self._session_to_project.get(session_id)
            if key is None:
                return
            light = self._lights.get(key)
            if light is None:
                return
            light.last_tool_call = tool_call
            light.last_event_at = time.monotonic()
            changed = True
        if changed:
            self._notify()

    def get_lights(self) -> List[LightState]:
        with self._lock:
            return [self._lights[key] for key in self._light_order if key in self._lights]

    def get_lights_json(self) -> List[dict]:
        with self._lock:
            return [self._lights[key].to_json() for key in self._light_order if key in self._lights]

    # --- internals ----------------------------------------------------------
    def _remove_existing_session(self, session_id: str) -> None:
        key = self._session_to_project.pop(session_id, None)
        if key is None:
            return
        light = self._lights.get(key)
        if light is None:
            return
        light.sessions = [s for s in light.sessions if s.session_id != session_id]
        if not light.sessions:
            self._remove_light_by_key(key)
        else:
            light.aggregate_status()

    def _remove_light_by_key(self, key: str) -> bool:
        light = self._lights.pop(key, None)
        if light is None:
            return False
        for session in light.sessions:
            self._session_to_project.pop(session.session_id, None)
        self._light_order = [k for k in self._light_order if k != key]
        return True
