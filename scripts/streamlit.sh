#!/usr/bin/env bash
# Dev helper: manage *this app's* Streamlit process only.
# Usage: scripts/streamlit.sh {start|stop|restart|status}
#
# Exists so the kill/restart dev loop is a single, tightly-scoped command that
# can be allow-listed in .claude/settings.local.json (so Claude can restart the
# app during development without a permission prompt for every step).
set -uo pipefail

cd "$(dirname "$0")/.."

PORT=8765
APP="app/main.py"
LOG="/tmp/ko-streamlit.log"
PYTHON=".venv/bin/python"  # invoke via -m so a directory rename can't break a shebang
HEALTH="http://localhost:${PORT}/_stcore/health"

stop() {
  pkill -f "streamlit run ${APP}" 2>/dev/null || true
  sleep 1
}

start() {
  nohup "${PYTHON}" -m streamlit run "${APP}" --server.port "${PORT}" --server.headless true \
    > "${LOG}" 2>&1 &
  disown 2>/dev/null || true
  for _ in $(seq 1 20); do
    if curl -sf "${HEALTH}" >/dev/null 2>&1; then
      echo "streamlit healthy on http://localhost:${PORT}"
      return 0
    fi
    sleep 1
  done
  echo "streamlit did not become healthy in time; see ${LOG}"
  return 1
}

status() {
  if curl -sf "${HEALTH}" >/dev/null 2>&1; then
    echo "running (healthy on :${PORT})"
  else
    echo "not running on :${PORT}"
  fi
}

reseed() {
  stop
  .venv/bin/python scripts/seed.py
  start
}

case "${1:-restart}" in
  start)   start ;;
  stop)    stop; echo "stopped" ;;
  restart) stop; start ;;
  reseed)  reseed ;;
  status)  status ;;
  *) echo "usage: $0 {start|stop|restart|reseed|status}"; exit 2 ;;
esac
