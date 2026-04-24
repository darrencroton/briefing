# `briefing session-ingest` Smoke Handoff (B-21)

This runbook captures the procedure for verifying `briefing session-ingest`
against a real `noted` session directory. It is the cross-repo Step 7 smoke
that completes ticket B-21. The dedicated smoke script (B-24) will automate
most of this.

## Current Status

- Status: blocked, not complete.
- Last attempt: 2026-04-24 using the sibling repo build at
  `/Users/dcroton/Local/git-repos/dev/noted/HushScribe/.build/arm64-apple-macosx/debug/Noted`.
- Scratch root: `/tmp/briefing-noted-smoke-codex`.
- Result: `noted validate-manifest --manifest /tmp/briefing-noted-smoke-codex/manifest.json`
  passed, but `noted start --manifest /tmp/briefing-noted-smoke-codex/manifest.json`
  did not return within the bounded startup window. The session status remained
  `starting` / `acquiring_audio_resources`, no `outputs/completion.json` was
  produced, and `noted stop --session-id 2026-04-24T153000+1000-codex-smoke`
  reported `session_not_running`.
- No `Noted` process was left running after the attempt.

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

- Full `briefing watch` invalidation polish (Phase 4 planning side).
- `session-reprocess` (Phase 5).
- Retention enforcement (Phase 5).
