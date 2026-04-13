#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8080}"

# python3 is available on most Macs/Linux; falls back to python
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python not found. Install python3 or use any static file server." >&2
  exit 1
fi

echo "Serving sensor dashboard on: http://localhost:${PORT}/"
$PY -m http.server "$PORT"
