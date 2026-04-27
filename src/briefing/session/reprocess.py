"""Session-reprocess: re-run summary generation from an existing transcript.

Unlike session-ingest, reprocess does not require completion.json to be present
or in a summarisable state.  It is intended for recovery after a transcript
exists but ingest was skipped or the LLM call failed.

Exit codes follow the same stable set as session-ingest so that callers can
handle them consistently:

| code | meaning |
| ---- | ------- |
| 0    | success (summary written or replaced) |
| 1    | unexpected error |
| 4    | manifest missing, invalid, or unsupported version |
| 5    | note structure error |
| 6    | transcript missing/empty or LLM failure |
| 7    | note I/O failure |
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from ..llm import get_provider
from ..notes import NoteStructureError
from ..settings import AppSettings
from .completion import Completion, read_completion
from .ingest import (
    IngestResult,
    attach_session_log_handler,
    error_result,
    missing_note_template,
)
from .loader import LoadedSession, SessionLoadError, load_session
from .note_summary import write_summary_block
from .prompt import PromptInputs
from .summary import SummaryGenerationError, generate_summary
from .transcript import TranscriptError, load_transcript


LOGGER = logging.getLogger("briefing.session.reprocess")


def run_session_reprocess(
    settings: AppSettings,
    session_dir: Path,
    *,
    provider=None,
    dry_run: bool = False,
) -> IngestResult:
    """Rerun summary generation from an existing transcript."""
    session_dir = session_dir.resolve()
    session_handler = None
    session_log_path = session_dir / "logs" / "briefing.log"
    try:
        session_handler = attach_session_log_handler(session_log_path)
    except OSError as exc:  # pragma: no cover - rare, captured as warning
        LOGGER.warning("Could not attach session log handler (%s): %s", session_log_path, exc)
    try:
        return _reprocess(settings, session_dir, provider=provider, dry_run=dry_run)
    finally:
        if session_handler is not None:
            logging.getLogger().removeHandler(session_handler)
            session_handler.close()


def _reprocess(
    settings: AppSettings,
    session_dir: Path,
    *,
    provider=None,
    dry_run: bool = False,
) -> IngestResult:
    LOGGER.info("Starting session reprocess for %s dry_run=%s", session_dir, dry_run)

    # Load manifest - required.
    try:
        loaded = load_session(session_dir, completion=None)
    except SessionLoadError as exc:
        LOGGER.error("Session load failed: %s", exc)
        return error_result(session_dir, exc.exit_code, str(exc), dry_run=dry_run)

    # Load completion if present - used for richer prompt context when available.
    completion: Completion | None = None
    completion_path = session_dir / "outputs" / "completion.json"
    if completion_path.exists():
        try:
            completion = read_completion(session_dir)
        except Exception as exc:
            LOGGER.info("completion.json exists but could not be parsed (%s); using synthetic context", exc)

    # Load transcript - required.
    try:
        transcript = load_transcript(loaded.transcript_text_path)
    except TranscriptError as exc:
        LOGGER.error("Transcript load failed: %s", exc)
        return error_result(
            session_dir,
            exc.exit_code,
            str(exc),
            session_id=loaded.manifest.session_id,
            note_path=str(loaded.note_path),
            dry_run=dry_run,
        )

    effective_completion = completion or _synthetic_completion(loaded, session_dir)

    # LLM call.
    active_provider = provider if provider is not None else get_provider(settings)
    try:
        summary = generate_summary(
            settings,
            active_provider,
            PromptInputs(
                manifest=loaded.manifest,
                completion=effective_completion,
                transcript=transcript,
            ),
            debug_key=f"{loaded.manifest.session_id}-reprocess",
        )
    except SummaryGenerationError as exc:
        LOGGER.error("Summary generation failed: %s", exc)
        return error_result(
            session_dir,
            exc.exit_code,
            str(exc),
            session_id=loaded.manifest.session_id,
            note_path=str(loaded.note_path),
            dry_run=dry_run,
        )

    if dry_run:
        LOGGER.info("Dry-run reprocess: skipping note write for session_id=%s", loaded.manifest.session_id)
        return IngestResult(
            ok=True,
            exit_code=0,
            session_id=loaded.manifest.session_id,
            session_dir=str(session_dir),
            decision="reprocess",
            note_path=str(loaded.note_path),
            note_created=False,
            block_written=False,
            block_replaced=False,
            terminal_status=effective_completion.terminal_status,
            stop_reason=effective_completion.stop_reason,
            dry_run=True,
        )

    try:
        write_result = write_summary_block(
            loaded.note_path,
            loaded.manifest,
            summary.text,
            session_id=loaded.manifest.session_id,
            transcript_sha256=transcript.sha256,
            missing_note_template=missing_note_template(settings)
            if not loaded.note_path.exists()
            else None,
        )
    except NoteStructureError as exc:
        LOGGER.error("Note structure error: %s", exc)
        return error_result(
            session_dir,
            5,
            str(exc),
            session_id=loaded.manifest.session_id,
            note_path=str(loaded.note_path),
            dry_run=dry_run,
        )
    except OSError as exc:
        LOGGER.error("Note write failed: %s", exc)
        return error_result(
            session_dir,
            7,
            f"Failed to write note: {exc}",
            session_id=loaded.manifest.session_id,
            note_path=str(loaded.note_path),
            dry_run=dry_run,
        )

    LOGGER.info(
        "Reprocess note write: path=%s created=%s replaced=%s written=%s",
        write_result.note_path,
        write_result.note_created,
        write_result.block_replaced,
        write_result.block_written,
    )
    return IngestResult(
        ok=True,
        exit_code=0,
        session_id=loaded.manifest.session_id,
        session_dir=str(session_dir),
        decision="reprocess",
        note_path=str(write_result.note_path),
        note_created=write_result.note_created,
        block_written=write_result.block_written,
        block_replaced=write_result.block_replaced,
        terminal_status=effective_completion.terminal_status,
        stop_reason=effective_completion.stop_reason,
        dry_run=dry_run,
    )


def _synthetic_completion(loaded: LoadedSession, session_dir: Path) -> Completion:
    """Build a minimal synthetic completion when completion.json is absent or unreadable."""
    audio_dir = session_dir / "audio"
    audio_ok = next((True for _ in audio_dir.glob("*.wav")), False) if audio_dir.exists() else False
    diarization_ok = (session_dir / "diarization" / "diarization.json").exists()
    return Completion(
        schema_version="1.0",
        session_id=loaded.manifest.session_id,
        manifest_schema_version=loaded.manifest.schema_version,
        terminal_status="completed_with_warnings",
        stop_reason="manual_stop",
        audio_capture_ok=audio_ok,
        transcript_ok=True,
        diarization_ok=diarization_ok,
        warnings=("reprocessed_without_completion",),
        errors=(),
        completed_at=datetime.now(timezone.utc).astimezone().isoformat(),
        raw={},
    )
