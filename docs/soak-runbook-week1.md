# Phase 5A Soak Runbook — Week 1

**Period:** 2026-04-25 → 2026-05-02  
**Goal:** Ten unattended meetings across seven days with zero developer intervention needed to recover.  
**Success criterion:** ≥ 95% of scheduled sessions produce a usable summary or a clearly recoverable state.

---

## Per-Session Log

Copy one row for each meeting. Fill in columns as the session progresses.

| Field | Value |
|-------|-------|
| **Date** | |
| **Session ID** | |
| **Event ID** | (calendar event UID or "adhoc") |
| **Series** | |
| **Manifest path** | |
| **Mode** | in_person / online / hybrid |
| **Stop mode** | scheduled / manual / auto_switch / extended |
| **Completion status** | completed / completed_with_warnings / failed |
| **Audio captured?** | yes / no |
| **Transcript OK?** | yes / no / partial |
| **Diarization OK?** | yes / no / skipped |
| **Ingest result** | ok / skipped (reason) / failed (reason) |
| **Summary written?** | yes / no |
| **Summary quality** | 1–5 (see rubric) |
| **Recovery needed?** | no / yes — describe |
| **Recovery command** | (e.g. `briefing session-reprocess --session-dir <path>`) |
| **Notes** | |

---

## Session Log Entries

<!-- Paste a filled-in copy of the table above for each meeting. -->

---

## Daily Checklist

> **Set your sessions root once:**
> ```bash
> SESSIONS=$(grep sessions_root user_config/settings.toml | awk -F'"' '{print $2}')
> # Or read it directly: SESSIONS="$HOME/noted-sessions"   ← substitute your configured path
> ```

Run these each morning before the first meeting:

```bash
# 1. Confirm briefing watch is running
launchctl list | grep briefing

# 2. Validate the full environment (confirms sessions_root, noted command, and schema compat)
uv run briefing validate

# 3. Check for any sessions from yesterday that need reprocessing
ls -lt "$SESSIONS/" | head -20
```

And each evening:

```bash
# 1. Check for sessions that produced completion_with_warnings
for d in "$SESSIONS"/*/; do
  jq -r '"[\(.session_id)] \(.terminal_status) — \(.stop_reason)"' "$d/outputs/completion.json" 2>/dev/null
done

# 2. Check briefing.log entries for ingest failures
grep -r "ERROR\|WARN" "$SESSIONS"/*/logs/briefing.log 2>/dev/null | tail -30

# 3. For any session with transcript_ok=true but no summary yet, reprocess:
# uv run briefing session-reprocess --session-dir <path>
```

---

## Failure Classification

| Symptom | Likely cause | Recovery |
|---------|--------------|----------|
| `completion.json` absent after 10+ min | `noted` crashed post-capture | Check `noted.log`; audio probably on disk — run `briefing session-reprocess` once transcript is manually generated |
| `transcript_ok: false`, `audio_capture_ok: true` | ASR failed | Wait; re-trigger `noted`'s transcript from audio if WhisperKit supports it |
| `transcript_ok: true`, ingest skipped | `ingest_after_completion=false` or briefing command not configured | Run `briefing session-ingest --session-dir <path>` manually |
| Summary block missing from note | LLM call timed out or failed | Run `briefing session-reprocess --session-dir <path>` |
| Summary written but poor quality | Diarization noise / short meeting | Rate 1–2, flag for prompt tuning after soak |
| `noted version` schema mismatch in validate | `noted` and `briefing` vendor contracts are out of sync | Run `briefing validate` and check `noted_schema_compat_error` |

---

## Recovery Commands Reference

```bash
# Re-run summary from existing transcript (transcript must be present)
uv run briefing session-reprocess --session-dir <path>

# Dry-run to preview without writing
uv run briefing session-reprocess --session-dir <path> --dry-run

# Re-ingest a session (requires completion.json to be in a summarisable state)
uv run briefing session-ingest --session-dir <path>

# Check noted is alive and the session is still running
noted status --session-id <id>

# Block until session completes (useful for scripting)
noted wait --session-id <id> --timeout-seconds 600

# Validate the environment before any meeting day
uv run briefing validate
```

---

## Week-End Retrospective Questions

1. How many sessions completed without any manual intervention?
2. Which failure mode recurred most? Is there a pattern?
3. Which summaries rated below 3? What was wrong with them?
4. Did diarization quality degrade during any meeting type?
5. Did any session fail silently (no completion.json, no error surfaced)?
6. Is 90-second pre-roll reliably getting the first words?
7. Any new open questions to add to the master plan §27?

---

## After the Soak

Populate the human-rated evaluation set (`docs/eval/`) from the 8–12 best sessions.  
Threshold for proceeding to full Phase 5: ≥ 9 of 10 sessions produced a usable summary with no developer intervention.
