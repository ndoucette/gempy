#!/usr/bin/env bash
# gempy runner: escapes the VS Code flatpak sandbox (where rbenv ruby
# breaks on host libs) and uses the project venv if present.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f /.flatpak-info ] && command -v flatpak-spawn >/dev/null 2>&1; then
  echo "[gempy] flatpak sandbox detected — re-launching on the host"
  exec flatpak-spawn --host "$(pwd)/run.sh" "$@"
fi

PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" launcher.py "$@"
