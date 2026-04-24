#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE_PATH="${SCRIPT_DIR}/com.user.briefing-watch.plist.template"
OUTPUT_DIR="${REPO_ROOT}/tmp/launchd"
OUTPUT_PATH="${OUTPUT_DIR}/com.user.briefing-watch.plist"
UV_PATH="$(command -v uv)"
LOG_DIR="${REPO_ROOT}/logs"
PATH_VALUE="${PATH}:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "${OUTPUT_DIR}" "${LOG_DIR}"

sed \
  -e "s|{{UV_PATH}}|${UV_PATH}|g" \
  -e "s|{{REPO_ROOT}}|${REPO_ROOT}|g" \
  -e "s|{{LOG_DIR}}|${LOG_DIR}|g" \
  -e "s|{{PATH_VALUE}}|${PATH_VALUE}|g" \
  "${TEMPLATE_PATH}" > "${OUTPUT_PATH}"

echo "Rendered ${OUTPUT_PATH}"
