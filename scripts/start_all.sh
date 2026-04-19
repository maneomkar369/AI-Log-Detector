#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${ROOT_DIR}/.logs"
NGROK_PID_FILE="${LOG_DIR}/ngrok.pid"
NGROK_LOG_FILE="${LOG_DIR}/ngrok.log"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: '$cmd' is not installed or not in PATH."
    exit 1
  fi
}

start_ngrok() {
  if [[ "${START_NGROK:-1}" != "1" ]]; then
    echo "Skipping ngrok start (START_NGROK=${START_NGROK:-0})."
    return
  fi

  if ! command -v ngrok >/dev/null 2>&1; then
    echo "Warning: ngrok not found. Backend started, but tunnel was not started."
    return
  fi

  if [[ -f "${NGROK_PID_FILE}" ]]; then
    local old_pid
    old_pid="$(cat "${NGROK_PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
      echo "ngrok already running (pid ${old_pid})."
      return
    fi
    rm -f "${NGROK_PID_FILE}"
  fi

  mkdir -p "${LOG_DIR}"
  if [[ -n "${NGROK_DOMAIN:-}" ]]; then
    nohup ngrok http --domain="${NGROK_DOMAIN}" 8000 >"${NGROK_LOG_FILE}" 2>&1 &
  else
    nohup ngrok http 8000 >"${NGROK_LOG_FILE}" 2>&1 &
  fi

  echo "$!" >"${NGROK_PID_FILE}"
  echo "Started ngrok (pid $(cat "${NGROK_PID_FILE}"))."
  echo "ngrok logs: ${NGROK_LOG_FILE}"
}

main() {
  require_cmd docker

  cd "${ROOT_DIR}"
  mkdir -p "${LOG_DIR}"

  if [[ "${START_BUILD:-0}" == "1" ]]; then
    echo "Starting Docker stack with build..."
    docker compose up -d --build
  else
    echo "Starting Docker stack..."
    docker compose up -d
  fi

  start_ngrok

  echo
  echo "System startup complete."
  echo "Dashboard: http://localhost:5001"
  echo "Edge API:  http://localhost:8000"
  echo "Health:    http://localhost:8000/api/health"
  echo
  echo "Tip: set NGROK_DOMAIN=your-domain.ngrok-free.dev before running this script"
  echo "if you use a reserved ngrok domain."
}

main "$@"
