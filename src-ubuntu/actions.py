"""Shared UI helpers — open paths, clipboard, diagnostics text.

Mirrors the right-click menu actions and the Diagnostics payload from
``src-tauri/src/ipc.rs`` (plus an ``opencode_db_path`` field for the Ubuntu
opencode watcher).
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

import config as config_mod
import hook_installer
import opencode_watcher


def home_dir() -> Optional[str]:
    return os.environ.get("USERPROFILE") or os.environ.get("HOME")


def open_path(path: str) -> None:
    """Open a path in the platform's default file manager / app."""
    opener = _platform_opener()
    if opener:
        try:
            subprocess.Popen([opener, path])
        except OSError:
            pass


def _platform_opener() -> Optional[str]:
    if os.name == "nt":
        return "explorer"
    if sys_platform() == "darwin":
        return "open"
    return "xdg-open"


def sys_platform() -> str:
    import sys

    return sys.platform


def copy_to_clipboard(text: str) -> None:
    try:
        from gi.repository import Gdk, Gtk
    except ImportError:
        return
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard.set_text(text, -1)
    clipboard.store()


def claude_project_log_dir(project_id: str) -> str:
    home = home_dir() or "."
    encoded = (
        project_id.replace("\\\\?\\", "")
        .replace(":", "")
        .replace("\\", "-")
        .replace("/", "-")
    )
    return os.path.join(home, ".claude", "projects", encoded)


def codex_sessions_dir() -> str:
    home = home_dir() or "."
    return os.path.join(home, ".codex", "sessions")


def opencode_db_path() -> str:
    return opencode_watcher._db_path() or ""


def build_diagnostics_text(aggregator) -> str:
    log_path = config_mod.get_log_path()
    hook_binary_path = hook_installer.get_hook_binary_path()
    lines = [
        "AI Light Diagnostics",
        "",
        f"Config dir: {config_mod.get_config_dir()}",
        f"Runtime: {config_mod.get_runtime_path()}",
        f"Lock: {config_mod.get_lock_path()}",
        f"Log: {log_path}",
        f"Claude settings: {hook_installer.get_claude_settings_path()}",
        f"Hook binary: {hook_binary_path}",
        f"Codex sessions: {codex_sessions_dir()}",
        f"opencode DB: {opencode_db_path()}",
        "",
        f"Hooks installed: {hook_installer.check_hooks_installed()}",
        f"Hook binary exists: {os.path.exists(hook_binary_path)}",
        f"Runtime exists: {os.path.exists(config_mod.get_runtime_path())}",
        f"Light count: {len(aggregator.get_lights())}",
        "",
        "Recent log:",
        _recent_log(log_path) or "(empty)",
    ]
    return "\n".join(lines)


def _recent_log(log_path: str) -> str:
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return ""
    return "".join(lines[-20:]).rstrip()
