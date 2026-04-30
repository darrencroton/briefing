# `noted` CLI Contract (v1.0)

**Authoritative source:** Master Plan §9. This document is the stable interface between `briefing` and `noted`; schema-level changes bump the contract version per `versioning-policy.md`.

## Principles

- Small, stable, scriptable, deterministic, machine-friendly.
- No GUI automation. No screen scraping.
- Every popup action and every menubar action has a 1:1 CLI equivalent (§9.8). One canonical code path per action.
- `stdout` is a single JSON line on success. Human-readable diagnostics go to `stderr`.
- All timestamps emitted by `noted` are ISO-8601 with explicit timezone offsets.

## Commands

### Required (v1)

```
noted start             --manifest <path>
noted pause             --session-id <id>
noted continue          --session-id <id>
noted stop              --session-id <id>
noted extend            --session-id <id> --minutes N
noted switch-next       --session-id <id>
noted status            --session-id <id>
noted validate-manifest --manifest <path>
noted version
```

### Optional (later)

```
noted wait              --session-id <id> [--timeout-seconds N]
noted list-sessions
noted tail-log          --session-id <id>
```

---

## `noted start --manifest <path>`

Validates the manifest, creates the session directory structure, acquires audio resources, begins capture, and returns once recording is stable.

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0    | Session successfully started |
| 2    | Invalid manifest |
| 3    | Required permissions missing (microphone, screen recording) |
| 4    | Audio device failure |
| 5    | Session already running |
| 6    | Internal startup failure |

**stdout (success):**

```json
{"ok": true, "session_id": "2026-04-18-jayde-1600", "status": "recording", "pid": 12345, "session_dir": "/path/to/sessions/2026-04-18-jayde-1600"}
```

---

## `noted stop --session-id <id>`

Finalises **capture only** and returns. ASR and diarization continue asynchronously as part of post-processing. `stop` is deliberately fast so that back-to-back handoffs are possible (guardrail 1).

On return:

- Capture has stopped.
- Raw audio has been flushed and fsynced.
- Session state has transitioned from `recording` (or `stopping`) to `processing`.
- `completion.json` has **not** been written yet — it is written at the end of post-processing.

Post-processing proceeds through the phases in §10.2 (`flushing_audio` → `running_asr` → `running_diarization` → `writing_outputs` → `finished`). `noted status` reflects progress. `completion.json` appears only when processing ends (success, warning, or failure).

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0    | Capture stopped; post-processing started |
| 2    | Unknown session ID |
| 3    | Session not running |
| 4    | Stop-capture failed (raw audio may still be recoverable on disk) |

**stdout (success):**

```json
{"ok": true, "session_id": "2026-04-18-jayde-1600", "status": "processing", "audio_finalised": true}
```

---

## `noted pause --session-id <id>` / `noted continue --session-id <id>`

Temporarily suspends or resumes audio capture for an active session. The session stays active and remains `status: "recording"`; `status.json` and `noted status` expose `is_paused` instead of adding a new locked runtime status value.

| Code | Meaning |
|------|---------|
| 0    | Pause/continue state applied |
| 2    | Unknown session ID |
| 3    | Session not in `recording` |
| 4    | Pause/continue request failed or timed out |

**stdout (success):**

```json
{"ok": true, "session_id": "2026-04-18-jayde-1600", "status": "recording", "is_paused": true}
```

---

## `noted extend --session-id <id> --minutes N`

Extends the scheduled stop by N minutes (typically 5). Idempotent within a single popup cycle; respects the extension policy described in §12.4.

| Code | Meaning |
|------|---------|
| 0    | Extension applied |
| 2    | Unknown session ID |
| 3    | Session not in `recording` |
| 6    | Extension rejected (policy) |

**stdout (success):**

```json
{"ok": true, "session_id": "2026-04-18-jayde-1600", "status": "recording", "current_extension_minutes": 5, "scheduled_end_time": "2026-04-18T17:05:00+10:00"}
```

---

## `noted switch-next --session-id <id>`

Stops the current capture immediately (same fast-stop as `stop`), writes `stop_reason: auto_switch_to_next_meeting`, and launches the next session by invoking `noted start --manifest <next_manifest_path>` on the pre-prepared manifest referenced by `next_meeting.manifest_path` in the current manifest. Returns as soon as the current capture is finalised and the next-session launch has either succeeded or failed. Post-processing of the old session and startup of the new session proceed concurrently.

| Code | Meaning |
|------|---------|
| 0    | Current session stopped; next session started |
| 2    | Unknown session ID |
| 3    | No eligible next meeting (`next_meeting.exists: false`) |
| 4    | Stop-capture failed |
| 8    | Next manifest missing or invalid (e.g. invalidated by `briefing watch` between planning and handoff); current session is stopped normally |

**stdout (success):**

```json
{"ok": true, "previous_session_id": "2026-04-18-jayde-1600", "next_session_id": "2026-04-18-group-1700", "status": "recording"}
```

---

## `noted status --session-id <id>`

| Code | Meaning |
|------|---------|
| 0    | Status returned |
| 2    | Unknown session ID |

**stdout:**

```json
{
  "ok": true,
  "session_id": "2026-04-18-jayde-1600",
  "status": "recording",
  "phase": "capturing",
  "is_paused": false,
  "started_at": "2026-04-18T16:00:03+10:00",
  "scheduled_end_time": "2026-04-18T17:00:00+10:00",
  "current_extension_minutes": 0,
  "pre_end_prompt_shown": false,
  "next_meeting_available": true,
  "output_dir": "/path/to/sessions/2026-04-18-jayde-1600"
}
```

`status` and `phase` are drawn from the locked vocabularies in §10.1 and §10.2 respectively. `is_paused` is an optional additional property on the runtime status shape. See also `schemas/runtime-status.v1.json`.

---

## `noted validate-manifest --manifest <path>`

Validates schema, required fields, and value ranges without starting a session.

| Code | Meaning |
|------|---------|
| 0    | Valid  |
| 2    | Invalid |

**stdout (valid):**

```json
{"ok": true, "schema_version": "1.0"}
```

**stdout (invalid):** `{"ok": false, "schema_version": "<value-if-readable>", "errors": ["..."]}` (shape is advisory for v1; exit code is the contract).

### Schema compatibility

- `schema_version` is `<major>.<minor>`.
- `noted` accepts any manifest whose **major** version matches its own.
- Unknown **minor** differences are tolerated forward: unknown fields are ignored.
- Missing required fields are not tolerated backward: validation fails.
- Unknown **major** version → validation error, exit 2.

---

## `noted version`

**stdout:**

```json
{"ok": true, "version": "<semver>", "manifest_schema_version": "1.0", "completion_schema_version": "1.0"}
```

---

## `noted wait --session-id <id> [--timeout-seconds N]`  *(optional)*

Blocks until a session is fully processed. For tests and deterministic ingest paths. File-watching `completion.json` is the normal path in v1.

| Code | Meaning |
|------|---------|
| 0    | Session reached a terminal state; `completion.json` present |
| 2    | Unknown session ID |
| 7    | Timeout |

---

## Concurrency

`noted` permits at most one **active capture** at a time (`start` returns exit 5 if one is already running). Post-processing of a just-stopped session may overlap with capture of the next session — this is the mechanism that makes back-to-back meetings possible (§9.4.2).

## Menubar ↔ CLI equivalence

Every popup button and every menubar menu item invokes the same code path as its CLI counterpart. There is no GUI-only behaviour. This keeps the runtime state model simple and makes each path testable from the shell (§9.8).

## Launch-time invariant

`briefing` invokes `noted start --manifest <path>` directly at pre-roll time. There is no `briefing session-start` wrapper (§18.2). `noted switch-next` invokes `noted start` internally on the pre-prepared next manifest (§13.2).

## Completion handoff

Completion handoff is **not** performed through the manifest — `hooks.completion_callback` is reserved and must be `null` in v1. When post-processing finishes, `noted` invokes `briefing session-ingest <session-dir>` directly (§27.6 decision (a)). This is outside the scope of the `noted` CLI listed here but is documented for completeness.
