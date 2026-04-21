#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANDROID_DIR="${ROOT_DIR}/android"

find_java17_home() {
  if [[ -n "${JAVA17_HOME:-}" ]] && [[ -x "${JAVA17_HOME}/bin/java" ]]; then
    echo "${JAVA17_HOME}"
    return 0
  fi

  if [[ -n "${JAVA_HOME:-}" ]] && [[ -x "${JAVA_HOME}/bin/java" ]]; then
    local current_version
    current_version="$("${JAVA_HOME}/bin/java" -version 2>&1 | head -n 1 || true)"
    if [[ "${current_version}" == *"17."* ]]; then
      echo "${JAVA_HOME}"
      return 0
    fi
  fi

  if command -v /usr/libexec/java_home >/dev/null 2>&1; then
    local mac_home
    mac_home="$(/usr/libexec/java_home -v 17 2>/dev/null || true)"
    if [[ -n "${mac_home}" ]] && [[ -x "${mac_home}/bin/java" ]]; then
      echo "${mac_home}"
      return 0
    fi
  fi

  return 1
}

JAVA17_HOME_RESOLVED="$(find_java17_home || true)"
if [[ -z "${JAVA17_HOME_RESOLVED}" ]]; then
  echo "Error: Java 17 was not found."
  echo "Install JDK 17 and set JAVA17_HOME, then retry."
  exit 1
fi

export JAVA_HOME="${JAVA17_HOME_RESOLVED}"
export PATH="${JAVA_HOME}/bin:${PATH}"

cd "${ANDROID_DIR}"

if [[ "$#" -eq 0 ]]; then
  set -- test assembleDebug
fi

echo "Using Java from: ${JAVA_HOME}"
echo "Running: ./gradlew --no-daemon $*"
./gradlew --no-daemon "$@"
