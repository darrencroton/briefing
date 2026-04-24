# briefing Extension Plan

This plan turns the Meeting Intelligence System master plan into `briefing` engineering tickets. It focuses on master-plan Phase 4 plus the required additions from section 18.2. Phase 5 items are included only at broad stroke where they affect interfaces.

Authoritative inputs:

- `../vendor/contracts/CONTRACTS_TAG` pinned to `v1.0.1`
- `../vendor/contracts/contracts/schemas/manifest.v1.json`
- `../vendor/contracts/contracts/schemas/completion.v1.json`
- `../vendor/contracts/contracts/session-directory.md`
- `../vendor/contracts/contracts/cli-contract.md`
- Existing CLI: `briefing run`, `briefing validate`, `briefing init-series`
- Existing source adapter package: `src/briefing/sources/`
- Existing note writer: `src/briefing/notes.py`

## Contracts Consumption

This plan assumes the current copied-snapshot mechanism: `vendor/contracts/CONTRACTS_TAG` records the pinned release tag and `vendor/contracts/contracts/` contains the checked-in contract snapshot. Confirm this with the dev team before cutting tickets. If the team switches to a submodule or fetch-at-test-time mechanism, update the paths in this plan first so issues do not cite stale locations.

## Scope Boundaries

`briefing` owns calendar interpretation, event eligibility, manifest contents, next-meeting lookahead, LLM summarisation, and Obsidian note writes.

`briefing` must not own capture state. It invokes `noted start --manifest <path>` at pre-roll time and later ingests `completion.json`; it does not infer outcomes from file presence or logs.

## Cross-Repo Dependency Map

| System phase | noted work | briefing work | Blocks / blocked by |
| --- | --- | --- | --- |
| Phase 2: Minimal `noted` Runtime | CLI, manifest validation, session directory writer, in-person capture, fast stop, async post-processing, completion file | Contract-aware tests can be built from fixtures; no runtime dependency yet | Blocks real recorded-session ingestion; does not block fixture-based `session-ingest` development |
| Phase 3: End-of-Meeting UX | Popup, `extend`, `switch-next`, auto-stop, auto-switch, UI state persistence | `session-plan` must pre-write next manifests for realistic switch testing | Depends on `briefing session-plan` for full next-meeting scenarios |
| Phase 4: `briefing` Integration | Completion handoff invokes `briefing session-ingest`; switch-next consumes pre-prepared manifests | `session-plan`, `session-ingest`, `watch`, transcript adapter, summary block writer | Depends on noted Phase 2 for real recordings; first vertical slice can start with shared fixtures |
| Phase 5: Hardening | Crash recovery, diagnostics, online/hybrid capture, retention hooks | `session-reprocess`, retention policy, operator diagnostics | Depends on real Phase 4 usage data; plan only at broad stroke now |

## Estimates

Estimates are days of focused work, not elapsed calendar time. They include implementation and local tests, but not review wait time or exploratory product review.

## Phase 4 - Session Planning and Watch

Goal: `briefing` detects eligible calendar events, writes contract-valid manifests at pre-roll time, invokes `noted start --manifest`, and keeps pre-prepared next-meeting manifests current while a meeting is in progress.

### Acceptance Criteria

- Event eligibility follows master-plan section 27.2 decision: a meeting enters the automated recording path if it matches a configured series or carries an explicit `noted config` marker. For series-matched events, calendar-note values override series YAML field by field.
- `briefing session-plan --event-id <id>` writes a schema-valid `manifest.json` for one event and, when eligible, pre-writes the next meeting manifest and populates `next_meeting`.
- All manifest timestamps are ISO-8601 with explicit offsets; naive datetimes are rejected in tests.
- `speaker_count_hint` is derived at manifest assembly time from explicit config, `participants.attendees_expected`, or participant-name count.
- `briefing watch` runs as the long-running command chosen in master-plan section 27.1, starts `noted` at the pre-roll target, and logs command, args, exit code, and session directory.
- `briefing watch` invalidates pre-prepared next manifests on cancellation or out-of-tolerance reschedule and rewrites them on in-tolerance reschedule.
- No `briefing session-start` wrapper is added.

### Tickets

| Ticket | Title | Estimate | Dependencies | Acceptance notes |
| --- | --- | ---: | --- | --- |
| B-01 | Add Meeting Intelligence settings | 2 days | Current settings loader | Adds sessions root, noted command path, pre-roll default 90 seconds with configurable 60-180 second bounds, default host/language/asr/backend policy, and one-off note defaults. One-off `noted config` events default to `paths.meeting_notes_dir` unless a new setting overrides it |
| B-02 | Extend series YAML model for recording metadata | 3 days | B-01 | Adds record flag, mode, participants, transcription, recording policy, and optional per-series defaults without breaking existing series |
| B-03 | Parse `noted config` event notes | 3 days | B-02 | Case-insensitive marker; supports field-level overrides and `record: false`; tests series override and one-off marker paths |
| B-04 | Implement event eligibility resolver | 2 days | B-03 | Encodes section 27.2 decision; returns skip reasons suitable for logs and diagnostics |
| B-05 | Build manifest assembly module | 5 days | B-01 through B-04 | Produces `manifest.v1.json` shape; derives session id, note path, participants, policy, and speaker hints |
| B-06 | Add manifest schema validation tests | 2 days | B-05 | Validates generated manifests against pinned contracts and rejects naive timestamps |
| B-07 | Implement next-meeting lookahead and pre-write | 4 days | B-05 | Writes next manifest in advance and populates current `next_meeting.manifest_path`; no runtime query by `noted` needed |
| B-08 | Add `briefing session-plan` CLI | 3 days | B-05, B-07 | Supports `--event-id`; prints machine-readable result with manifest path and skip reason |
| B-09 | Implement `briefing watch` scheduling loop | 5 days | B-08 | Starts `noted` at pre-roll; respects one active launch per event; persists state for restarts |
| B-10 | Implement manifest invalidation sweep | 4 days | B-07, B-09 | Deletes or rewrites pre-prepared manifests when calendar state changes; logs all decisions |
| B-11 | Add launchd support for `briefing watch` | 2 days | B-09 | Installs separately from existing batch `briefing run`; existing launchd flow remains usable |

Phase 4 planning/watch focused estimate: 35 days.

### Open Questions

- What reschedule tolerance should `briefing watch` use when deciding to rewrite versus delete a next manifest?
- Should `briefing watch` persist planned manifest state in the existing `StateStore` or a dedicated session-planning state file?

### Implementation Note

- Product decision: pre-prepared manifests may be updated before they are consumed by `noted` when that is required for the desired UX, including active-meeting `next_meeting` refresh and in-tolerance calendar reschedules. Future contract work should align manifest mutability wording with this behavior rather than treating every planned manifest as immutable from first write.

## Phase 4 - Session Ingestion and Summarisation

Goal: `briefing session-ingest --session-dir <path>` reads `outputs/completion.json` first, consumes completed transcripts, generates a post-meeting summary, and appends a managed summary block after the user's `## Meeting Notes` content.

### Acceptance Criteria

- `session-ingest` always reads `outputs/completion.json` first and rejects missing, invalid, or unknown-major completion payloads without inferring success from transcript files.
- `terminal_status=failed` with `audio_capture_ok=false` produces no summary attempt and a clear log/diagnostic result.
- `terminal_status=completed` or `completed_with_warnings` with `transcript_ok=true` loads the transcript through a new `transcript` source adapter.
- Diarization failure does not block summarisation; the prompt uses speaker-agnostic attribution unless the transcript and hints support high confidence.
- A new post-meeting prompt template is separate from the existing pre-meeting prompt template.
- The generated summary block is headed `## Meeting Summary` and appended after the user's `## Meeting Notes` section, preserving user-owned content byte-identically.
- The summary block is wrapped in managed HTML comments keyed by `session_id` and `transcript_sha256`. Re-ingesting the same session replaces only that managed block; `session-reprocess` can later update the same block without appending duplicates.
- `session-ingest` resolves the target Obsidian note from `manifest.paths.note_path`; missing notes are created under the existing note template rules, and existing notes without `## Meeting Notes` are reconciled before summary insertion or rejected with a structure error.
- `briefing` appends to `logs/briefing.log` inside the session directory during ingestion.
- `noted` can invoke `briefing session-ingest --session-dir <path>` non-interactively after post-processing completes.

### Tickets

| Ticket | Status | Title | Estimate | Dependencies | Acceptance notes |
| --- | --- | --- | ---: | --- | --- |
| B-12 | Completed | Add completion reader and validator | 3 days | Pinned contracts | Reads completion first; validates schema and major version; exposes ingest decisions |
| B-13 | Completed | Add completed-session model and loader | 3 days | B-12 | Resolves manifest, completion, transcript paths, `manifest.paths.note_path`, and briefing log path from one session directory; refuses to infer note path from filenames; validates completion/manifest identity |
| B-14 | Completed | Add transcript source adapter | 3 days | B-13 | Supports `transcript/transcript.txt` first; can read structured JSON later without changing prompt assembly shape |
| B-15 | Completed | Add post-meeting prompt template | 3 days | B-14 | Includes transcript, manifest context, participant hints, attribution policy, and warnings |
| B-16 | Completed | Implement post-meeting summary generator | 3 days | B-15 | Reuses existing LLM provider abstraction; emits debug prompt/output under configured debug paths when enabled |
| B-17 | Completed | Add managed post-meeting summary block writer | 5 days | B-16 | Appends `## Meeting Summary` after `## Meeting Notes`; uses managed comments keyed by session id and transcript hash; preserves existing user text byte-for-byte; creates missing notes through the configured note template |
| B-18 | Completed | Implement partial-context policy | 2 days | B-12, B-17 | Lenient only for post-meeting failures; placeholder/log behavior matches section 27.5 |
| B-19 | Completed | Add `briefing session-ingest` CLI | 3 days | B-12 through B-18 | `--session-dir`; stable exit codes; machine-readable success/failure result for `noted` logs, including invalid session directories |
| B-20 | Completed | Add ingest fixture tests | 4 days | B-19 | Uses shared completion fixtures plus synthetic session dirs; verifies failed startup, failed capture, warning, completed paths, byte-preservation regressions, identity mismatch rejection, and CLI JSON failures |
| B-21 | Completed | Add real noted-session smoke handoff | 3 days | B-19 plus noted Phase 2 | Completed 2026-04-24 as part of Step 7 vertical slice. Hand-written manifest → `noted start` (EXIT:0, recording) → `noted stop` (EXIT:0, audio_finalised) → `completion.json` (terminal_status=completed, all *_ok=true) → `briefing session-ingest` (EXIT:0, block_written=true). Guardrail #12 verified: user-owned `## Meeting Notes` byte-identical after ingest. transcript_sha256 written into managed summary block matches actual transcript. See `docs/step-7-report.md` at the dev root for full findings. Earlier timeout was caused by macOS TCC microphone dialog blocking `requestAccess` in the child process before mic permission was approved; not a contract bug. No contract-level issues found. |

Phase 4 ingestion focused estimate: 32 days.

### Open Questions

- Should `session-ingest` create a placeholder summary block for `completed_with_warnings` sessions where transcript generation failed but raw audio exists, or only log the recoverable state for `session-reprocess`?

## Phase 4 - Integration Polish for First Vertical Slice

Goal: The team can demonstrate one calendar-driven in-person meeting flowing through planning, capture, transcript generation, completion handoff, summarisation, and note update.

### Acceptance Criteria

- A configured event is planned before pre-roll, started through `noted start --manifest`, stopped through `noted stop` or scheduled stop, ingested through `session-ingest`, and written to Obsidian with no manual file edits.
- Logs explain each boundary crossing: event detection, manifest path, `noted` command result, completion ingest, LLM call, note write.
- The vertical slice is repeatable in a test calendar or fixture-driven local harness.
- Failures leave recoverable session directories with raw audio preserved by `noted`.

### Tickets

| Ticket | Title | Estimate | Dependencies | Acceptance notes |
| --- | --- | ---: | --- | --- |
| B-22 | Add cross-boundary diagnostics | 2 days | B-09, B-19 | Stable log fields for event uid, session id, manifest path, noted exit code, completion status |
| B-23 | Add operator dry-run modes | 3 days | B-08, B-19 | Plan without launching; ingest without writing note; useful for review and debugging |
| B-24 | Build first vertical-slice script/runbook | 2 days | B-21, noted Phase 2 | Owns the cross-repo Step 7 smoke script, preferably under `briefing/scripts/`; documents exact commands and expected artefacts |
| B-25 | Update user docs for recording workflow | 3 days | B-11, B-19 | Adds `briefing watch`, `session-plan`, and `session-ingest` usage without disrupting existing pre-meeting docs |

Integration polish focused estimate: 10 days.

## Phase 5 - Hardening

Do not break this into detailed tickets yet. Use real Phase 4 failures to shape it.

Broad work areas:

- `briefing session-reprocess --session-dir <path>` for rerunning summarisation on an existing transcript and, later, on retranscribed raw audio.
- Retention coordination with `noted` once the 30-day raw-audio plus FLAC policy is implemented.
- Better operator diagnostics for failed ingest, missing notes, invalid completion files, stale manifests, and LLM failures.
- Regression set and human-rated summary evaluation.
- Online/hybrid mode support once `noted` ships the capture path.

## Tickets in the First Vertical Slice

The full Phase 4 estimate is not the Step 7 estimate. Step 7 should prove one narrow end-to-end path before the team builds the whole watch and popup surface.

Minimum `briefing` slice:

- B-12 and B-13 to read a completed session directory from `completion.json` first.
- B-14 with `transcript/transcript.txt` support.
- B-15 and B-16 with a first post-meeting prompt path.
- B-17 for the `## Meeting Summary` managed block.
- B-19 for `briefing session-ingest --session-dir <path>`.
- B-20 against synthetic session directories.

If Step 7 must be calendar-driven rather than "record then manually ingest":

- Add B-01 through B-08 for manifest planning.
- Add only the thinnest launch path from B-09; full invalidation sweep B-10 can follow.
- B-24 owns the cross-repo smoke script because `briefing` is the orchestration component.

Explicitly out of the first slice:

- Full `briefing watch` invalidation polish.
- `session-reprocess`.
- Retention enforcement.
- Online/hybrid mode.

## Tickets That Can Start Tomorrow

- B-01 settings extension.
- B-02 series YAML model extension.
- B-03 `noted config` parser.
- B-12 completion reader and validator.
- B-14 transcript source adapter against synthetic session directories.
- B-17 summary block writer tests, after the heading string is chosen.

## Highest-Risk Assumptions

- The existing note refresh logic can append a new managed summary block after user notes while preserving user content byte-for-byte.
- `briefing watch` can be long-running enough for pre-roll and invalidation without destabilizing the existing batch `run` command.
- One-off `noted config` events can be given sensible defaults without forcing users to create series YAML for every recording.
- The first useful transcript summary can reuse the current LLM provider abstraction without a separate provider path.

Cheapest ways to test these:

- Write summary-block preservation tests before integrating LLM calls.
- Implement `session-ingest` against synthetic session directories before waiting for `noted` Phase 2.
- Run `briefing watch` in a dry-run mode against a test calendar to verify pre-roll and invalidation state.

## Review Questions

- Which Phase 4 tickets are too large to become GitHub issues as written?
- Which tickets could start tomorrow without waiting on `noted`?
- Which phase would hurt most if wrong: manifest planning, completion ingestion, or note mutation?
- What assumptions about calendar event notes, one-off defaults, or managed-block preservation could turn out false, and what is the cheapest test?
