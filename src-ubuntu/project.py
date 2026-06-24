"""Project identification — Python port of ``src-tauri/src/project.rs``.

Resolves a working directory to ``(project_id, project_label)`` where the id is
the git root (or canonicalized cwd) and the label is the declared project name
(tauri.conf.json → package.json → Cargo.toml → pyproject.toml → go.mod) or the
final directory component as fallback.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional, Tuple

try:
    import tomllib as _toml  # Python 3.11+
    _TOMLI_FALLBACK = None
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    try:
        import tomli as _toml  # type: ignore
        _TOMLI_FALLBACK = None
    except ModuleNotFoundError:
        _toml = None
        _TOMLI_FALLBACK = "toml"  # fall back to the `toml` package if present


def identify_project(cwd) -> Tuple[str, str]:
    """Return ``(project_id, project_label)`` for a working directory."""
    cwd = os.fspath(cwd)
    project_path = find_git_root(cwd) or normalize_path(cwd)
    project_id = display_path(project_path)
    project_label = _project_label(project_path)
    return project_id, project_label


def find_git_root(cwd: str) -> Optional[str]:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    root = output.strip()
    if not root:
        return None
    return normalize_path(root)


def normalize_path(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def _project_label(project_path: str) -> str:
    return (
        _declared_project_name(project_path)
        or _fallback_project_label(project_path)
    )


def _declared_project_name(project_path: str) -> Optional[str]:
    return (
        _tauri_product_name(project_path)
        or _package_json_name(project_path)
        or _cargo_package_name(project_path)
        or _pyproject_name(project_path)
        or _go_module_name(project_path)
    )


def _non_empty(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _tauri_product_name(project_path: str) -> Optional[str]:
    config_path = os.path.join(project_path, "src-tauri", "tauri.conf.json")
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return _non_empty(value.get("productName"))


def _package_json_name(project_path: str) -> Optional[str]:
    try:
        with open(os.path.join(project_path, "package.json"), "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return _non_empty(value.get("name"))


def _cargo_package_name(project_path: str) -> Optional[str]:
    return _toml_field(os.path.join(project_path, "Cargo.toml"), ("package", "name"))


def _pyproject_name(project_path: str) -> Optional[str]:
    return _toml_field(os.path.join(project_path, "pyproject.toml"), ("project", "name"))


def _toml_field(path: str, keys: Tuple[str, ...]) -> Optional[str]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            data = _toml.load(handle) if _toml else _toml_legacy_load(path)
    except (OSError, Exception):
        return None
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return _non_empty(cur if isinstance(cur, str) else None)


def _toml_legacy_load(path: str):  # pragma: no cover
    import toml as _tomllib_legacy  # type: ignore

    with open(path, "r", encoding="utf-8") as handle:
        return _tomllib_legacy.load(handle)


def _go_module_name(project_path: str) -> Optional[str]:
    try:
        with open(os.path.join(project_path, "go.mod"), "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("module "):
            module = line[len("module "):].strip()
            tail = module.rsplit("/", 1)[-1]
            return _non_empty(tail)
    return None


def _fallback_project_label(project_path: str) -> str:
    return os.path.basename(project_path.rstrip(os.sep)) or "unknown"


def display_path(path: str) -> str:
    return _strip_windows_verbatim_prefix(path)


def _strip_windows_verbatim_prefix(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[len("\\\\?\\UNC\\"):]
    if path.startswith("\\\\?\\"):
        return path[len("\\\\?\\"):]
    return path
