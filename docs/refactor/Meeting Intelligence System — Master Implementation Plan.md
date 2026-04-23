# Meeting Intelligence System — Master Implementation Plan

**Status:** Draft v1.0 — awaiting sign-off on §27 (Open Questions) before implementation begins.

**Audience:** Developers implementing or extending the system.

-----

## Table of Contents

1. Introduction & Motivation
2. User Stories
3. Goals & Non-Goals
4. Design Principles
5. Canonical Architecture
6. End-to-End User Experience
7. Calendar Metadata Format
8. Session Manifest Schema
9. `noted` CLI Contract
10. Runtime State Model
11. Session Directory Structure
12. End-of-Meeting UX Contract
13. Next-Meeting Handoff
14. Recording Modes
15. Audio Capture & Transcription
16. Summarisation
17. Obsidian Integration Contract
18. Integration With Existing `briefing`
19. Failure Handling
20. Manual Override
21. Logging
22. Security & Privacy
23. Implementation Sequence
24. Quality Metrics & Success Criteria
25. Testing Strategy
26. Locked Vocabulary
27. Open Questions & Decisions to Resolve Before Implementation
28. Glossary
29. References

-----

## 1. Introduction & Motivation

### 1.1 Problem

A meeting’s value usually lives in what was *decided* and what was *agreed to be done*, not in the recording itself. Today those artefacts are lost to memory, scattered across notebooks, or reconstructed imperfectly after the fact. Existing transcription tools prioritise the transcript as the product; the transcript is the least useful output.

In-person meetings are the hardest case. They are where most high-value conversations happen, and where existing tooling is weakest — no meeting client is running, no hooks are available, diarization is unreliable, and the audio environment is uncontrolled.

### 1.2 Outcome

A local, calendar-driven system that:

1. Detects meetings worth recording from the user’s calendar.
2. Captures audio unobtrusively (starting with an audible signal to participants).
3. Transcribes and diarizes offline.
4. Produces a short, structured, useful summary.
5. Writes that summary directly into the same Obsidian meeting note that already holds the *pre*-meeting briefing — without the user having to touch files.

### 1.3 Why Two Components

The work splits cleanly along a responsibility line:

- **Orchestration, calendar interpretation, policy, summarisation, and note writing** — tasks that happen before and after a meeting, that are stateless per run, and that already exist as a working Python application (`briefing`).
- **Audio capture, live recording state, and in-meeting UI** — tasks that must run continuously during a meeting, in a menubar app with a stable runtime, and that require macOS-specific capture code (`noted`, forked from HushScribe).

Keeping these separate avoids duplicating calendar logic, prevents the runtime agent from growing into a second workflow tool, and lets each component be tested and replaced independently.

-----

## 2. User Stories

### 2.1 Primary: In-person 1:1

> *As the host of a recurring 1:1 in the office, I want my meeting note to be waiting for me afterward with a short summary and action items, so I can review it on the walk back to my desk instead of scribbling during the conversation.*

### 2.2 Primary: Back-to-back meetings

> *As the host of two meetings scheduled back-to-back, I want the first recording to stop and the second to start automatically when I move rooms, so I never have to think about recording state mid-transition.*

### 2.3 Secondary: Online meeting

> *As a remote participant in a video call, I want the system to capture both my microphone and the call audio, so the summary reflects everyone who spoke, not just me.*

### 2.4 Secondary: Ad hoc recording

> *As someone who has just walked into an unscheduled conversation that turned important, I want to start a recording manually from the menubar and still get a useful summary afterwards.*

### 2.5 Recovery

> *As a user whose laptop crashed mid-meeting, I want the raw audio to still be on disk so I can re-run the transcription and summary later without re-living the meeting.*

### 2.6 Quality floor

> *As a host who doesn’t want false attributions, I would rather have a summary that says “a participant raised a concern about X” than one that confidently names the wrong person.*

-----

## 3. Goals & Non-Goals

### 3.1 Goals

- Calendar-driven automatic recording.
- Reliable in-person capture as the primary case.
- Structured, concise summaries in Obsidian.
- Clean separation between orchestration (`briefing`) and capture (`noted`).
- Graceful degradation under partial failure.
- Extensibility on top of the existing `briefing` application.

### 3.2 Non-Goals (v1)

- Real-time live transcription during the meeting.
- A transcript reader / editor UI.
- Speaker enrolment / voice profiles.
- Multi-device / multi-host synchronisation.
- Cloud storage of audio or transcripts.
- A full task-management layer — action items are emitted into the note; follow-through is the user’s.

-----

## 4. Design Principles

1. **Summary-first.** Transcript quality is a means to an end. The summary is the product.
2. **Real-world first.** In-person meetings are the primary case, even though they are the harder engineering problem.
3. **One source of truth per concern.** `briefing` owns *what* a meeting is; `noted` owns *whether it is actually recording*. Neither duplicates the other’s state.
4. **Strict contracts, loose coupling.** Components interact through a versioned manifest, a small CLI, and a completion file. No shared hidden state, no shared library code required.
5. **Correctness over confidence.** When speaker attribution is uncertain, the summary uses speaker-agnostic language rather than guess.
6. **Retain the irreplaceable.** Raw audio is kept long enough that a failed transcription or summary can be rerun without the user re-hosting the meeting.
7. **Extend, don’t rebuild.** Calendar access, LLM invocation, note management, prior-context gathering, and launchd automation already exist in `briefing`. New functionality is added as adapters and subcommands, not as a second application.

-----

## 5. Canonical Architecture

### 5.1 Components

**`briefing`** — the orchestration brain. An existing Python 3.13+ CLI app, `uv`-managed, running under `launchd` on macOS. Already handles: EventKit calendar ingestion, series configuration, source adapters (`previous_note`, `slack`, `notion`, `file`), LLM CLI invocation (Claude, Codex, Copilot, Gemini), and Obsidian note writing with a managed `## Briefing` block.

**`noted`** — the menubar capture agent. A fork of HushScribe, reduced in scope: removes summarisation, meeting detection, and transcript viewer; retains audio capture, ASR, diarization, and file output; adds a CLI, manifest loader, session directory writer, menubar UI, and end-of-meeting prompt logic.

### 5.1.1 Why Two Components, Not One

A reasonable question is why `noted`‘s functionality isn’t folded into `briefing` as a Python module. The answer is lifecycle mismatch. `briefing` runs briefly, on a schedule, and exits. `noted` runs continuously, responds to user input in real time, and holds audio hardware. Combining them would force `briefing` to become a long-running UI application or force `noted` to take on calendar and note-writing logic it shouldn’t own. Keeping them separate lets each live in its natural process model and be tested independently.

### 5.2 Data Flow

```
Calendar Event
     │
     ▼
briefing (detect + parse + plan)
     │   generates manifest.json
     ▼
noted (capture + transcribe + diarize)
     │   writes completion.json + transcript
     ▼
briefing (ingest + summarise + write note)
     │
     ▼
Obsidian meeting note
```

### 5.3 Source of Truth

|Concern                                 |Owner                                                             |
|----------------------------------------|------------------------------------------------------------------|
|What meeting this is                    |`briefing`                                                        |
|Calendar metadata                       |`briefing`                                                        |
|Mode (`in_person` / `online` / `hybrid`)|`briefing`                                                        |
|Scheduled end time                      |`briefing`                                                        |
|Whether a next meeting exists           |`briefing`                                                        |
|Output paths                            |`briefing`                                                        |
|Session manifest contents               |`briefing` (exception: ad hoc manifests written by `noted`, §20.1)|
|Launching a session from a manifest     |`noted`                                                           |
|Whether a session is actually running   |`noted`                                                           |
|Local capture / transcription state     |`noted`                                                           |
|Whether runtime prompts have been shown |`noted`                                                           |
|Whether a session was extended          |`noted`                                                           |
|Capture / processing success or failure |`noted`                                                           |
|Summary content                         |`briefing` (via LLM)                                              |
|Obsidian note contents                  |`briefing`                                                        |

### 5.4 Interaction Boundary

The two components communicate only through:

- **Session manifest** (JSON file; normally written by `briefing` and read by `noted`; for ad hoc sessions, written by `noted` from its own defaults per §20.1) — see §8.
- **`noted` CLI** — see §9.
- **Runtime status file** (JSON file written by `noted`, readable by `briefing` for diagnostics) — see §10.
- **Completion file** (JSON file written by `noted`, read by `briefing` on ingest) — see §11.

No shared in-memory state. No shared library. No inter-process direct IPC in v1.

-----

## 6. End-to-End User Experience

### 6.1 The Common Path

1. User schedules a meeting. For recurring or named series configured in `briefing` (the common case), no calendar-note action is required — the series YAML supplies all metadata by default. For a one-off meeting not covered by a series, the user adds a `noted config` marker in the event notes (see §7). Calendar notes can also be used to override series defaults on a per-instance basis.
2. `briefing` detects the event and invokes `noted start` during a **pre-roll window** before `start_time` (see §6.1.1) so that capture is already stable by the time the meeting begins.
3. `noted` plays a short bell at the moment actual capture begins and sets the menubar icon to “recording”.
4. The meeting proceeds. `noted` captures audio continuously, maintains runtime state, and is otherwise silent.
5. At `scheduled_end − 5 minutes`, `noted` plays a beep and shows a popup with **Stop**, **+5 minutes**, and (if a next meeting exists) **Next Meeting**.
6. The user either clicks a button or does nothing. Default behaviour is covered in §12.
7. When the session stops, `noted` finalises audio promptly and returns. ASR and diarization run asynchronously in the background. `completion.json` is written when post-processing finishes.
8. `briefing` ingests the completed session, runs summarisation, and writes the summary into the Obsidian meeting note.
9. The user opens Obsidian and finds the summary already written.

### 6.1.1 Pre-Roll Buffer

`briefing` targets starting `noted` capture **90 seconds before** the scheduled `start_time` by default. This buffer absorbs the real-world delays that otherwise cause the first 10–30 seconds of a meeting to be missed:

- macOS waking from sleep.
- Audio device acquisition (external mic enumeration, Bluetooth reconnection).
- `noted` cold start.
- TCC permission prompts on first run.
- Transient system load.

The pre-roll window is a setting (`pre_roll_seconds`, default 90, range 60–180) in `briefing`’s configuration. If capture is stable earlier than `start_time`, raw audio simply includes a short pre-meeting buffer; the recording-start bell still plays at the moment capture actually begins, not at `start_time`. Summarisation treats pre-`start_time` audio as warm-up and is free to ignore it.

### 6.2 What the User Sees

- **Calendar:** the event they already had.
- **Menubar:** an icon whose state reflects idle / recording / processing.
- **Popup:** at most once per meeting, five minutes before the scheduled end.
- **Obsidian note:** the same note that already contains their `## Briefing` block, now additionally containing a managed `## Summary` block.

### 6.3 What the User Does *Not* Do

- Open files.
- Start or stop recording manually (on the common path).
- Copy, paste, upload, download, or attach anything.
- Wait for transcription to finish before leaving the room.

### 6.4 Menubar Menu

Clicking the `noted` menubar icon opens a small menu with these items:

- **Start** — visible only when idle. Starts an ad hoc session (§20). Calendar-driven sessions are launched automatically by `briefing`, not from this menu.
- **Stop** — visible only when a session is active. Equivalent to the popup’s **Stop** button.
- **Status** — opens a small read-only panel showing session ID, elapsed time, current phase, and scheduled end.
- **Settings** — opens the settings panel (§20.4 content).
- **Quit** — quits `noted`. Confirmation required if a session is active.

### 6.5 Menubar Icon States

|Icon      |Condition                                                                          |
|----------|-----------------------------------------------------------------------------------|
|Neutral   |`idle` — no session                                                                |
|Recording |`starting` or `recording`                                                          |
|Processing|`stopping` or `processing`                                                         |
|Warning   |last session ended `failed` or `completed_with_warnings`, until next session starts|

The icon reflects the runtime status file (§10.3). It does not display a numerical countdown.

### 6.6 Recording-Start Bell

A short audible bell (≈ 0.5 s, ≈ 70 dB at typical laptop volume) is played by `noted` in the moment between `acquiring_audio_resources` and `capturing`. The bell is mandatory in v1 and is not a user-toggleable setting. Its purpose is transparency: anyone within earshot is made aware that recording has begun. A separate distinct beep is used for the end-of-meeting popup (§12.1) so the two cues are not confused.

-----

## 7. Calendar Metadata Format

### 7.1 Purpose

Calendar event notes are the per-event override mechanism and the entry point for one-off meetings. For series-matched events, the series YAML in `briefing` supplies all metadata by default — calendar notes are optional. For one-off events without a matching series, a `noted config` marker in the notes block opts the event into the recording workflow and supplies its metadata. The format is plain text, case-insensitive, and designed to be edited by hand.

### 7.2 Canonical Fields

```
noted config
mode: in_person | online | hybrid
attendees: <integer>
participants: Name 1, Name 2, Name 3
record: true | false
speaker_count_hint: <integer>
```

If `speaker_count_hint` is not set explicitly, `briefing` derives it from `attendees` (falling back to the length of `participants`); see §7.3 and §8.5.

**Optional (future):**

```
audio_app_bundle_id: us.zoom.xos
location_type: office | home | seminar_room
```

### 7.3 Parsing Rules

- Keys are case-insensitive.
- Unknown keys are ignored (warned, not errored).
- Malformed values produce a warning and a sane default; the workflow continues.
- If `attendees` and the length of `participants` disagree, both are preserved and a warning is logged. `participants` is a hint, not a count.
- `record: false` suppresses recording even if the event matches an active series.
- **Precedence.** For series-matched events, metadata is resolved in the following order, highest priority first: (1) calendar-note values, (2) series YAML defaults, (3) `briefing` global defaults, (4) hard-coded defaults. A calendar-note value always wins over a series YAML default for the same field.
- **`speaker_count_hint` fallback.** If `speaker_count_hint` is not provided by either the calendar notes or the series YAML, `briefing` derives it in order: (1) `attendees`, (2) length of `participants`, (3) unset. This fallback is performed at manifest-assembly time in `briefing`; see §8.5.

### 7.4 `noted config` Grammar

The `noted config` marker is the per-event signal that this event should be processed by the recording workflow. It is **not required for events matched by a configured series**; those are processed automatically using series YAML defaults. It **is required for one-off events** not covered by any series.

- Must appear on a line by itself within the event notes.
- Case-insensitive (`noted config`, `NOTED CONFIG`, `Noted Config` all match).
- A trailing colon is permitted (`noted config:`).
- Must appear before any metadata key/value lines; lines above it are ignored.
- Metadata key/value lines after the marker are parsed per §7.2 and override series YAML defaults per the precedence rule in §7.3.
- For an event that does **not** match a series: absence of the marker means the event is not processed for recording, regardless of any metadata values present.
- For an event that **does** match a series: the marker is optional. A series-matched event is processed with or without it. The marker’s purpose for series-matched events is to carry per-instance overrides — for example, `record: false` to skip this specific instance, or a `mode:` change for a one-off relocation.

How this marker interacts with `briefing`’s existing series YAML configuration is §27.2.

### 7.5 Examples

**One-off event (no matching series).** The `noted config` marker is required to opt the event into the workflow. Metadata fields fill from the notes, with anything absent falling back to `briefing` global defaults.

```
noted config
mode: in_person
attendees: 3
participants: Jayde, Ivo
record: true
```

**Series-matched event, no override.** Typically no metadata is needed at all. The series YAML supplies everything. The calendar notes can be empty.

**Series-matched event with a per-instance override.** The marker is optional here but is present to carry the override. This instance is skipped; the series is unchanged.

```
noted config
record: false
```

-----

## 8. Session Manifest Schema

### 8.1 Role

The manifest is the single handoff object describing one meeting instance. `briefing` is the normal author (for calendar-driven sessions); `noted` is the author only for ad hoc sessions (§20.1). The reader is always `noted`. Once written, a manifest must not be modified — runtime state lives in separate files (§10, §11).

### 8.2 Canonical Schema (v1.0)

```json
{
  "schema_version": "1.0",
  "session_id": "2026-04-18-jayde-1600",
  "created_at": "2026-04-18T15:54:12+10:00",
  "meeting": {
    "event_id": "calendar-event-id",
    "series_id": "jayde",
    "title": "Jayde 4–5pm",
    "start_time": "2026-04-18T16:00:00+10:00",
    "scheduled_end_time": "2026-04-18T17:00:00+10:00",
    "timezone": "Australia/Melbourne",
    "location": "Office 3.21"
  },
  "mode": {
    "type": "in_person",
    "audio_strategy": "room_mic"
  },
  "participants": {
    "host_name": "Darren",
    "attendees_expected": 3,
    "participant_names": ["Jayde", "Ivo"],
    "names_are_hints_only": true
  },
  "recording_policy": {
    "auto_start": true,
    "auto_stop": true,
    "default_extension_minutes": 5,
    "max_single_extension_minutes": 5,
    "pre_end_prompt_minutes": 5,
    "no_interaction_grace_minutes": 5
  },
  "next_meeting": {
    "exists": true,
    "event_id": "calendar-event-id-2",
    "title": "Group Meeting",
    "start_time": "2026-04-18T17:00:00+10:00",
    "manifest_path": "/path/to/sessions/2026-04-18-group-1700/manifest.json"
  },
  "paths": {
    "session_dir": "/path/to/sessions/2026-04-18-jayde-1600",
    "output_dir": "/path/to/sessions/2026-04-18-jayde-1600",
    "note_path": "/path/to/obsidian/Meetings/Jayde/2026-04-18 Jayde 4-5pm.md"
  },
  "transcription": {
    "asr_backend": "faster-whisper",
    "diarization_enabled": true,
    "speaker_count_hint": 3
  },
  "hooks": {
    "completion_callback": null
  }
}
```

### 8.3 Required vs Optional Fields

**Required:**

- `schema_version`, `session_id`, `created_at`
- `meeting.event_id`, `meeting.title`, `meeting.start_time`, `meeting.scheduled_end_time`, `meeting.timezone`
- `mode.type`
- `participants.host_name`, `participants.names_are_hints_only`
- `recording_policy.auto_start`, `recording_policy.auto_stop`, `recording_policy.default_extension_minutes`, `recording_policy.pre_end_prompt_minutes`, `recording_policy.no_interaction_grace_minutes`
- `next_meeting.exists`
- `paths.session_dir`, `paths.output_dir`, `paths.note_path`
- `transcription.asr_backend`, `transcription.diarization_enabled`

**Ad hoc exception:** `meeting.event_id` may be `null` and `meeting.scheduled_end_time` may be `null` for ad hoc sessions (§20.1). `meeting.series_id` is also permitted to be absent in that case. All other required fields must be present with real values.

**Optional but recommended when available:**

- `meeting.series_id` (absent for ad hoc sessions)
- `meeting.location`
- `mode.audio_strategy` (if absent, `noted` derives it from `mode.type` per §14.1)
- `participants.attendees_expected`, `participants.participant_names`
- `next_meeting.event_id`, `next_meeting.title`, `next_meeting.start_time`, `next_meeting.manifest_path`
- `transcription.speaker_count_hint` (derived from `attendees` if not set — see §7.3 and §8.5), `transcription.language` (BCP-47, e.g. `en-AU`; defaults to `noted`’s configured language)

**Reserved (present in v1.0 for forward compatibility; not yet consumed):**

- `recording_policy.max_single_extension_minutes` — reserved for §27.12.
- `hooks.completion_callback` — reserved for a future per-session callback mechanism. Always `null` in v1.

### 8.4 Schema Compatibility

- `schema_version` is `<major>.<minor>`.
- `noted` accepts any manifest whose major version matches its own; minor version differences are tolerated forward (unknown fields ignored) but not backward (missing required fields fail validation).
- Unknown major version → validation error, exit 2.

### 8.5 `speaker_count_hint`

Advisory only. May improve diarization; must not be required; may be inaccurate. Never treated as ground truth.

**Default derivation.** When `speaker_count_hint` is not set explicitly in either calendar notes or the series YAML, `briefing` populates it at manifest-assembly time using, in order of precedence: (1) `participants.attendees_expected`, (2) the length of `participants.participant_names`, (3) unset. This default is almost always correct for standard meetings. For settings where attendee count and expected-speaker count diverge materially (a large seminar with a silent audience, for example), the hint should be set explicitly.

-----

## 9. `noted` CLI Contract

### 9.1 Principles

The CLI must be small, stable, scriptable, deterministic, and machine-friendly. No GUI automation. No screen scraping.

### 9.2 Commands

**Required:**

```
noted start             --manifest <path>
noted stop              --session-id <id>
noted extend            --session-id <id> --minutes N
noted switch-next       --session-id <id>
noted status            --session-id <id>
noted validate-manifest --manifest <path>
noted version
```

**Optional (later):**

```
noted wait              --session-id <id> [--timeout-seconds N]
noted list-sessions
noted tail-log          --session-id <id>
noted resume            --session-id <id>
```

### 9.3 `start`

**Command:** `noted start --manifest /path/to/manifest.json`

**Behaviour:** Validates the manifest, creates the session directory structure, acquires audio resources, begins capture, returns immediately once recording is stable — or exits non-zero on failure.

**Exit codes:**

|Code|Meaning                                                    |
|----|-----------------------------------------------------------|
|0   |Session successfully started                               |
|2   |Invalid manifest                                           |
|3   |Required permissions missing (microphone, screen recording)|
|4   |Audio device failure                                       |
|5   |Session already running                                    |
|6   |Internal startup failure                                   |

**Stdout** (single JSON line):

```json
{"ok": true, "session_id": "2026-04-18-jayde-1600", "status": "recording", "pid": 12345, "session_dir": "/path/to/sessions/2026-04-18-jayde-1600"}
```

**Stderr:** human-readable diagnostics only.

### 9.4 `stop`

**Command:** `noted stop --session-id <id>`

**Behaviour:** Finalises **capture only** and returns. ASR and diarization continue asynchronously as part of the session’s post-processing phase. `stop` is deliberately fast so that a back-to-back **Next Meeting** handoff is possible.

On return:

- Capture has stopped.
- Raw audio has been flushed and fsynced.
- Session state has transitioned from `recording` (or `stopping`) to `processing`.
- `completion.json` has **not** been written yet — it is written at the end of post-processing, not at stop time.

Post-processing runs in the background and proceeds through the phases listed in §10.2 (`flushing_audio` → `running_asr` → `running_diarization` → `writing_outputs` → `finished`). `noted status` reflects progress. `completion.json` appears only when processing ends (success, warning, or failure).

**Exit codes:**

|Code|Meaning                                                         |
|----|----------------------------------------------------------------|
|0   |Capture stopped; post-processing started                        |
|2   |Unknown session ID                                              |
|3   |Session not running                                             |
|4   |Stop-capture failed (raw audio may still be recoverable on disk)|

**Stdout:**

```json
{"ok": true, "session_id": "2026-04-18-jayde-1600", "status": "processing", "audio_finalised": true}
```

### 9.4.1 `wait` (optional)

For tests or deterministic ingest paths, a `wait` command blocks until a session is fully processed:

**Command:** `noted wait --session-id <id> [--timeout-seconds N]`

**Exit codes:**

|Code|Meaning                                                    |
|----|-----------------------------------------------------------|
|0   |Session reached a terminal state; `completion.json` present|
|2   |Unknown session ID                                         |
|7   |Timeout                                                    |

This is optional in v1; file-watching `completion.json` is the normal path.

### 9.4.2 Concurrency

`noted` permits at most **one active capture** at a time (exit code 5 from `start`). However, post-processing of a just-stopped session may overlap with capture of the next session. This is the mechanism that makes back-to-back meetings possible: while session B captures, session A’s ASR and diarization run in the background. Resource contention is expected to be modest for typical meeting lengths on a current-generation MacBook Pro; Phase 5 may revisit if it becomes an issue.

### 9.5 `status`

**Command:** `noted status --session-id <id>`

**Exit codes:**

|Code|Meaning           |
|----|------------------|
|0   |Status returned   |
|2   |Unknown session ID|

**Stdout:**

```json
{
  "ok": true,
  "session_id": "2026-04-18-jayde-1600",
  "status": "recording",
  "phase": "capturing",
  "started_at": "2026-04-18T16:00:03+10:00",
  "scheduled_end_time": "2026-04-18T17:00:00+10:00",
  "current_extension_minutes": 0,
  "pre_end_prompt_shown": false,
  "next_meeting_available": true,
  "output_dir": "/path/to/sessions/2026-04-18-jayde-1600"
}
```

### 9.6 `validate-manifest`

**Command:** `noted validate-manifest --manifest /path/to/manifest.json`

**Behaviour:** Validates schema, required fields, and value ranges without starting a session.

**Exit codes:**

|Code|Meaning|
|----|-------|
|0   |Valid  |
|2   |Invalid|

**Stdout:**

```json
{"ok": true, "schema_version": "1.0"}
```

### 9.7 `extend` and `switch-next` (popup-driven actions)

The end-of-meeting popup’s **+5 minutes** and **Next Meeting** buttons are implemented by `noted`’s internal runtime. For scriptability and parity with the popup, they are also exposed as CLI commands.

**`noted extend --session-id <id> --minutes N`**

Extends the scheduled stop by N minutes (typically 5). Idempotent within a single popup cycle; respects the extension policy in §12.4.

|Code|Meaning                                            |
|----|---------------------------------------------------|
|0   |Extension applied                                  |
|2   |Unknown session ID                                 |
|3   |Session not in `recording`                         |
|6   |Extension rejected (policy — e.g. already extended)|

**`noted switch-next --session-id <id>`**

Stops the current capture immediately (same fast-stop behaviour as `stop`, §9.4), writes `stop_reason: auto_switch_to_next_meeting`, and launches the next session by invoking `noted start --manifest <next_manifest_path>` on the pre-prepared manifest referenced by the current manifest’s `next_meeting.manifest_path`. Returns as soon as the current capture is finalised and the next-session launch has either succeeded or failed; post-processing of the old session and startup of the new session proceed concurrently.

|Code|Meaning                                                                                                                                   |
|----|------------------------------------------------------------------------------------------------------------------------------------------|
|0   |Current session stopped; next session started                                                                                             |
|2   |Unknown session ID                                                                                                                        |
|3   |No eligible next meeting (manifest had `next_meeting.exists: false`)                                                                      |
|4   |Stop-capture failed                                                                                                                       |
|8   |Next manifest missing or invalid (e.g., invalidated by `briefing watch` between planning and handoff); current session is stopped normally|

### 9.8 Menubar → CLI Equivalence

Every popup action and every menubar menu action has a 1:1 CLI equivalent. There is one canonical code path per action, invoked either directly from the GUI or from the shell. This keeps the runtime state model simple, makes each path testable from the shell, and removes any hidden GUI-only behaviour.

-----

## 10. Runtime State Model

### 10.1 Session States

|State                    |Description                           |
|-------------------------|--------------------------------------|
|`idle`                   |No active session                     |
|`starting`               |Session initialising                  |
|`recording`              |Capture in progress                   |
|`stopping`               |Graceful stop initiated               |
|`processing`             |Post-session ASR / diarization running|
|`completed`              |Session finished successfully         |
|`completed_with_warnings`|Session finished with non-fatal issues|
|`failed`                 |Session failed                        |

### 10.2 Processing Phases

Finer-grained indicator within `recording`, `stopping`, or `processing`:

- `validating_manifest`
- `acquiring_audio_resources`
- `capturing`
- `flushing_audio`
- `running_asr`
- `running_diarization`
- `writing_outputs`
- `finished`
- `failed_startup`
- `failed_capture`
- `failed_processing`

### 10.3 Runtime State File

`noted` maintains a machine-readable file at `<session_dir>/runtime/status.json`. It is rewritten on every state or phase transition. It exists so that `briefing`, or a crash investigator, can inspect state without relying on the CLI or on a running process.

**Example:**

```json
{
  "session_id": "2026-04-18-jayde-1600",
  "status": "recording",
  "phase": "capturing",
  "started_at": "2026-04-18T16:00:03+10:00",
  "updated_at": "2026-04-18T16:27:14+10:00",
  "scheduled_end_time": "2026-04-18T17:00:00+10:00",
  "current_extension_minutes": 0,
  "pre_end_prompt_shown": false,
  "last_error": null
}
```

### 10.4 UI State File

`noted` maintains a separate file at `<session_dir>/runtime/ui_state.json` for ephemeral UI state that is not part of the session’s canonical record: popup display history, button-press log, icon state history. This file exists so that UI state survives a menubar restart within a running session without polluting `status.json`. `briefing` does not read it. It may be deleted without loss of session integrity.

-----

## 11. Session Directory Structure

### 11.1 Canonical Layout

```
sessions/
  <session_id>/
    manifest.json
    runtime/
      status.json
      ui_state.json
    audio/
      raw_room.wav        (in_person)
      raw_mic.wav         (online / hybrid)
      raw_system.wav      (online / hybrid)
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
      briefing.log
```

### 11.2 File Requirements by State

|Condition             |Files that must exist                                    |
|----------------------|---------------------------------------------------------|
|Session starts        |`manifest.json`, `runtime/status.json`, `logs/noted.log` |
|Audio capture succeeds|At least one file in `audio/`                            |
|Transcript completes  |`transcript/transcript.json`, `transcript/transcript.txt`|
|Any terminal state    |`outputs/completion.json`                                |

### 11.3 Completion File

`completion.json` is the canonical machine-readable final result. It is what `briefing` reads first when deciding how to proceed.

```json
{
  "schema_version": "1.0",
  "session_id": "2026-04-18-jayde-1600",
  "manifest_schema_version": "1.0",
  "terminal_status": "completed_with_warnings",
  "stop_reason": "scheduled_stop",
  "audio_capture_ok": true,
  "transcript_ok": true,
  "diarization_ok": false,
  "warnings": ["diarization_confidence_low"],
  "errors": [],
  "completed_at": "2026-04-18T17:06:51+10:00"
}
```

`manifest_schema_version` echoes the version of the manifest that produced this session, for traceability when schemas evolve.

### 11.4 Disk Layout Rule

One session = one directory. Never share state between sessions. Never write outside the session directory except to the Obsidian note path specified in the manifest.

### 11.5 Stop Reason → Terminal Status Mapping

|`stop_reason`                |Implies `terminal_status`                                                         |
|-----------------------------|----------------------------------------------------------------------------------|
|`manual_stop`                |`completed` (or `completed_with_warnings` if processing produced any)             |
|`scheduled_stop`             |`completed` (or `completed_with_warnings`)                                        |
|`auto_switch_to_next_meeting`|`completed` (or `completed_with_warnings`)                                        |
|`startup_failure`            |`failed`                                                                          |
|`capture_failure`            |`failed`                                                                          |
|`processing_failure`         |`completed_with_warnings` if audio was captured; `failed` otherwise               |
|`forced_quit`                |`completed_with_warnings` if any usable artefacts were flushed; `failed` otherwise|

-----

## 12. End-of-Meeting UX Contract

### 12.1 Required Behaviour

At `scheduled_end_time − pre_end_prompt_minutes`, `noted` must:

- Play a beep (distinct from the recording-start bell).
- Show a popup with:
  - **Stop**
  - **+5 minutes**
  - **Next Meeting** *(only if `next_meeting.exists == true`)*

### 12.2 User Actions

|Action                |Behaviour                                                               |
|----------------------|------------------------------------------------------------------------|
|Click **Stop**        |Stop current session immediately                                        |
|Click **+5 minutes**  |Extend stop deadline by `default_extension_minutes`                     |
|Click **Next Meeting**|Stop current session; launch next session from the pre-prepared manifest|

### 12.3 No-Interaction Rules

|Condition                          |Behaviour                                                                                                      |
|-----------------------------------|---------------------------------------------------------------------------------------------------------------|
|No interaction, no next meeting    |Stop at `scheduled_end_time`                                                                                   |
|No interaction, next meeting exists|Continue until `scheduled_end_time + no_interaction_grace_minutes`; auto-switch to next if still no interaction|

### 12.4 Extension Policy

In v1, a user may click **+5 minutes** only once per session. The popup does not re-appear after an extension. Further extensions require a new popup policy; not in scope for v1 unless revisited in §27.

### 12.5 Ownership

- `noted`: popup display, countdown, extension bookkeeping, button events, audible cues, launching sessions from manifests.
- `briefing`: whether a next meeting is eligible, preparing the next manifest, keeping pre-prepared manifests current against the calendar.

-----

## 13. Next-Meeting Handoff

### 13.1 Principle

`noted` never searches the calendar, never computes what the next session is, and never writes its own manifest from calendar data. All next-meeting knowledge comes from the current manifest; `briefing` is the only component that writes manifests. `noted` is the only component that launches sessions — always by invoking `noted start --manifest <path>` on a manifest someone else (or, in the ad hoc case, `noted` itself) has prepared.

### 13.2 Flow

Before starting the current session, `briefing`:

1. Determines whether an eligible next meeting exists.
2. Prepares the next session’s manifest **in advance**, at the same time it prepares the current one, and writes it to disk. This is deliberate — the **Next Meeting** button must be able to fire instantly, without waiting for `briefing` to do work under time pressure.
3. Populates `next_meeting` in the current manifest, including `manifest_path` pointing at the pre-prepared next manifest.

On **Next Meeting** click or auto-switch, `noted`:

1. Stops capture on the current session (fast-stop per §9.4). Post-processing continues in the background.
2. Writes session state transitions to runtime files.
3. Invokes `noted start --manifest <next_manifest_path>` directly on the pre-prepared manifest. There is no round-trip through `briefing` at launch time — `briefing` has already done its job by writing the manifest in advance.

This preserves the source-of-truth rules in §5.3: `briefing` remains the only component that decides *what meeting this is* and the only component that writes manifests. `noted`’s role is to launch the session from the manifest it has been given.

### 13.3 Keeping Pre-Prepared Manifests Current

Because next-meeting manifests are written in advance, the calendar state at the moment of handoff may differ from the state at planning time (e.g., meeting B is cancelled or rescheduled while meeting A is happening). `briefing watch` is responsible for keeping pre-prepared manifests honest:

- On each tick, `briefing watch` checks pre-prepared next-manifests against current calendar state.
- If the corresponding event is cancelled, `briefing watch` **deletes** the pre-prepared manifest file and updates the current session’s `next_meeting.exists` in its own tracking; the running `noted` session will notice the missing manifest path on a switch attempt and degrade gracefully.
- If the event is rescheduled within tolerance, `briefing watch` rewrites the manifest in place.
- If the event is moved outside tolerance, the manifest is deleted.

If `noted switch-next` attempts to launch a manifest that has been deleted, it logs a warning, writes a completion file for the current session with `stop_reason: auto_switch_to_next_meeting` and a `next_manifest_missing` warning, and returns to `idle`. The user sees the menubar return to neutral; no new session starts. In the worst case where invalidation races the switch, `noted` launches on a stale manifest and records a few minutes of an empty room — not a disaster, and the summarisation step will reflect that.

### 13.4 Eligibility

`briefing` decides what “eligible next meeting” means: typically a meeting that starts within 15 minutes of the current scheduled end, has `record: true` (or is otherwise configured for recording), and does not overlap the current session by more than a small tolerance. Exact rules are `briefing`’s concern.

-----

## 14. Recording Modes

### 14.1 Supported Modes

|Mode       |`audio_strategy`    |Capture behaviour                                                                                                                   |
|-----------|--------------------|------------------------------------------------------------------------------------------------------------------------------------|
|`in_person`|`room_mic`          |Single high-quality audio input (typically an external USB mic or AirPods pretending to be the room mic). Offline ASR + diarization.|
|`online`   |`mic_plus_system`   |Capture microphone *and* system audio. Useful for video calls. Offline ASR.                                                         |
|`hybrid`   |`room_mic` (default)|Treated as `in_person` unless explicitly overridden.                                                                                |

### 14.2 Rationale

In-person is the primary case and hardest problem. Online is supported because it’s a low-cost addition — the ASR and summarisation pipeline is shared. Hybrid exists as a category label; it does not get its own capture strategy in v1.

### 14.3 System Audio on macOS

The macOS-specific mechanism for capturing system audio is an open decision (§27.8). Candidates are CoreAudio Tap (macOS 14.4+), ScreenCaptureKit audio taps, and third-party virtual devices (BlackHole, Loopback). Each has different entitlement and permission implications.

-----

## 15. Audio Capture & Transcription

### 15.1 Capture

- Always write raw audio as the capture proceeds; do not buffer the whole session in memory.
- Default format is WAV at 16-bit / 48 kHz mono for `in_person`. `online` mode may write mic and system channels as separate files and mix or process them post-capture.
- Raw audio is the most valuable irreplaceable artefact. It is retained after the session per the retention policy (§27.10).

### 15.2 ASR Backend

Default: `faster-whisper`. The manifest’s `transcription.asr_backend` field allows override in future; no other backend is required for v1. Model size selection (tiny / base / small / medium / large) is a `noted` setting, not a per-session manifest value.

### 15.3 Language

ASR is run in a single target language per session. The language is resolved, in order of precedence:

1. `manifest.transcription.language` if set (BCP-47, e.g. `en-AU`).
2. `noted`’s configured default language.
3. Automatic detection as a last resort (not recommended — slower and less accurate).

For the primary use case this defaults to `en-AU` in `noted` settings.

### 15.4 Diarization

Default: `pyannote` (TBC in §27.9). May fail cleanly — the pipeline must continue with a diarization-less transcript, and `diarization_ok: false` must be set in `completion.json` with a warning.

### 15.5 Transcript Outputs

- `transcript.txt` — plain text, optionally with bracketed speaker labels if diarization succeeded.
- `transcript.json` — structured segments with timestamps, speaker labels, and confidence.
- `segments.json` — optional, used for debugging or downstream diarization analysis.

-----

## 16. Summarisation

### 16.1 Owner

`briefing`, using the same LLM provider already configured for pre-meeting briefings. The post-meeting summary is produced by a new prompt template (e.g., `post_meeting_summary.md`) alongside the existing `pre_meeting_summary.md`.

### 16.2 Inputs

- Transcript (text + segments).
- Meeting title, series, and location from the manifest.
- `host_name` and (with caution) `participant_names`.
- Prior-context bundle as built by existing `briefing` sources for this series, when available.

### 16.3 Attribution Policy

|Confidence                                             |Behaviour                                                                                                  |
|-------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
|**High** (host speaking, or clearly-identified speaker)|Name directly                                                                                              |
|**Medium** (diarization evidence is reasonably strong) |Name cautiously                                                                                            |
|**Low**                                                |Speaker-agnostic language: *“one participant noted…”*, *“a question was raised…”*, *“the group discussed…”*|

### 16.4 Hard Rule

`participant_names` from the calendar are **hints only**. They are never forced into the transcript or summary as ground-truth labels.

### 16.5 Output Style

- Structured Markdown.
- Short: typically 3–8 bullets or a short outline plus an action-items list.
- Timeline or narrative ordering is allowed but not required.
- Every action item should include, where extractable: *what*, *who*, *by when*.

-----

## 17. Obsidian Integration Contract

### 17.1 Goal

The summary is written into the *same* Markdown note that already holds the user’s pre-meeting `## Briefing` block. A user opening the note after a meeting sees briefing, summary, and their own notes in one place.

### 17.2 Managed Blocks

`briefing` already manages a `## Briefing` block and preserves everything from `## Meeting Notes` onward as user-owned, carried forward into subsequent notes as prior context. This plan introduces one additional managed block: the post-meeting summary. Its exact heading, position in the note, and behaviour relative to `## Meeting Notes` is the single most load-bearing undefined contract in this document (§27.4).

### 17.3 Managed-Block Invariants

Regardless of which option in §27.4 is chosen, the following must hold:

- The summary block must be idempotent: re-running summarisation replaces the block, not the surrounding content.
- The user’s own notes must never be touched.
- The pre-meeting `## Briefing` block must never be touched by the summary workflow.
- The managed block boundaries must be machine-detectable (comment markers or explicit heading) so that regeneration is safe.
- A note without the managed block is a valid input; the block is inserted on first summarisation.

### 17.4 Carry-Forward Interaction

`briefing`‘s `previous_note` source adapter currently feeds everything from `## Meeting Notes` onward into subsequent pre-meeting briefings as prior context. The summary block’s placement (§27.4) determines whether the machine-generated summary becomes part of that carry-forward:

- Under **option (a)** — summary above `## Meeting Notes` — the summary is *not* carried forward. Only the user’s own notes feed future briefings. This is simpler and prevents machine-generated content from contaminating the pre-briefing pipeline.
- Under **option (b)** — summary below `## Meeting Notes` — the summary *is* carried forward alongside user notes. This gives future briefings richer context but risks feedback loops.

This trade-off is part of the §27.4 decision and should be made deliberately, not by accident.

### 17.5 Note Path Resolution

`briefing`’s existing `[paths]` configuration and series mapping resolve the note path. For ad hoc sessions (no series), resolution falls back to a default directory defined in settings. Title-to-filename slug rules (handling em-dashes, colons, emoji, etc.) must be shared between pre- and post-meeting note creation to avoid divergence; any change must be made in one place.

### 17.6 Collision Policy

If the target note exists and contains a managed summary block, the block is replaced. If it exists without one, the block is inserted. The note is never silently overwritten.

### 17.7 Note Creation When Missing

If the target note does not exist at ingest time, `briefing` creates it from the standard `meeting_note.md` template and then inserts the managed summary block. This can happen when a meeting was recorded without a pre-meeting briefing (e.g., the calendar event was added last-minute, or briefing failed earlier in the day). The created note contains:

- Standard frontmatter per `meeting_note.md`.
- An empty `## Briefing` block (so the shape is identical to briefed notes).
- The managed summary block with the just-generated summary.
- An empty `## Meeting Notes` section for the user.

This keeps every meeting note structurally identical regardless of whether it was briefed, and keeps the user-owned `## Meeting Notes` section consistently the last thing in the file.

-----

## 18. Integration With Existing `briefing`

This plan *extends* `briefing`; it does not duplicate it. Dev team familiarity with the existing codebase is assumed. Key integration points:

### 18.1 What Already Exists (No New Work Required)

- EventKit calendar ingestion.
- `user_config/series/*.yaml` series definitions.
- `[paths]`, `[calendar]`, `[llm]`, `[logging]` configuration schema.
- Source adapters: `previous_note`, `slack`, `notion`, `file`.
- LLM CLI providers (`claude`, `codex`, `copilot`, `gemini`) with `effort`, `timeout_seconds`, `retry_attempts`.
- `pre_meeting_summary.md` prompt template.
- `meeting_note.md` note template.
- Managed `## Briefing` block with preservation of user content.
- `launchd` scheduling.
- `briefing validate` command.

### 18.2 What Must Be Added

- A new source adapter: `transcript`. Points at `<session_dir>/transcript/transcript.txt` (or `.json`) from a completed `noted` session. Uses the existing source-adapter interface so the LLM prompt assembly is unchanged in shape.
- A new prompt template: `post_meeting_summary.md`.
- New CLI subcommands (names for discussion in §27.3, but roughly):
  - `briefing session-plan --event-id <id>` — generate a manifest for a single detected event, with `next_meeting` lookahead. Used by `briefing watch` during planning and during invalidation sweeps.
  - `briefing session-ingest --session-dir <path>` — consume a completed `noted` session (reads `completion.json` + transcript) and write the summary into the Obsidian note. Invoked by `noted` when post-processing finishes, per §27.6.
  - `briefing session-reprocess --session-dir <path>` — rerun summarisation on an existing transcript. Essential for the retain-raw-audio recovery story.
- Extensions to the series YAML to supply the full default metadata set for series-matched events. Fields include: `record: true | false`, `mode`, `attendees_expected`, `participant_names`, `speaker_count_hint`, and the `transcription` block (ASR backend, model size, language, diarization on/off). These series-level values are the **primary source** of metadata for series-matched events; calendar-note values override them on a per-instance basis per §7.3. A user who intends the series to be recorded sets `record: true` in the series YAML once, and does not need to touch calendar notes thereafter.
- A trigger mechanism — how `briefing` is invoked near the start of a meeting rather than on a fixed launchd schedule. See §27.1. Whichever trigger model is chosen, `briefing` at pre-roll time invokes `noted start --manifest <path>` directly; there is no `briefing session-start` wrapper.
- A manifest-invalidation sweep in `briefing watch` (§13.3) so pre-prepared next-meeting manifests reflect current calendar state.

### 18.3 What Must *Not* Be Done

- Do not create a second orchestration layer in `noted`.
- Do not re-implement calendar access in `noted`.
- Do not bypass the source-adapter model by feeding the transcript directly to the LLM call site.
- Do not fork `briefing`’s note-writing logic for the summary block; reuse the managed-block mechanism and extend it.

-----

## 19. Failure Handling

### 19.1 Failure Cases to Handle in v1

- Missing microphone permission.
- Missing screen-recording permission (for `online` mode).
- Audio device unavailable at start.
- Audio device disappearing mid-capture.
- Invalid manifest.
- `start` called while a session is already active.
- `stop` called when no session is active.
- App crash during recording.
- ASR failure after successful capture.
- Diarization failure after successful ASR.
- Summarisation failure in `briefing` (LLM unreachable, timeout, provider error).
- Obsidian note write failure (path unwritable, disk full).

### 19.2 Required Behaviour

|Failure                                 |Behaviour                                                                                                                                         |
|----------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
|Capture never started                   |`terminal_status = failed`; no summary attempt; user-visible error in `noted`; `briefing` logs failure                                            |
|Capture succeeded, transcript failed    |`terminal_status = completed_with_warnings` or `failed`; **raw audio is retained**; `briefing` per §27.5 either writes a placeholder note or skips|
|Transcript succeeded, diarization failed|Proceed; summarise using speaker-agnostic style by default                                                                                        |
|Transcript succeeded, LLM summary failed|`briefing` preserves transcript references; writes a recoverable placeholder or retryable marker; `session-reprocess` can rerun later             |
|Obsidian note write fails               |Transcript and summary are preserved in the session directory; error logged; user alerted on next run                                             |

### 19.3 Recovery Principle

Raw audio is the irreplaceable artefact. It is retained whenever possible so that ASR, diarization, or summary failures can be corrected later without asking the user to re-host the meeting. `session-reprocess` exists to make this recovery a single command, not a forensic exercise.

-----

## 20. Manual Override

### 20.1 Manual Start

The `noted` menubar **Start** action starts an ad hoc unlinked session. Calendar-driven sessions arrive via `briefing` invoking `noted start` directly (§13), and back-to-back switches arrive via `noted switch-next`; neither uses the menubar.

For ad hoc sessions, `noted` constructs a **full, canonical manifest** (the same schema as §8.2) with defaults filled in from its own settings (§20.4). There is no separate ad hoc manifest variant.

**Rules for `noted`-constructed ad hoc manifests:**

- `meeting.event_id` is `null`.
- `meeting.series_id` is absent.
- `meeting.scheduled_end_time` is `null` — the session has no scheduled end. This relaxes the “required field” rule of §8.3 for ad hoc sessions only: `noted`’s manifest writer sets it to `null` and the end-of-meeting popup logic (§12) is suppressed.
- `participants.host_name` is taken from settings (§20.4).
- `participants.names_are_hints_only` is `true`.
- `mode.type` defaults to `in_person`.
- `recording_policy` is populated from defaults. With no `scheduled_end_time`, only manual stop ends the session.
- `next_meeting.exists` is `false`.
- `paths.session_dir`, `paths.output_dir`, `paths.note_path` are resolved against settings. `note_path` points to the default ad hoc notes directory.
- `transcription` fields are filled from `noted` settings.

**Example ad hoc manifest:**

```json
{
  "schema_version": "1.0",
  "session_id": "adhoc-2026-04-18-154500",
  "created_at": "2026-04-18T15:45:00+10:00",
  "meeting": {
    "event_id": null,
    "title": "Ad hoc recording",
    "start_time": "2026-04-18T15:45:00+10:00",
    "scheduled_end_time": null,
    "timezone": "Australia/Melbourne"
  },
  "mode": {"type": "in_person", "audio_strategy": "room_mic"},
  "participants": {"host_name": "Darren", "names_are_hints_only": true},
  "recording_policy": {
    "auto_start": false,
    "auto_stop": false,
    "default_extension_minutes": 5,
    "pre_end_prompt_minutes": 5,
    "no_interaction_grace_minutes": 5
  },
  "next_meeting": {"exists": false},
  "paths": {
    "session_dir": "/path/to/sessions/adhoc-2026-04-18-154500",
    "output_dir": "/path/to/sessions/adhoc-2026-04-18-154500",
    "note_path": "/path/to/obsidian/Meetings/Adhoc/2026-04-18 Ad hoc recording.md"
  },
  "transcription": {"asr_backend": "faster-whisper", "diarization_enabled": true}
}
```

Ad hoc sessions still produce raw audio, a transcript, and a completion file. Summarisation of an ad hoc session falls back to a “no series context” path in `briefing`, which still produces a summary but without prior-context enrichment.

### 20.2 Manual Stop

Manual **Stop** is always permitted for the active session, regardless of timing.

### 20.3 Post Hoc Linking

Linking an ad hoc session to a calendar event that turned up later (e.g., the user realises this was meant to be a series meeting) is deferred. Users may manually move the resulting note if desired.

### 20.4 `noted` Settings

`noted` maintains a small settings file at a platform-standard location (e.g., `~/Library/Application Support/noted/settings.toml`). It is deliberately minimal. In v1:

|Key                  |Purpose                                                                              |
|---------------------|-------------------------------------------------------------------------------------|
|`host_name`          |Default host name if not provided in a manifest                                      |
|`default_audio_input`|Audio device used for `in_person` capture                                            |
|`asr_backend`        |Default ASR backend (e.g., `faster-whisper`)                                         |
|`asr_model_size`     |One of `tiny`, `base`, `small`, `medium`, `large`                                    |
|`asr_language`       |BCP-47 language tag (default `en-AU` per the primary use case)                       |
|`log_level`          |One of `debug`, `info`, `warn`, `error`                                              |
|`output_root`        |Default parent directory for session directories when a manifest does not specify one|

Settings that belong to a specific meeting (mode, participants, etc.) live in the manifest, not here. Settings do not grow `noted` into a second workflow tool.

-----

## 21. Logging

### 21.1 `noted`

Must log: manifest path used, start time, audio device selection, permission issues, prompt display events, extension events, stop reason, transcript completion, terminal state, unexpected exceptions.

### 21.2 `briefing`

Must log (in addition to its existing logging): event detection, metadata parse results, manifest generation path, `noted` invocation commands and exit codes, completion-file ingestion, summarisation invocation, note write result, final workflow state.

### 21.3 Log Location

- Per-session log files at `<session_dir>/logs/`.
- Aggregated rolling log at `briefing`’s existing `logs/` directory.

-----

## 22. Security & Privacy

### 22.1 Defaults

- All audio, transcript, and summary artefacts are stored locally by default.
- No cloud transcription.
- No telemetry.

### 22.2 LLM Calls

`briefing` sends transcript text to the configured LLM CLI. Whether that provider is local or remote is a per-user policy decision, owned by `briefing`’s existing `[llm]` configuration. No change to that model is introduced here.

### 22.3 Recording Notification

Every recording starts with an audible bell played by `noted`. This is a deliberate transparency signal: anyone in the room can hear that a recording has begun, and the menubar icon reflects recording state throughout.

### 22.4 User Responsibility

In jurisdictions requiring all-party consent, verbal disclosure remains the user’s responsibility. The system provides an audible start signal; it does not independently disclose to participants.

### 22.5 Retention

Raw audio, transcripts, and the session directory are retained per a retention policy that is still to be finalised (§27.10). Until finalised, the default is “retain indefinitely, rely on user to prune” — which is safe for recovery but not for privacy hygiene over time.

### 22.6 API Keys & Secrets

Already handled by `briefing`’s existing env-file pattern (`~/.env.briefing`) for Slack and Notion tokens, and by provider CLI authentication (`claude auth login` etc.). No new secret-handling surface is introduced.

-----

## 23. Implementation Sequence

Each phase has a success criterion that must be demonstrable before moving on.

### Phase 1 — Lock Contracts

- Manifest schema v1.0 frozen.
- `noted` CLI contract frozen (commands, exit codes, stdout shape).
- Session directory layout frozen.
- Runtime state model and completion file frozen.
- Open questions in §27 resolved and this document updated.

**Success criterion:** `noted validate-manifest` runs against fixture manifests and returns correct exit codes. Any dev on the team can read this document cold and implement a mock `noted` that passes the contract tests.

### Phase 2 — Minimal `noted` Runtime

- `validate-manifest`, `start`, `stop`, `status`, `version`.
- Session directory creation.
- Raw audio capture (`in_person` only).
- Fast-stop behaviour: `stop` returns after audio is flushed; ASR and diarization run asynchronously as post-processing (faster-whisper, chosen model size).
- `completion.json` written at the end of post-processing.
- Transcript files written.
- Minimal menubar state (idle / recording / processing / done).
- Recording-start bell.

**Success criterion:** a real meeting can be recorded from CLI with a hand-written manifest; `stop` returns promptly; the session directory eventually contains audio, transcript, and completion file; no interaction with `briefing` is required.

### Phase 3 — End-of-Meeting UX

- Beep + popup at `T − pre_end_prompt_minutes`.
- Stop / +5 / Next Meeting buttons wired to the `stop` / `extend` / `switch-next` CLI paths.
- Auto-stop and auto-switch per §12.3.
- Runtime state file reflects all transitions.

**Success criterion:** a session is recorded, the popup appears at the right moment, each button path works, a session that is ignored ends correctly, and a back-to-back switch results in the next capture starting within 2 seconds of the current one stopping.

### Phase 4 — `briefing` Integration

- New `transcript` source adapter.
- New `post_meeting_summary.md` prompt template.
- `briefing session-plan` and `briefing session-ingest` subcommands.
- Managed summary block in the Obsidian note, per the §27.4 decision.
- `briefing` trigger mechanism per §27.1 decision.

**Success criterion:** a calendar event flagged for recording results, with no manual intervention, in an Obsidian note containing a summary block. The end-to-end path works for at least one real recorded meeting.

### Phase 5 — Hardening

- `briefing session-reprocess`.
- Crash recovery for `noted`.
- Diagnostics and better error surfacing.
- Diarization quality improvements.
- `online` and `hybrid` mode support, pending the audio-capture decision in §27.8.
- Retention enforcement per the §27.10 decision.

**Success criterion:** ten meetings run unattended over two weeks without developer intervention, and any failures recover via `session-reprocess`.

-----

## 24. Quality Metrics & Success Criteria

### 24.1 Summary Quality (the metric that matters most)

- A small human-rated evaluation set of 8–12 recorded meetings with hand-written reference summaries.
- Each summary rated on three axes: **coverage** (did it capture the important points?), **correctness** (no invented content, no misattributions), and **action-item recall** (did it surface action items that are in the reference?).
- Regression threshold: a prompt or model change must not reduce any axis by more than one rating point on the eval set.

### 24.2 Attribution Accuracy

- On meetings where speaker identity is known, precision and recall of speaker labelling in the summary.
- Target: precision ≥ 0.9 (it is worse to misattribute than to leave unattributed).

### 24.3 End-to-End Latency

- Target: summary available in Obsidian within 5 minutes of meeting end for a one-hour meeting on a current-generation MacBook Pro.

### 24.4 Reliability

- Target: ≥ 95 % of scheduled sessions produce a usable summary or a recoverable state (not a silent failure).
- Target: 100 % of captured audio is retained until purged by retention policy.

### 24.5 Cost (if cloud LLM is used)

- Per-session cost reported in `briefing` logs.
- Target: no runaway — set a per-session cap in LLM settings.

-----

## 25. Testing Strategy

### 25.1 Fixture-Based Integration Tests

Because real meetings are expensive to generate, tests must be driven by pre-recorded fixture sessions: a small collection of reference recordings (self-recorded monologues, role-played meetings, freely licenced podcasts) that exercise mono/stereo, one/two/three speakers, and short/long durations.

Each fixture is a complete session directory (pre-captured) that can be fed into:

- The transcript adapter (skips capture entirely).
- The summariser (tests prompt and note-writing behaviour).

### 25.2 Contract Tests

- Manifest schema: positive and negative examples validated against `noted validate-manifest`.
- CLI exit codes: each failure mode triggered deterministically.
- Completion file shape: produced and consumed by identical schema.

### 25.3 End-to-End Smoke

One real recorded meeting per week, hand-reviewed against its summary. Catches regressions that fixtures miss (especially attribution and prior-context bugs).

### 25.4 Regression Set

The human-rated evaluation set in §24.1 doubles as the summarisation regression harness. Run on every prompt change and every LLM provider swap.

-----

## 26. Locked Vocabulary

### 26.1 Stop Reasons (in `completion.json`)

- `manual_stop`
- `scheduled_stop`
- `auto_switch_to_next_meeting`
- `startup_failure`
- `capture_failure`
- `processing_failure`
- `forced_quit`

### 26.2 Terminal Status

- `completed`
- `completed_with_warnings`
- `failed`

### 26.3 Transcript Output Files

- `transcript.txt` — plain text.
- `transcript.json` — structured segments with timestamps.
- `segments.json` — optional debugging artefact.

### 26.4 Timezone Handling

All timestamps are full ISO-8601 with timezone offsets. Naive local time is never used.

### 26.5 Schema Versioning

Every manifest and every completion file includes `schema_version` as `<major>.<minor>`. The compatibility rule is in §8.4.

-----

## 27. Open Questions & Decisions to Resolve Before Implementation

**These must be resolved before Phase 1 closes.** Each carries a recommendation, but the decision is the team’s.

### 27.0 At-a-Glance Dependency Map

|Open question                               |Blocks phase|
|--------------------------------------------|------------|
|§27.1 `briefing` lifecycle model            |4           |
|§27.2 `noted config` marker vs series gate  |4           |
|§27.3 New subcommand naming                 |4           |
|§27.4 Summary block placement               |4           |
|§27.5 Partial-context policy                |4           |
|§27.6 Completion handoff mechanism          |4           |
|§27.7 `no_interaction_grace_minutes` default|3           |
|§27.8 macOS system-audio capture mechanism  |5           |
|§27.9 Diarization library                   |2           |
|§27.10 Retention policy                     |5           |
|§27.11 Audio device selection hint          |2           |
|§27.12 Extension policy beyond one +5       |3           |

**Minimum decisions needed before Phase 2 can begin:** §27.9, §27.11.
**Before Phase 3:** §27.7, §27.12.
**Before Phase 4:** §27.1, §27.2, §27.3, §27.4, §27.5, §27.6.
**Before Phase 5:** §27.8, §27.10.

### 27.1 `briefing` Lifecycle Model

**Context:** `briefing` is currently a batch application run on a `launchd` schedule — it generates pre-meeting briefings and exits. The Meeting Intelligence System expects `briefing` to also react to upcoming meetings (to plan manifests, invoke `noted start` at pre-roll time, and keep pre-prepared next-meeting manifests current per §13.3) and to ingest completed sessions (§27.6). That’s a lifecycle shift.

**Options:**

- **(a) Tight launchd schedule** — fire `briefing run` every 60 seconds. It checks whether any event is starting now or any session needs ingesting. Simplest, reuses current shape.
- **(b) Long-running daemon** — `briefing` becomes an agent. Bigger rewrite, more precise timing.
- **(c) Split commands** — keep `briefing run` as today; add `briefing watch` as a second, longer-running command installed under launchd. Keeps the existing batch behaviour unchanged, adds reactive capability cleanly.

**Recommendation:** **(c)**. Preserves all existing behaviour, confines new complexity to a new command, easy to roll back.

**Blocks:** Phase 4.

**Decision:** (c) as recommended.

### 27.2 `noted config` Marker vs Series Config as the Trigger

**Context:** Existing `briefing` only processes events that match a configured series YAML. The plan introduces a `noted config` marker in event notes as a per-event signal. These are two independent gates, and the semantics need aligning. This also determines whether a user can mark a **one-off** calendar event for automated recording without creating a series.

**Options:**

- **(a) Both required** — event must match a series *and* carry `noted config`. Most conservative; recording is opt-in twice. One-off events cannot enter the automated path.
- **(b) Either sufficient** — any event with `noted config` triggers the workflow, regardless of series. Ad hoc unconfigured meetings are recordable. Risk: accidentally recording any meeting with the marker.
- **(c) Series required, `noted config` is per-instance override** — series YAML gates the meeting; `record: true` or `noted config` in the event notes controls this specific instance. Consistent with `briefing`’s existing opt-in model. One-off events cannot enter the automated path — the user falls back to manual ad hoc recording from the menubar.
- **(d) Series OR explicit marker** — an event enters the automated path if it matches a series *or* carries an explicit `noted config` marker. One-off events can be marked directly in the calendar without creating a series YAML. More flexible; slightly larger blast radius if a marker is added by mistake.

**Recommendation:** **(c)** if the product stance is that recording is always series-level (series YAML is the contract between user and system). **(d)** if the product stance is that the calendar is the source of intent and one-off events are a valid first-class case. Pick one deliberately — this is a product decision, not a technical one.

**If (c) is chosen,** document plainly that one-off events use the manual ad hoc path (§20.1) and this is intentional.

**If (d) is chosen,** document that `briefing` treats `noted config` without a matching series as an implicit ad-hoc-style session, gets its defaults from settings, and writes the note to a configurable default directory.

**Blocks:** §7.5, §18.2, Phase 4.

**Decision:** (d) — the calendar is the source of intent. An event enters the automated path if it matches a configured series *or* carries an explicit `noted config` marker.

**Precedence for series-matched events** (also codified in §7.3): the series YAML supplies all metadata by default. Calendar-note values under a `noted config` marker override series YAML values field-by-field. This means:

- A recurring meeting the user intends to record should have `record: true` set **in its series YAML**, not in every calendar event. Calendar notes are for per-instance overrides only.
- A single instance of a series can be skipped by adding `noted config` + `record: false` to that event’s notes.
- A single instance can use different settings (different `mode`, different `speaker_count_hint`, etc.) by adding those fields under `noted config` in that event’s notes.
- A one-off event not matching any series requires the `noted config` marker to be recorded at all; `briefing` uses global defaults for any fields not specified in the notes.

### 27.3 Naming for New `briefing` Subcommands

**Context:** New commands are needed for session planning, ingestion, and reprocessing. Existing style: `briefing run | validate | init-series`.

**Options:**

- **(a)** `briefing session-plan`, `briefing session-ingest`, `briefing session-reprocess`.
- **(b)** `briefing meet-start`, `briefing meet-end`, `briefing meet-reprocess`.
- **(c)** Sub-namespaced: `briefing session plan`, `briefing session ingest`, etc.

**Recommendation:** **(a)**. Hyphenated sibling commands match the existing `init-series` pattern; no sub-command parser gymnastics required.

**Blocks:** §18.2, Phase 4.

**Decision:** (a) as recommended.

### 27.4 Placement of the Summary Block in the Obsidian Note

**Context:** Existing notes have a managed `## Briefing` block, then `## Meeting Notes` onward as user-owned content that is preserved and carried forward as prior context. Where does the post-meeting summary go?

**Options:**

- **(a) New `## Summary` block between `## Briefing` and `## Meeting Notes`** — pre-briefing up top, then summary, then user notes. Read top-to-bottom reflects the meeting lifecycle.
- **(b) New `## Summary` block appended after the user’s `## Meeting Notes` section** — user notes remain the first thing read; summary is additive.
- **(c) A separate file** — e.g., `2026-04-18 Jayde 4-5pm (summary).md` — avoids touching the existing note at all.

**Recommendation:** **(a)**. It preserves the one-note-per-meeting model, puts machine-generated content in a predictable location, and keeps the user’s notes as the final, owned section. Downstream carry-forward behaviour is unchanged because only content from `## Meeting Notes` onward feeds prior-context lookups.

**Blocks:** §17.2, Phase 4.

**Decision:** (b) the user may take their own meeting notes. The automated summary from the transcript is processed and added after the meeting and so should be copied to the end of the note.

### 27.5 Partial-Context Policy Alignment

**Context:** Existing `briefing` policy is strict: *“If a required source fails, that meeting’s briefing is skipped rather than generated with incomplete context.”* The addendum is lenient for the post-meeting case: *“Capture succeeded, transcript failed → briefing may write a placeholder note.”* These conflict.

**Options:**

- **(a) Strict everywhere** — fail-skip on both pre- and post-meeting. Consistent but loses the summary of a real recorded meeting if transcription blips.
- **(b) Lenient for post-meeting only** — acknowledges that capture is non-repeatable while briefings can simply run again tomorrow. Writes a placeholder with transcript pointer.
- **(c) Lenient everywhere** — always degrade, always emit.

**Recommendation:** **(b)**. Different stakes justify different policies. Pre-meeting briefings are rerunnable; a failed recording is not.

**Blocks:** §19, Phase 4.

**Decision:** (b) as recommended.

### 27.6 Completion Ingestion Handoff Mechanism

**Context:** Session launching is now locked (§13.2): `briefing` writes manifests in advance; `noted start --manifest <path>` is the single launch entry point, invoked by `briefing watch` for calendar meetings, by `noted` itself for ad hoc, and by `noted switch-next` for back-to-back. That is settled. What remains open is a different handoff: after post-processing completes and `completion.json` is written, how does `briefing session-ingest` get triggered to write the summary into the Obsidian note?

**Options:**

- **(a) `noted` invokes `briefing session-ingest <session-dir>` when post-processing finishes.** Simple; clear causality; works even if launchd is idle.
- **(b) `briefing watch` polls the sessions directory** and picks up any new `completion.json`.
- **(c) A launchd `WatchPaths` agent** triggers `briefing session-ingest` on completion-file appearance.

**Recommendation:** **(a)**. Easiest to reason about, easiest to test. (b) adds latency; (c) adds a launchd file that’s easy to forget about.

**Blocks:** §18.2, Phase 4.

**Decision:** (a) as recommended.

### 27.7 `no_interaction_grace_minutes` Default

**Context:** If a meeting has a next meeting queued and the user ignores the popup, how long does `noted` wait past `scheduled_end_time` before auto-switching?

**Options:**

- **(a)** Same as `default_extension_minutes` (5 min) — one knob, consistent.
- **(b)** Shorter (e.g., 2 min) — faster handoff, less overrun.
- **(c)** Longer (e.g., 10 min) — more forgiving.

**Recommendation:** **(a) = 5 min.** Simpler mental model for the user.

**Blocks:** §8.2 schema, §12.3 behaviour.

**Decision:** (a) as recommended.

### 27.8 macOS System-Audio Capture Mechanism (for `online` mode)

**Context:** Capturing system audio on macOS without third-party kexts is platform-specific and has moved recently.

**Options:**

- **(a) CoreAudio Tap API** (macOS 14.4+). Native, first-class, no extra install, requires screen-recording permission.
- **(b) ScreenCaptureKit audio taps**. Native, well-tested, also requires screen-recording permission.
- **(c) Third-party virtual audio device** (BlackHole, Loopback). Requires user install; works back to older macOS.

**Recommendation:** **(a)** with fallback to **(b)**. Setting a minimum macOS version of 14.4 is reasonable on modern hardware; document the fallback path for older systems or defer `online` mode.

**Blocks:** Phase 5 (`online` support).

**Decision:** **(a)** with fallback to **(b)** as recommended.

### 27.9 Diarization Library

**Context:** In-person diarization quality is the primary technical risk. Library choice affects quality, install complexity, and licence.

**Options:**

- **(a) `pyannote.audio`** — strong quality, requires Hugging Face token for some pipelines, heavier.
- **(b) `whisperx`** — wraps `faster-whisper` with diarization; lighter integration.
- **(c) `sherpa-onnx` speaker-id pipelines** — lighter-weight, less accurate.

**Recommendation:** **(b)** for v1 — it’s the tightest match to the chosen ASR backend. Re-evaluate after the first real dataset is in hand.

**Blocks:** Phase 2.

**Decision:** (b) as recommended.

### 27.10 Raw-Audio Retention Policy

**Context:** “Retain whenever possible” is stated but unbounded. Raw WAV at 48 kHz mono is roughly 330 MB/hour; 10 meetings/week is ~15 GB/month. There must be a retention rule.

**Options:**

- **(a) Rolling window** — keep raw audio for N days (e.g., 30), then delete, retaining only transcript and summary.
- **(b) Size cap** — retain until the sessions directory exceeds a configured size, then prune oldest first.
- **(c) Manual** — never auto-delete; user prunes.
- **(d) Compress to FLAC** — reduces size by ~50 % without loss; combine with (a) or (b).

**Recommendation:** **(a) + (d)**. Keep 30 days, store as FLAC. Balances recovery value with privacy hygiene and disk usage.

**Blocks:** §22.5, Phase 5.

**Decision:** **(a) + (d)** as recommended.

### 27.11 Audio Device Selection Hint for `in_person`

**Context:** A MacBook Pro may have several connected inputs (built-in mic, AirPods, USB interface, conference room mic). There is no signal in the manifest for which one to use.

**Options:**

- **(a) `noted` settings hold a default device**; manifest does not override. Simplest.
- **(b) Per-series device hint in `briefing` series YAML**, passed into the manifest. More flexible (office mic for office 1:1, AirPods for travel).
- **(c) Prompt the user at start** if multiple candidates exist. Breaks the unattended flow.

**Recommendation:** **(a)** for v1. Add **(b)** later if users ask for it.

**Blocks:** Phase 2.

**Decision:** (a) as recommended.

### 27.12 Extension Policy — Beyond One +5

**Context:** §12.4 locks v1 to a single `+5 minutes` action. Long meetings with one legitimate overrun aren’t well served.

**Options:**

- **(a)** Single +5 only (current v1 rule).
- **(b)** Allow up to N extensions (e.g., N=3), re-prompt at each extension deadline.
- **(c)** After the first +5, show a simpler notification with a single “Still going” option that grants another 5 min.

**Recommendation:** Ship **(a)** in v1; revisit after two weeks of real usage.

**Blocks:** Phase 3.

**Decision:** (c) let the user keep extending if they want.

-----

## 28. Glossary

- **`briefing`** — the orchestration application; existing Python codebase.
- **`noted`** — the menubar capture agent; forked from HushScribe.
- **Series** — a configured recurring or named meeting type in `briefing`’s `user_config/series/`.
- **Session** — a single recording instance corresponding to one meeting.
- **Manifest** — the JSON file that carries all per-session intent from `briefing` to `noted`.
- **Completion file** — `completion.json`, the machine-readable final state of a session.
- **Managed block** — a delimited region of a Markdown note that `briefing` owns and rewrites; user content outside it is preserved.
- **Ad hoc session** — a session started manually from the menubar without a `briefing`-generated manifest.
- **Attribution** — naming speakers in the summary text.
- **Source adapter** — `briefing`’s existing pluggable interface for supplying context to an LLM prompt (`previous_note`, `slack`, `notion`, `file`; proposed new `transcript`).
- **`noted config` marker** — a plain-text marker (and optional metadata block) in a calendar event’s notes that opts a one-off event into the recording workflow and/or overrides series-YAML defaults on a per-instance basis. See §7.
- **Metadata precedence** — the order in which `briefing` resolves a manifest field for a series-matched event: calendar-note value > series YAML default > `briefing` global default > hard-coded default. See §7.3.

-----

## 29. References

- `briefing` repository — https://github.com/darrencroton/briefing
- HushScribe repository — https://github.com/drcursor/HushScribe
- Apple EventKit documentation.
- `faster-whisper` — https://github.com/SYSTRAN/faster-whisper
- Surveillance Devices Act 1999 (Vic) — relevant for consent posture in §22.

-----

## Canonical Architecture Statement

> `briefing` remains the only orchestration brain in the system.
> `noted` is the menubar capture agent and runtime control surface.
> `noted` does not own calendar interpretation, workflow policy, summarisation, or note writing.