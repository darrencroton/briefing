# Session Directory Layout (v1.0)

**Authoritative source:** Master Plan §11. This document fixes the on-disk contract that `briefing` and `noted` both depend on.

## Canonical layout

The names of files under `audio/` are determined directly by `mode.type`. See the *Audio files by mode* table below.

```
sessions/
  <session_id>/
    manifest.json
    runtime/
      status.json
      ui_state.json
    audio/
      raw_room.wav        (mode.type = in_person)
      raw_mic.wav         (mode.type = online or hybrid)
      raw_system.wav      (mode.type = online or hybrid)
    transcript/
      transcript.json
      transcript.txt
      segments.json
    diarization/
      diarization.json
    outputs/
      completion.json
    logs/
      noted.log
      briefing-ingest.stdout.log
      briefing-ingest.stderr.log
```

One session = one directory. Never share state between sessions. Never write outside the session directory except to the Obsidian note path specified in the manifest (`paths.note_path`).

## File-requirements table

The contract is not that every file always exists — it is that when a given condition has been reached, the listed files must exist.

| Condition              | Files that must exist                                    |
|------------------------|----------------------------------------------------------|
| Session starts         | `manifest.json`, `runtime/status.json`, `logs/noted.log` |
| Audio capture succeeds | At least one file in `audio/`                            |
| Transcript completes   | `transcript/transcript.json`, `transcript/transcript.txt` |
| Any terminal state     | `outputs/completion.json`                                |

Notes:

- `manifest.json` starts as a direct copy (or serialisation) of the manifest that was passed to `noted start`. While the session is active, `briefing watch` may refresh `next_meeting` in place when it discovers or invalidates the following meeting; `noted` re-reads `manifest.json` at end-of-meeting popup display time and uses the latest valid `next_meeting` value.
- `runtime/status.json` is rewritten on every state or phase transition (§10.3).
- `runtime/ui_state.json` is ephemeral UI state (popup history, button presses, icon state). `briefing` does not read it; it may be deleted without loss of session integrity (§10.4).
- `outputs/completion.json` is the only authoritative record of session outcome (guardrail 3). `briefing` reads it first; it must never be inferred from file presence or log parsing.
- Normally `noted` writes `outputs/completion.json` after post-processing. If a planned launch is blocked until the meeting window closes and `noted` never starts the session, `briefing watch` writes a failed `startup_failure` completion so the missed session still has a terminal artifact.

## Transcript outputs

Locked filenames (§26.3):

- `transcript.txt` — plain text, optionally with bracketed speaker labels if diarization succeeded.
- `transcript.json` — structured segments with timestamps, speaker labels, and confidence.
- `segments.json` — optional, used for debugging or downstream diarization analysis.

Speaker labels produced by the diarizer are opaque identifiers (`speaker_0`, `speaker_1`, …). Binding opaque IDs to real names is handled by `briefing` at summarisation time using the `host_name` and `participant_names` hints (§15.4, §16.3–§16.4).

## Audio files by mode

Files under `audio/` are a direct function of `mode.type`:

| `mode.type` | Files under `audio/` | Meaning |
|-------------|----------------------|---------|
| `in_person` | `raw_room.wav` | One microphone is expected to capture everyone in the room. |
| `online` | `raw_mic.wav`, `raw_system.wav` | Local microphone and remote/system audio are preserved separately. |
| `hybrid` | `raw_mic.wav`, `raw_system.wav` | Same capture layout as `online`; the semantic mode remains useful to `briefing` and note context. |

Default capture format is WAV 16-bit / 48 kHz mono.

Raw-audio retention is **not** part of the Phase 1 contract. The project-wide policy is master-plan §27.10 (30-day rolling window, FLAC-compressed), scheduled for Phase 5. Until that lands, `noted` retains raw audio indefinitely and consumers must not assume any automatic pruning.

## Stop reason → terminal status mapping

Reproduced from §11.5. This is the contract for what `terminal_status` an ingest consumer should expect given a `stop_reason`.

| `stop_reason`                  | Implies `terminal_status` |
|--------------------------------|---------------------------|
| `manual_stop`                  | `completed` (or `completed_with_warnings` if processing produced any) |
| `scheduled_stop`               | `completed` (or `completed_with_warnings`) |
| `auto_switch_to_next_meeting`  | `completed` (or `completed_with_warnings`) |
| `startup_failure`              | `failed` |
| `capture_failure`              | `failed` |
| `processing_failure`           | `completed_with_warnings` if audio was captured; `failed` otherwise |
| `forced_quit`                  | `completed_with_warnings` if any usable artefacts were flushed; `failed` otherwise |

## Retention invariants

- Raw audio is preserved whenever capture succeeds, even on downstream failure (guardrail 10). `briefing session-reprocess` depends on this.
- Logs remain in `logs/` alongside the session for the lifetime of the session directory.
- `completion.json` is never deleted independently of the session directory.

## Invariants for writers

- `noted` writes everything in the session directory, including `logs/briefing-ingest.stdout.log` and `logs/briefing-ingest.stderr.log` (captured from the `briefing session-ingest` subprocess it spawns after completion).
- `briefing` writes `manifest.json` for calendar-driven sessions before `noted start` is invoked.
- Only `briefing` writes to the Obsidian note at `paths.note_path`; `noted` never touches it.
