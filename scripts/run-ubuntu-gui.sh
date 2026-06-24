#!/usr/bin/env bash
# Launch the AI Light Ubuntu GTK3 GUI.
# Usage: ./scripts/run-ubuntu-gui.sh
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

exec python3 "${repo_root}/src-ubuntu/ai_light.py" "$@"
