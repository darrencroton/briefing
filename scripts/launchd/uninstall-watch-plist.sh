#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LABEL="com.user.briefing-watch"
INSTALL_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
ARCHIVE_DIR="${REPO_ROOT}/archive/launchd"
ARCHIVE_PATH="${ARCHIVE_DIR}/${LABEL}.$(date +%Y%m%d-%H%M%S).plist"

launchctl bootout "gui/$(id -u)" "${INSTALL_PATH}" >/dev/null 2>&1 \
  || launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 \
  || true

if [[ -f "${INSTALL_PATH}" ]]; then
  mkdir -p "${ARCHIVE_DIR}"
  mv "${INSTALL_PATH}" "${ARCHIVE_PATH}"
  echo "Archived ${INSTALL_PATH} to ${ARCHIVE_PATH}"
else
  echo "No installed plist found at ${INSTALL_PATH}"
fi

echo "Uninstalled ${LABEL}"
