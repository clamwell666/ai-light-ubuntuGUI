"""Claude Code hook installer — Python port of ``src-tauri/src/hook_installer.rs``.

Merges AI Light hooks into ``~/.claude/settings.json`` using the
``command + args`` form (avoids shell path-escaping issues). The command
points at ``~/.ai_light/bin/ai-light-hook``. On Ubuntu that binary is the
Python shim shipped beside this module (``ai_light_hook``) when the Rust
binary is not already present.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import List, Tuple

# (Claude Code hook event, normalized event arg)
HOOK_EVENTS: List[Tuple[str, str]] = [
    ("SessionStart", "session-start"),
    ("UserPromptSubmit", "prompt-submit"),
    ("PreToolUse", "pre-tool-use"),
    ("PermissionRequest", "permission-request"),
    ("PostToolUse", "post-tool-use"),
    ("Notification", "notification"),
    ("Stop", "stop"),
    ("SessionEnd", "session-end"),
]


def home_dir():
    return os.environ.get("USERPROFILE") or os.environ.get("HOME") or "."


def get_claude_settings_path() -> str:
    return os.path.join(home_dir(), ".claude", "settings.json")


def hook_binary_name() -> str:
    return "ai-light-hook.exe" if os.name == "nt" else "ai-light-hook"


def get_hook_binary_path() -> str:
    return os.path.join(home_dir(), ".ai_light", "bin", hook_binary_name())


def _bundled_shim_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_light_hook")


def install_hook_shim() -> bool:
    """Copy the Python hook shim to ~/.ai_light/bin/ai-light-hook if missing.

    Returns True if the shim was (re)installed. The Rust binary, if present,
    is left untouched and preferred.
    """
    dest = get_hook_binary_path()
    if os.path.exists(dest):
        # Assume an existing binary (Rust or earlier shim) is fine.
        return False
    source = _bundled_shim_path()
    if not os.path.exists(source):
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(source, dest)
    os.chmod(dest, 0o755)
    return True


def install_hook_binary_from_resource() -> bool:
    """Match the Rust API name; on Ubuntu this installs the Python shim."""
    return install_hook_shim()


def merge_hooks(existing, hook_path: str):
    if not isinstance(existing, dict):
        raise ValueError("settings root must be a JSON object")
    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings hooks field must be a JSON object")

    command_path = hook_path
    for claude_event, hook_event in HOOK_EVENTS:
        entries = hooks.setdefault(claude_event, [])
        if not isinstance(entries, list):
            raise ValueError(f"settings hooks.{claude_event} field must be an array")
        entries[:] = [entry for entry in entries if not _entry_contains_ai_light_hook(entry)]
        entries.append({
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": command_path,
                "args": [hook_event],
            }],
        })
    return existing


def install_hooks() -> None:
    settings_path = get_claude_settings_path()
    # Ensure a hook binary exists — install the Python shim if nothing is present.
    if not os.path.exists(get_hook_binary_path()):
        if not install_hook_shim():
            raise RuntimeError(f"hook binary not found and shim unavailable: {get_hook_binary_path()}")
    hook_path = get_hook_binary_path()

    existing = _read_settings(settings_path) if os.path.exists(settings_path) else {}
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    if os.path.exists(settings_path):
        shutil.copyfile(settings_path, settings_path + ".bak")
    merged = merge_hooks(existing, hook_path)
    _write_settings(settings_path, merged)


def remove_hooks() -> None:
    settings_path = get_claude_settings_path()
    if os.path.exists(settings_path):
        existing = _read_settings(settings_path)
        cleaned = remove_ai_light_hooks(existing)
        shutil.copyfile(settings_path, settings_path + ".ai-light-remove.bak")
        _write_settings(settings_path, cleaned)
    hook_path = get_hook_binary_path()
    if os.path.exists(hook_path):
        os.remove(hook_path)


def preview_hook_config() -> str:
    existing = _read_settings(get_claude_settings_path()) if os.path.exists(get_claude_settings_path()) else {}
    merged = merge_hooks(existing, get_hook_binary_path())
    return json.dumps(merged, indent=2, ensure_ascii=False)


def check_hooks_installed() -> bool:
    if not os.path.exists(get_claude_settings_path()):
        return False
    try:
        with open(get_claude_settings_path(), "r", encoding="utf-8-sig") as handle:
            settings = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    return all(
        _entries_have_ai_light_for_event(hooks.get(claude_event), hook_event)
        for claude_event, hook_event in HOOK_EVENTS
    )


def remove_ai_light_hooks(existing):
    if not isinstance(existing, dict):
        raise ValueError("settings root must be a JSON object")
    hooks = existing.get("hooks")
    if not isinstance(hooks, dict):
        return existing
    for event_name in list(hooks.keys()):
        entries = hooks.get(event_name)
        if not isinstance(entries, list):
            continue
        entries[:] = [entry for entry in entries if not _entry_contains_ai_light_hook(entry)]
        if not entries:
            hooks.pop(event_name, None)
    return existing


# --- helpers ---------------------------------------------------------------

def _entry_contains_ai_light_hook(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    commands = entry.get("hooks")
    if not isinstance(commands, list):
        return False
    return any(
        isinstance(cmd, dict)
        and isinstance(cmd.get("command"), str)
        and "ai-light-hook" in cmd["command"]
        for cmd in commands
    )


def _entries_have_ai_light_for_event(entries, hook_event: str) -> bool:
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        commands = entry.get("hooks")
        if not isinstance(commands, list):
            continue
        for cmd in commands:
            if not isinstance(cmd, dict):
                continue
            command = cmd.get("command")
            if not isinstance(command, str) or hook_binary_name() not in command:
                continue
            args = cmd.get("args")
            if isinstance(args, list) and any(a == hook_event for a in args):
                return True
            if isinstance(command, str) and hook_event in command:
                return True
    return False


def _read_settings(path: str):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _write_settings(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
