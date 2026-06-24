"""Configuration & runtime paths — Python port of ``src-tauri/src/config.rs``.

Byte-compatible with the Rust app: the same ``config.json`` / ``runtime.json``
files are read and written, so the Ubuntu GUI and the Tauri GUI coexist on the
same ``~/.ai_light`` directory.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

CONFIG_DIR_ENV = "AI_LIGHT_CONFIG_DIR"


def home_dir() -> Optional[str]:
    return os.environ.get("USERPROFILE") or os.environ.get("HOME")


def get_config_dir() -> str:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return override
    home = home_dir()
    if not home:
        raise RuntimeError("failed to resolve home directory")
    return os.path.join(home, ".ai_light")


def get_config_path() -> str:
    return os.path.join(get_config_dir(), "config.json")


def get_runtime_path() -> str:
    return os.path.join(get_config_dir(), "runtime.json")


def get_lock_path() -> str:
    return os.path.join(get_config_dir(), "ai-light.lock")


def get_log_path() -> str:
    return os.path.join(get_config_dir(), "ai-light.log")


@dataclass
class AppConfig:
    window_x: int = 100
    window_y: int = 100
    monitoring_paused: bool = False
    hooks_installed: bool = False
    http_bind: str = "127.0.0.1"
    http_port: Optional[int] = None

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class RuntimeConfig:
    http_port: int

    def to_json(self) -> dict:
        return {"http_port": self.http_port}


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith("﻿") else text


def load_app_config() -> AppConfig:
    path = get_config_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = _strip_bom(handle.read())
    except OSError:
        return AppConfig()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()
    # Tolerant load: pick known keys with defaults.
    return AppConfig(
        window_x=int(data.get("window_x", 100)),
        window_y=int(data.get("window_y", 100)),
        monitoring_paused=bool(data.get("monitoring_paused", False)),
        hooks_installed=bool(data.get("hooks_installed", False)),
        http_bind=str(data.get("http_bind", "127.0.0.1")),
        http_port=data.get("http_port"),
    )


def save_app_config(config: AppConfig) -> None:
    os.makedirs(get_config_dir(), exist_ok=True)
    with open(get_config_path(), "w", encoding="utf-8") as handle:
        json.dump(config.to_json(), handle, indent=2, ensure_ascii=False)


def load_runtime_config() -> Optional[RuntimeConfig]:
    try:
        with open(get_runtime_path(), "r", encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    port = data.get("http_port")
    if not isinstance(port, int):
        return None
    return RuntimeConfig(http_port=port)


def save_runtime_config(config: RuntimeConfig) -> None:
    os.makedirs(get_config_dir(), exist_ok=True)
    with open(get_runtime_path(), "w", encoding="utf-8") as handle:
        json.dump(config.to_json(), handle, indent=2, ensure_ascii=False)
