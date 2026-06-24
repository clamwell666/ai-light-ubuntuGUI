# Ubuntu GUI for AI Light

Last updated: 2026-06-25

The Ubuntu GUI is a native **Python + GTK3** desktop widget that monitors
Claude Code, Codex, and opencode sessions in real time. It runs with **no Rust
toolchain, no `sudo`, and no `webkit2gtk` dev headers** \u2014 only
`python3-gi`, which ships with Ubuntu.

## Run

```bash
./scripts/run-ubuntu-gui.sh
# or
python3 src-ubuntu/ai_light.py
```

A small transparent, always-on-top, taskbar-skipping window appears. With no
active sessions it shows an `AI` handle you can right-click for
**Settings / Diagnostics / Quit**. Drag the background to move it.

## Per-tool lights

Each AI tool gets its own independent row per project, with a tool badge:

| Badge | Tool |
| ----- | ---- |
| CC    | Claude Code |
| CX    | Codex |
| OC    | opencode |

Each row has its own status (red/yellow/green lamps), so when Claude Code is
Working and opencode is Idle in the same project, you see both states
simultaneously.

## Window controls

### Always on top

Toggle in **Settings \u2192 Window \u2192 Always on top**. Changes take effect
immediately and persist across restarts.

### Opacity

Adjust in **Settings \u2192 Window \u2192 Opacity** (slider from 10% to 100%).
Changes take effect immediately and persist.

## Claude Code integration

Right-click \u2192 **Settings \u2192 Install Claude Integration**. This:

1. Copies the Python `ai_light_hook` shim to `~/.ai_light/bin/ai-light-hook`
   (only if no hook binary is already present).
2. Merges the 8 AI Light hooks into `~/.claude/settings.json` using the
   `command + args` form (avoids shell path-escaping issues).

Then restart Claude Code (or run `/hooks`) to confirm the hooks are loaded.
The shim reads its target from `AI_LIGHT_URL` (preferred) or
`~/.ai_light/runtime.json`, POSTs the event to `/events`, and logs to
`~/.ai_light/hook.log`.

## opencode support

[opencode](https://opencode.ai) has no Claude-style lifecycle-hook config, so
like Codex it is **monitored automatically** \u2014 no install step. The
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
git-root logic as Claude/Codex. opencode sessions show an `OC` badge;
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
  <<<'{"session_id":"ubuntu-test"}'      # -> yellow light (CC)
AI_LIGHT_URL="http://127.0.0.1:$port" ~/.ai_light/bin/ai-light-hook stop \
  <<<'{"session_id":"ubuntu-test"}'      # -> green; click it to clear

# 4. opencode: start `opencode` in any project, send a prompt -> yellow (OC), then green.
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
  opencode_watcher.py    opencode.db event tail
  hook_installer.py      ~/.claude/settings.json merge
  ai_light_hook          Python hook shim
  app_lock.py            single-instance fcntl lock
  logging_util.py        ~/.ai_light/ai-light.log
  window.py              floating GTK3 traffic-light window
  settings_window.py     settings + diagnostics + opacity + always-on-top
  ui.css                 lamp/label styles
  actions.py             open / clipboard / diagnostics helpers
```
