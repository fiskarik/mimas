#!/usr/bin/env bash
set -euo pipefail
cd /app
python scripts/migrate.py
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1 &
api_pid=$!
HOSTNAME=0.0.0.0 PORT="${PORT:-10000}" node /app/frontend/server.js &
web_pid=$!

cleanup() {
  kill "$api_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT
wait -n "$api_pid" "$web_pid"
exit 1
