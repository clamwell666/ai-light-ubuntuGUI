#!/usr/bin/env python3
"""AI Light \u2014 Ubuntu GTK3 GUI entry point.

Boots the same core services as the Tauri app (HTTP hook receiver, Codex
watcher) plus an opencode SQLite watcher, then runs the floating GTK3 window.
Wire-compatible with the Rust app: shares ``~/.ai_light/config.json``,
``runtime.json``, ``ai-light.lock``, and the ``ai-light-hook`` binary.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import aggregator as aggregator_mod  # noqa: E402
import app_lock  # noqa: E402
import claude_scanner  # noqa: E402
import codex_watcher  # noqa: E402
import config as config_mod  # noqa: E402
import hook_installer  # noqa: E402
import http_server  # noqa: E402
import opencode_watcher  # noqa: E402
from logging_util import append_log  # noqa: E402


def main() -> int:
    if http_server.existing_instance_is_healthy():
        append_log("another healthy AI Light instance is running; exiting")
        return 0

    lock = app_lock.AppLock.acquire()
    if lock is None:
        append_log("app lock held by another instance; exiting")
        return 0

    app_config = config_mod.load_app_config()
    aggregator = aggregator_mod.StateAggregator()

    try:
        http_server.start_http_server(aggregator, app_config)
    except OSError as error:
        append_log(f"failed to start http server: {error}")
        print(f"failed to start http server: {error}", file=sys.stderr)

    try:
        codex_watcher.start_codex_watcher(aggregator)
    except Exception as error:
        append_log(f"failed to start codex watcher: {error}")

    try:
        opencode_watcher.start_opencode_watcher(aggregator)
    except Exception as error:
        append_log(f"failed to start opencode watcher: {error}")

    try:
        hook_installer.install_hook_shim()
    except Exception as error:
        append_log(f"failed to install hook shim: {error}")

    # Scan for Claude Code sessions that started before AI Light —
    # their session-start hook events were lost, so we discover them
    # from their JSONL session logs instead.
    try:
        claude_scanner.register_existing_sessions(aggregator)
    except Exception as error:
        append_log(f"failed to scan existing Claude sessions: {error}")

    import window as window_mod

    window_mod.load_css()

    from settings_window import SettingsWindow

    light_window = window_mod.LightWindow(
        aggregator,
        on_settings=lambda: None,
        on_quit=lambda: Gtk.main_quit(),
    )

    settings_window = SettingsWindow(aggregator, light_window=light_window)
    settings_window.hide()

    def on_settings() -> None:
        settings_window.show_settings()

    def on_quit() -> None:
        append_log("quit requested")
        Gtk.main_quit()

    light_window._on_settings = on_settings
    light_window._on_quit = on_quit

    aggregator.set_on_change(light_window.schedule_refresh)
    GLib.timeout_add_seconds(1, light_window.schedule_refresh)

    append_log("AI Light Ubuntu GUI started")
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
