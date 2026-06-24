# Changelog

## [0.2.0] - 2026-06-25

### Changed

- Removed all Rust/Tauri code (`src-tauri/`, `src-hook/`, `Cargo.toml`).
- Project now exclusively uses the Python + GTK3 Ubuntu GUI (`src-ubuntu/`).
- Each AI tool (Claude Code, Codex, opencode) now gets its own independent
  traffic light row per project, with distinct tool badges (CC/CX/OC).
- Aggregator uses composite keys `(project_id, tool)` so each tool's status
  is tracked and displayed independently.

### Added

- Settings window: window opacity slider (10% - 100%, real-time).
- Settings window: always-on-top toggle (real-time).
- Both settings persist to `~/.ai_light/config.json`.

### Removed

- `docs/BUILDING.md`, `docs/UBUNTU_HOOK_ONLY.md`, `docs/PROGRESS.md`,
  `docs/validation/`, `docs/superpowers/`.

## [0.1.0] - 2026-05-31

### Added

- Initial MVP implementation for a floating traffic-light desktop widget.
- Claude Code integration via local hooks and `ai-light-hook`.
- Codex integration via rollout JSONL session watching under `~/.codex/sessions`.
- Project-level session aggregation with idle, working, error, and done states.
- Local HTTP hook receiver with `/events` and `/health`.
- Minimal Tauri UI with traffic-light rendering, context menus, and hook install dialog.
- Stable hook binary path under `~/.ai_light/bin/`.
- Project names displayed above each light group, resolved from project metadata when available.
- Diagnostics and application log entries from the widget context menu.
- Cross-platform single-instance guard using a file lock.
- Content-based hook binary update detection.
- macOS bundle resource config for the non-`.exe` hook binary.
- Optional remote hook mode with `AI_LIGHT_URL` for sending events from SSH/Linux clients to a Windows host.
- Configurable HTTP bind address and fixed HTTP port for LAN-based monitoring.
- Ubuntu hook-only installer script for configuring Claude Code forwarding without launching a GUI.
