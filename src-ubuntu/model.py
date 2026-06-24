from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional
import time


class Status(IntEnum):
    Idle = 0
    Done = 1
    Working = 2
    Error = 3


class Tool(IntEnum):
    ClaudeCode = 0
    Codex = 1
    Opencode = 2

    @property
    def badge(self) -> str:
        return {
            Tool.ClaudeCode: "CC",
            Tool.Codex: "CX",
            Tool.Opencode: "OC",
        }[self]

    @property
    def label(self) -> str:
        return {
            Tool.ClaudeCode: "Claude Code",
            Tool.Codex: "Codex",
            Tool.Opencode: "opencode",
        }[self]


def composite_key(project_id: str, tool: Tool) -> str:
    return f"{project_id}|{tool.value}"


@dataclass
class SessionRef:
    session_id: str
    tool: Tool
    status: Status
    started_at: float = field(default_factory=time.monotonic)

    def to_json(self) -> dict:
        return {
            "session_id": self.session_id,
            "tool": int(self.tool),
            "status": int(self.status),
        }


@dataclass
class LightState:
    project_id: str
    project_label: str
    tool: Tool
    status: Status = Status.Idle
    sessions: List[SessionRef] = field(default_factory=list)
    last_event_at: float = field(default_factory=time.monotonic)
    last_tool_call: Optional[str] = None

    def __init__(self, project_id: str, project_label: str, tool: Tool) -> None:
        self.project_id = project_id
        self.project_label = project_label
        self.tool = tool
        self.status = Status.Idle
        self.sessions: List[SessionRef] = []
        self.last_event_at = time.monotonic()
        self.last_tool_call = None

    @property
    def key(self) -> str:
        return composite_key(self.project_id, self.tool)

    def aggregate_status(self) -> None:
        if self.sessions:
            self.status = max(session.status for session in self.sessions)
        else:
            self.status = Status.Idle

    def to_json(self) -> dict:
        return {
            "project_id": self.project_id,
            "project_label": self.project_label,
            "tool": int(self.tool),
            "status": int(self.status),
            "sessions": [session.to_json() for session in self.sessions],
            "last_tool_call": self.last_tool_call,
        }


STATUS_NAMES = {
    Status.Idle: "Idle",
    Status.Done: "Done",
    Status.Working: "Working",
    Status.Error: "Error",
}
