#!/bin/zsh
setopt errexit nounset pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

stop_one() {
  local name="$1"
  local pidfile="$ROOT/logs/${name}.pid"
  if [[ ! -f "$pidfile" ]]; then
    echo "$name is not running"
    return
  fi
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
    local _
    for _ in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "stopped $name (pid $pid)"
  else
    echo "$name was not running (stale pid $pid)"
  fi
  rm -f "$pidfile"
}

stop_one hotkey
stop_one server
