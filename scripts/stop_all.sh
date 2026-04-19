#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${ROOT_DIR}/.logs"
NGROK_PID_FILE="${LOG_DIR}/ngrok.pid"

stop_ngrok() {
  if [[ "${STOP_NGROK:-1}" != "1" ]]; then
    echo "Skipping ngrok stop (STOP_NGROK=${STOP_NGROK:-0})."
    return
  fi

  if [[ -f "${NGROK_PID_FILE}" ]]; then
    local pid
    pid="$(cat "${NGROK_PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" || true
      echo "Stopped ngrok (pid ${pid})."
    else
      echo "ngrok pid file found, but process is not running."
    fi
    rm -f "${NGROK_PID_FILE}"
  else
    echo "No ngrok pid file found."
  fi

  if [[ "${STOP_NGROK_ALL:-0}" == "1" ]]; then
    pkill -f "ngrok http.*8000" >/dev/null 2>&1 || true
    echo "Attempted to stop any remaining ngrok http 8000 processes."
  fi
}

main() {
  cd "${ROOT_DIR}"

  if [[ "${CLEAN_VOLUMES:-0}" == "1" ]]; then
    echo "Stopping Docker stack and removing volumes..."
    docker compose down -v
  else
    echo "Stopping Docker stack..."
    docker compose down
  fi

  stop_ngrok

  echo
  echo "System shutdown complete."
}

main "$@"
