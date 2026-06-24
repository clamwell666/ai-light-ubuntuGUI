# Ubuntu GUI for AI Light

Last updated: 2026-06-25

The Ubuntu GUI is a native **Python + GTK3** port of the Tauri/Rust desktop widget.
It runs on this machine with **no Rust toolchain, no `sudo`, and no
`webkit2gtk` dev headers** — only `python3-gi`, which ships with Ubuntu. It is
**wire-compatible** with the existing Windows/macOS Tauri app: both share
`~/.ai_light/config.json`, `runtime.json`, `ai-light.lock`, the `ai-light.log`,
and the `~/.ai_light/bin/ai-light-hook` binary.

## Run

```bash
./scripts/run-ubuntu-gui.sh
# or
python3 src-ubuntu/ai_light.py
```

A small transparent, always-on-top, taskbar-skipping window appears. With no
active sessions it shows an `AI` handle you can right-click for
**Settings / Diagnostics / Quit**. Drag the background to move it.

## Architecture (mirrors the Rust core)

| Rust module                | Ubuntu port (`src-ubuntu/`)      |
| -------------------------- | -------------------------------- |
| `config.rs`                | `config.py`                      |
| `types.rs`                 | `model.py`                       |
| `aggregator.rs`            | `aggregator.py`                  |
| `http_server.rs`           | `http_server.py`                 |
| `project.rs`               | `project.py`                     |
| `codex_watcher.rs`         | `codex_watcher.py`               |
| `hook_installer.rs`        | `hook_installer.py`              |
| `app_lock.rs`              | `app_lock.py`                    |
| `logging.rs`               | `logging_util.py`                |
| `src-hook/main.rs`         | `ai_light_hook` (Python shim)    |
| `src/app.js` + `index.html`| `window.py` + `ui.css`           |
| `src/settings.*`           | `settings_window.py`             |
| — (new)                    | `opencode_watcher.py`            |

The HTTP server exposes the same endpoints (`GET /health`, `GET /state`,
`POST /events`) and writes `runtime.json` with the bound port, so the existing
`install-ubuntu-hook.sh` / `ai-light-hook` binary keep working unchanged.

## Claude Code integration

Right-click → **Settings → Install Claude Integration**. This:

1. Copies the Python `ai_light_hook` shim to `~/.ai_light/bin/ai-light-hook`
   (only if no hook binary is already present — an existing Rust binary is
   preferred and left untouched).
2. Merges the 8 AI Light hooks into `~/.claude/settings.json` using the
   `command + args` form (avoids shell path-escaping issues).

Then restart Claude Code (or run `/hooks`) to confirm the hooks are loaded.
The shim reads its target from `AI_LIGHT_URL` (preferred) or
`~/.ai_light/runtime.json`, POSTs the event to `/events`, and logs to
`~/.ai_light/hook.log` — identical to the Rust helper.

## opencode support (new)

[opencode](https://opencode.ai) has no Claude-style lifecycle-hook config, so
like Codex it is **monitored automatically** — no install step. The
`opencode_watcher.py` thread tails the `event` table in
`~/.local/share/opencode/opencode.db` (opened read-only, so the running
opencode process is never blocked) and infers status:

| Event                              | Light      |
| ---------------------------------- | ---------- |
| `session.created.1`                | Idle (new) |
| `message.updated.1` role=user      | Working    |
| `message.updated.1`/`.part` assistant | Working (streaming) |
| quiet for 8s while Working         | Done       |
| stale Working 10min                | Error      |
| inactive 15min / `time_archived`   | removed    |

The opencode project is resolved from the session's `directory` via the same
git-root logic as Claude/Codex, so a light for `ai-light-master` itself will
appear when you run `opencode` here. opencode sessions show an `OC` badge;
Claude Code `CC`; Codex `CX`.

## Verify

```bash
# 1. Launch
./scripts/run-ubuntu-gui.sh &

# 2. HTTP health
port=$(python3 -c "import json;print(json.load(open('$HOME/.ai_light/runtime.json'))['http_port'])")
curl -s "http://127.0.0.1:$port/health"   # -> ok
curl -s "http://127.0.0.1:$port/state"    # -> []

# 3. Claude hook (manual)
AI_LIGHT_URL="http://127.0.0.1:$port" ~/.ai_light/bin/ai-light-hook session-start \
  <<<'{"session_id":"ubuntu-test","cwd":"/tmp/ail-test"}'
AI_LIGHT_URL="http://127.0.0.1:$port" ~/.ai_light/bin/ai-light-hook prompt-submit \
  <<<'{"session_id":"ubuntu-test"}'      # -> yellow light
AI_LIGHT_URL="http://127.0.0.1:$port" ~/.ai_light/bin/ai-light-hook stop \
  <<<'{"session_id":"ubuntu-test"}'      # -> green; click it to clear

# 4. opencode: start `opencode` in any project, send a prompt -> yellow, then green.
# 5. Single instance: launch a second time -> exits immediately.
```

## Files

```
src-ubuntu/
  ai_light.py            entry point
  config.py              ~/.ai_light config + runtime
  model.py               Status / Tool(+Opencode) / LightState
  aggregator.py          session/light aggregation
  http_server.py         /health /state /events
  project.py             git-root project identity
  codex_watcher.py       ~/.codex/sessions JSONL tail
  opencode_watcher.py    opencode.db event tail (new)
  hook_installer.py      ~/.claude/settings.json merge
  ai_light_hook          Python hook shim (drop-in for the Rust binary)
  app_lock.py            single-instance fcntl lock
  logging_util.py        ~/.ai_light/ai-light.log
  window.py              floating GTK3 traffic-light window
  settings_window.py     settings + diagnostics
  ui.css                 lamp/label styles
  actions.py             open / clipboard / diagnostics helpers
```

## Notes

- The Tauri/Rust app and `src/` web frontend are untouched and remain the
  Windows/macOS build. The Ubuntu GUI is a parallel native client.
- opencode plugin/SDK integration was rejected in favour of the DB watcher:
  it works without opencode running in server mode and needs no opencode
  config changes.
