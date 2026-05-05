#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEFAULT_PLIST="${REPO_ROOT}/tmp/launchd/com.user.briefing-watch.plist"
TARGET_PLIST="${1:-${DEFAULT_PLIST}}"
INSTALL_PATH="${HOME}/Library/LaunchAgents/com.user.briefing-watch.plist"

if [[ $# -eq 0 ]]; then
  "${SCRIPT_DIR}/render-watch-plist.sh"
elif [[ ! -f "${TARGET_PLIST}" ]]; then
  echo "Plist not found: ${TARGET_PLIST}" >&2
  exit 1
fi

plutil -lint "${TARGET_PLIST}"
mkdir -p "${HOME}/Library/LaunchAgents"
cp "${TARGET_PLIST}" "${INSTALL_PATH}"
launchctl bootout "gui/$(id -u)" "${INSTALL_PATH}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${INSTALL_PATH}"
launchctl enable "gui/$(id -u)/com.user.briefing-watch"

echo "Installed ${INSTALL_PATH}"
