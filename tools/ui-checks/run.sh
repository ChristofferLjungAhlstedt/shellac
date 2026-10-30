#!/usr/bin/env bash
# Run a GUI check script in a throwaway X server with a scratch HOME and config.
# Usage: tools/ui-checks/run.sh tools/ui-checks/settings_window.py
# Needs: xvfb-run, dbus-run-session, xdotool, ImageMagick (import). Screenshots go to $SHOTDIR.
set -euo pipefail
script=$(realpath "$1")
root=$(cd "$(dirname "$0")/../.." && pwd)
run=$(mktemp -d)
mkdir -p "$run/home" "$run/cfg" "$run/state" "$run/shots"
export SHOTDIR="$run/shots" HOME="$run/home" XDG_CONFIG_HOME="$run/cfg" XDG_STATE_HOME="$run/state"
export SHELL=/bin/bash GDK_BACKEND=x11 GSK_RENDERER=cairo NO_AT_BRIDGE=1 GTK_A11Y=none PYTHONPATH="$root"
cd "$root"
dbus-run-session -- xvfb-run -a -s "-screen 0 1280x800x24" python3.12 "$script" 2>&1 | grep -v "^$\|EGL\|dbus\|CRITICAL"
echo "screenshots: $SHOTDIR"
