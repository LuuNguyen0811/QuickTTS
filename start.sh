#!/bin/zsh
setopt errexit nounset pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
export PYTHONUNBUFFERED=1
mkdir -p "$ROOT/logs"

start_one() {
  local name="$1"
  local script="$2"
  local pidfile="$ROOT/logs/${name}.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pidfile"))"
    return
  fi
  # setsid so the process survives the terminal that launched it
  "$PY" -c '
import os, sys
os.setsid()
os.execv(sys.argv[1], [sys.argv[1], sys.argv[2]])
' "$PY" "$ROOT/$script" >> "$ROOT/logs/${name}.log" 2>&1 &
  local pid=$!
  echo "$pid" > "$pidfile"
  echo "$name started (pid $pid)"
}

start_one server server.py

ready=0
for _ in {1..60}; do
  if curl -sf -m 1 "http://127.0.0.1:8765/health" >/dev/null; then
    ready=1
    break
  fi
  if [[ -f "$ROOT/logs/server.pid" ]] && ! kill -0 "$(cat "$ROOT/logs/server.pid")" 2>/dev/null; then
    echo "server exited. last log lines:"
    tail -n 40 "$ROOT/logs/server.log" || true
    exit 1
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  echo "server did not open port 8765. last log lines:"
  tail -n 40 "$ROOT/logs/server.log" || true
  exit 1
fi
echo "server is listening on http://127.0.0.1:8765"
start_one hotkey hotkey.py
echo "hotkey listener started. shortcut: Option+\`  or  Control+Option+\`"
