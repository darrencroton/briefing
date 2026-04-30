# Locked Vocabulary (v1.0)

**Authoritative source:** Master Plan §26. Every string in these lists is part of the contract. Readers must treat unknown values as errors; writers must use only the values listed here.

Because readers reject unknown values by design, **any change to any list below — adding, removing, or renaming — is a major version bump.** See `versioning-policy.md`.

## Stop reasons (in `completion.json`)

- `manual_stop`
- `scheduled_stop`
- `auto_switch_to_next_meeting`
- `startup_failure`
- `capture_failure`
- `processing_failure`
- `forced_quit`

Stop-reason → terminal-status mapping is in `session-directory.md`.

## Terminal statuses (in `completion.json`)

- `completed`
- `completed_with_warnings`
- `failed`

## Runtime statuses (in `runtime/status.json`)

Top-level session state (§10.1):

- `idle`
- `starting`
- `recording`
- `stopping`
- `processing`
- `completed`
- `completed_with_warnings`
- `failed`

Pause state is not a runtime status. During a pause the session remains `recording` and `runtime/status.json` carries `is_paused: true`.

## Runtime phases (in `runtime/status.json`)

Finer-grained indicator within `recording`, `stopping`, or `processing` (§10.2):

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

## Mode types (in manifest)

- `in_person`
- `online`
- `hybrid`

## Audio strategies (in manifest)

- `room_mic`
- `mic_plus_system`

## ASR backends (in manifest)

Locked for v1 per §15.2 and §27.9. Python backends (`faster-whisper`, `whisperx`) are **not** part of `noted` and are not valid values.

- `whisperkit` *(default)*
- `fluidaudio-parakeet`
- `sfspeech`

## Transcript output filenames

Locked (§26.3):

- `transcript.txt` — plain text.
- `transcript.json` — structured segments with timestamps.
- `segments.json` — optional debugging artefact.

## Timezone handling

All timestamps in every contract file are ISO-8601 with explicit timezone offsets. Naive local time is never used (§26.4, guardrail 5). `Z` is a valid UTC offset.

## Schema versioning

Every manifest and every completion file includes `schema_version` as `<major>.<minor>`. The runtime-status file carries its version in its filename (`runtime-status.v1.json`) to match the master-plan example at §10.3.

Compatibility rule (§8.4):

- Major match required.
- Forward-tolerate minor (unknown fields ignored).
- Backward-strict minor (missing required fields fail).
- Unknown major → validation error, exit 2.
