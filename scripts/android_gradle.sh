#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANDROID_DIR="${ROOT_DIR}/android"
DAEMON_JVM_PROPS="${ANDROID_DIR}/gradle/gradle-daemon-jvm.properties"

resolve_required_java_version() {
  local required_version="17"

  if [[ -f "${DAEMON_JVM_PROPS}" ]]; then
    local parsed_version
    parsed_version="$(grep -E '^toolchainVersion=' "${DAEMON_JVM_PROPS}" | cut -d'=' -f2 | tr -d '[:space:]' || true)"
    if [[ "${parsed_version}" =~ ^[0-9]+$ ]]; then
      required_version="${parsed_version}"
    fi
  fi

  echo "${required_version}"
}

java_major_version() {
  local java_bin="$1"
  "${java_bin}" -version 2>&1 | head -n 1 | sed -E 's/.*version "([0-9]+)(\.[^"]*)?".*/\1/'
}

find_java_home() {
  local required_version="$1"
  local required_var="JAVA${required_version}_HOME"
  local candidate_home="${!required_var:-}"

  if [[ -n "${candidate_home}" ]] && [[ -x "${candidate_home}/bin/java" ]]; then
    echo "${candidate_home}"
    return 0
  fi

  if [[ -n "${JAVA_HOME:-}" ]] && [[ -x "${JAVA_HOME}/bin/java" ]]; then
    local current_major
    current_major="$(java_major_version "${JAVA_HOME}/bin/java" || true)"
    if [[ "${current_major}" == "${required_version}" ]]; then
      echo "${JAVA_HOME}"
      return 0
    fi
  fi

  if command -v /usr/libexec/java_home >/dev/null 2>&1; then
    local mac_home
    mac_home="$(/usr/libexec/java_home -v "${required_version}" 2>/dev/null || true)"
    if [[ -n "${mac_home}" ]] && [[ -x "${mac_home}/bin/java" ]]; then
      echo "${mac_home}"
      return 0
    fi
  fi

  return 1
}

REQUIRED_JAVA_VERSION="$(resolve_required_java_version)"
JAVA_HOME_RESOLVED="$(find_java_home "${REQUIRED_JAVA_VERSION}" || true)"

if [[ -z "${JAVA_HOME_RESOLVED}" ]]; then
  echo "Error: Java ${REQUIRED_JAVA_VERSION} was not found."
  echo "Install JDK ${REQUIRED_JAVA_VERSION} and set JAVA${REQUIRED_JAVA_VERSION}_HOME, then retry."
  exit 1
fi

export JAVA_HOME="${JAVA_HOME_RESOLVED}"
export PATH="${JAVA_HOME}/bin:${PATH}"

cd "${ANDROID_DIR}"

if [[ "$#" -eq 0 ]]; then
  set -- test assembleDebug
fi

echo "Using Java from: ${JAVA_HOME}"
echo "Required Java major version: ${REQUIRED_JAVA_VERSION}"
echo "Running: ./gradlew --no-daemon $*"
./gradlew --no-daemon "$@"
