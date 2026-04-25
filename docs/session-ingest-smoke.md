# Meeting Intelligence Smoke Handoff (B-21/B-24)

This runbook captures the procedure for verifying `briefing session-ingest`
against a real `noted` session directory. The original manual run completed
B-21; `scripts/meeting-intelligence-smoke.sh` is the repeatable B-24 harness.

## Current Status

- Status: **complete** — B-21 signed off 2026-04-24.
- Session: `2026-04-24T171800+1000-slice-test`, scratch root `/tmp/noted-slice`.
- Result: full chain passed — `noted start` (EXIT:0), `noted stop` (EXIT:0, audio_finalised), `completion.json` (terminal_status=completed, all *_ok=true), `briefing session-ingest` (EXIT:0, block_written=true). Guardrail #12 verified. No contract-level bugs found.
- Earlier attempt (also 2026-04-24) blocked because the debug binary lacked bundle context for `app.noted.macos`; TCC's `requestAccess` blocked indefinitely. Resolution: use the dist app bundle and approve the mic permission dialog once after signing.
- Full findings: see `docs/step-7-report.md` in the root repo.

## Automated smoke script

Run from the `briefing` repo root:

```sh
scripts/meeting-intelligence-smoke.sh
```

Useful environment overrides:

- `NOTED_CMD=/path/to/Noted`
- `BRIEFING_SMOKE_ROOT=/tmp/meeting-intelligence-smoke`
- `CAPTURE_SECONDS=30`
- `WAIT_SECONDS=180`

The script adapts the shared valid manifest fixture, starts and stops `noted`,
waits for `outputs/completion.json`, runs `session-ingest --dry-run`, then runs
the real note write.

## Prerequisites

- `noted` Phase 2 built and available on `$PATH`.
- `briefing` configured (`./scripts/setup.sh`) and `briefing validate` green.
- A pre-written manifest in v1.x that points `paths.note_path` at a scratch
  Obsidian note path. The shared fixture `vendor/contracts/contracts/fixtures/manifests/valid-inperson.json`
  can be adapted — edit `paths.*` to local absolute paths.

## Procedure

1. Start a short session (1–2 minutes) against the manifest:
   ```sh
   noted start --manifest /tmp/smoke/manifest.json
   ```
2. Let `noted` capture, then stop it:
   ```sh
   noted stop --session-id <session_id>
   ```
3. Wait for post-processing to finish; `outputs/completion.json` only appears
   once `noted` has written ASR, diarization, and the completion payload.
4. Ingest through `briefing`:
   ```sh
   uv run briefing session-ingest --session-dir /tmp/smoke/sessions/<session_id>
   ```

## Expected artefacts

- `outputs/completion.json` validates against `contracts/schemas/completion.v1.json`.
- `logs/briefing.log` contains a line-by-line trace of completion read, ingest
  decision, transcript load, LLM call, and note write.
- The target note at `manifest.paths.note_path` contains a `## Meeting Summary`
  block wrapped in
  `<!-- MEETING-SUMMARY:start session_id="…" transcript_sha256="…" -->` /
  `<!-- MEETING-SUMMARY:end -->` markers.
- Re-running `session-ingest` against the same directory replaces only the
  managed block; user content outside the markers is byte-identical.

## Exit-code contract

`session-ingest` emits a single-line JSON result on stdout and exits with:

| code | meaning |
| ---- | ------- |
| 0    | summary written, replaced, or recoverable no-op logged |
| 1    | unexpected/unclassified error |
| 2    | `outputs/completion.json` missing |
| 3    | completion invalid or unsupported `schema_version` |
| 4    | manifest missing, invalid, or unsupported `schema_version` |
| 5    | note structure error (cannot reconcile safely) |
| 6    | transcript or LLM failure |
| 7    | note I/O failure |

## Out of scope

- `session-reprocess` (Phase 5).
- Retention enforcement (Phase 5).
