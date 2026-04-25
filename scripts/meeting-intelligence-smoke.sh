#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
NOTED_CMD="${NOTED_CMD:-noted}"
SMOKE_ROOT="${BRIEFING_SMOKE_ROOT:-/tmp/meeting-intelligence-smoke}"
SESSION_ID="smoke-$(date +%Y%m%d%H%M%S)"
SESSION_DIR="$SMOKE_ROOT/sessions/$SESSION_ID"
NOTE_PATH="$SMOKE_ROOT/vault/Meetings/$SESSION_ID.md"
MANIFEST_PATH="$SESSION_DIR/manifest.json"
CAPTURE_SECONDS="${CAPTURE_SECONDS:-30}"
WAIT_SECONDS="${WAIT_SECONDS:-180}"

mkdir -p "$SESSION_DIR" "$(dirname "$NOTE_PATH")"

python3 - "$DEV_ROOT/contracts/fixtures/manifests/valid-inperson.json" "$MANIFEST_PATH" "$SESSION_ID" "$SESSION_DIR" "$NOTE_PATH" <<'PY'
import json
import sys
from datetime import datetime, timedelta

source, target, session_id, session_dir, note_path = sys.argv[1:]
manifest = json.load(open(source, encoding="utf-8"))
now = datetime.now().astimezone()
manifest["session_id"] = session_id
manifest["created_at"] = now.isoformat()
manifest["meeting"]["event_id"] = "smoke-event"
manifest["meeting"]["title"] = "Meeting Intelligence Smoke"
manifest["meeting"]["start_time"] = now.isoformat()
manifest["meeting"]["scheduled_end_time"] = (now + timedelta(minutes=15)).isoformat()
manifest["meeting"]["timezone"] = now.tzinfo.tzname(now) or "local"
manifest["paths"]["session_dir"] = session_dir
manifest["paths"]["output_dir"] = f"{session_dir}/outputs"
manifest["paths"]["note_path"] = note_path
manifest["next_meeting"] = {"exists": False}
json.dump(manifest, open(target, "w", encoding="utf-8"), indent=2, sort_keys=True)
PY

cat > "$NOTE_PATH" <<EOF
---
title: Meeting Intelligence Smoke
---
# Meeting Intelligence Smoke

---
## Briefing

Smoke-test note.

---
## Meeting Notes

- Manual note content that must survive ingest.
EOF

echo "Validating manifest: $MANIFEST_PATH"
"$NOTED_CMD" validate-manifest --manifest "$MANIFEST_PATH"

echo "Starting noted capture for $CAPTURE_SECONDS seconds"
START_JSON="$("$NOTED_CMD" start --manifest "$MANIFEST_PATH")"
echo "$START_JSON"
sleep "$CAPTURE_SECONDS"

echo "Stopping noted capture"
"$NOTED_CMD" stop --session-id "$SESSION_ID"

echo "Waiting for completion.json"
deadline=$((SECONDS + WAIT_SECONDS))
while [[ ! -f "$SESSION_DIR/outputs/completion.json" ]]; do
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for $SESSION_DIR/outputs/completion.json" >&2
    exit 1
  fi
  sleep 2
done

handoff_probe_deadline=$((SECONDS + 10))
while [[ -f "$SESSION_DIR/logs/noted.log" ]] \
  && ! grep -Eq "briefing ingest (starting|completed|failed to start|skipped)" "$SESSION_DIR/logs/noted.log" \
  && (( SECONDS < handoff_probe_deadline )); do
  sleep 1
done

if grep -Eq "briefing ingest (starting|completed)" "$SESSION_DIR/logs/noted.log" 2>/dev/null; then
  echo "Waiting for automatic noted -> briefing ingest handoff"
  deadline=$((SECONDS + WAIT_SECONDS))
  while ! grep -Eq "briefing ingest (completed|failed to start)" "$SESSION_DIR/logs/noted.log"; do
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for automatic briefing ingest handoff" >&2
      exit 1
    fi
    sleep 2
  done
fi

echo "Running briefing session-ingest dry-run"
(cd "$ROOT_DIR" && uv run briefing session-ingest --session-dir "$SESSION_DIR" --dry-run)

echo "Running briefing session-ingest write"
(cd "$ROOT_DIR" && uv run briefing session-ingest --session-dir "$SESSION_DIR")

echo "Smoke complete"
echo "Session: $SESSION_DIR"
echo "Note: $NOTE_PATH"
