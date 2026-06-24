#!/usr/bin/env bash
# Launch the AI Light Ubuntu GTK3 GUI.
# Usage: ./scripts/run-ubuntu-gui.sh
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

# On Wayland sessions, set_keep_above() is silently ignored by the
# compositor (GNOME Mutter does not implement wlr-layer-shell).
# Force X11 backend via XWayland so the EWMH _NET_WM_STATE_ABOVE
# property works — this makes the "always on top" feature functional.
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    export GDK_BACKEND=x11
fi

exec python3 "${repo_root}/src-ubuntu/ai_light.py" "$@"
