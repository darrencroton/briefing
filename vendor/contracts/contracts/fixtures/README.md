# fixtures/

Canonical examples for consumer tests. These files are examples, not the
specification: the JSON Schemas in `contracts/schemas/` remain authoritative.
If a fixture disagrees with a schema, fix the fixture.

## Manifest Fixtures

| File | Purpose |
| --- | --- |
| `manifests/valid-inperson.json` | Fully populated calendar-driven in-person manifest. Use this for happy-path manifest parsing and writer round-trip tests. |
| `manifests/valid-adhoc.json` | Canonical ad hoc manifest. `meeting.event_id` and `meeting.scheduled_end_time` are `null`, which are the permitted ad hoc null slots in v1. |
| `manifests/valid-with-next-meeting.json` | Calendar-driven online manifest with `next_meeting.exists: true` and a populated `manifest_path`, for `switch-next` and pre-prepared next-manifest tests. |
| `manifests/invalid-missing-required.json` | Negative manifest fixture with the required top-level `schema_version` field omitted. Use this to catch validators or writers that forget the version field. |
| `manifests/invalid-bad-timezone.json` | Negative manifest fixture with naive `created_at` and `meeting.start_time` values. Use this to enforce the explicit-offset timestamp guardrail. |
| `manifests/invalid-naive-scheduled-end-time.json` | Negative manifest fixture with only `meeting.scheduled_end_time` written as a naive timestamp. Use this to catch regressions in calendar-driven end-time handling. |

## Completion Fixtures

| File | Purpose |
| --- | --- |
| `completions/completed.json` | Happy path: capture, transcript, and diarization all succeeded. |
| `completions/completed-with-warnings.json` | Non-fatal diarization failure: transcript is usable, diarization is not. |
| `completions/failed-startup.json` | Startup failure before capture begins. No usable raw audio is expected. |
| `completions/failed-capture.json` | Mid-session capture failure after capture started. `audio_capture_ok` remains true to preserve partial raw audio for reprocessing. |

## Audio Fixtures

| File | Purpose |
| --- | --- |
| `audio/smoke-30s.wav` | Generated 30-second mono WAV for capture-replacement and file-handling smoke tests. It is synthetic tone/silence, not real meeting audio. |

Fixtures should be named for the contract behavior they exercise. Additions under
this directory do not require a version bump as long as they satisfy the current
schemas. Changes that alter fixture semantics warrant a patch bump; see
`versioning-policy.md`.
