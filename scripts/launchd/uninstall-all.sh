#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"${SCRIPT_DIR}/uninstall-plist.sh"
"${SCRIPT_DIR}/uninstall-watch-plist.sh"
