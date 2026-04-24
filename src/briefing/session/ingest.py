"""Top-level session-ingest orchestration (B-18, B-19).

Reads the completion file first, applies the partial-context policy from
master plan §27.5, then — when a summary is warranted — loads the transcript,
invokes the LLM, and writes the managed `## Meeting Summary` block.

Exit codes are stable for ``noted`` to consume:

| code | meaning |
| ---- | ------- |
| 0    | success (summary written, replaced, or recoverable no-op logged) |
| 1    | unexpected/unclassified error |
| 2    | completion.json missing |
| 3    | completion.json invalid or unsupported version |
| 4    | manifest missing, invalid, or unsupported version |
| 5    | note structure error (cannot reconcile safely) |
| 6    | transcript or LLM failure |
| 7    | note I/O failure |
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..llm import get_provider
from ..notes import NoteStructureError
from ..settings import AppSettings
from .completion import (
    Completion,
    CompletionError,
    IngestDecision,
    decide,
    decision_should_summarise,
    read_completion,
)
from .loader import LoadedSession, SessionLoadError, load_session
from .note_summary import MissingNoteTemplate, NoteWriteResult, write_summary_block
from .prompt import PromptInputs
from .summary import SummaryGenerationError, generate_summary
from .transcript import Transcript, TranscriptError, load_transcript


LOGGER = logging.getLogger("briefing.session.ingest")


class IngestError(Exception):
    """Raised when ingest cannot complete. Carries a stable exit code."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(slots=True)
class IngestResult:
    """Machine-readable ingest result (serialised to stdout for ``noted``)."""

    ok: bool
    exit_code: int
    session_id: str | None
    session_dir: str
    decision: str | None
    note_path: str | None
    note_created: bool
    block_written: bool
    block_replaced: bool
    terminal_status: str | None
    stop_reason: str | None
    error: str | None = None

    def as_stdout_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "session_id": self.session_id,
            "session_dir": self.session_dir,
            "decision": self.decision,
            "note_path": self.note_path,
            "note_created": self.note_created,
            "block_written": self.block_written,
            "block_replaced": self.block_replaced,
            "terminal_status": self.terminal_status,
            "stop_reason": self.stop_reason,
            "error": self.error,
        }


def run_session_ingest(
    settings: AppSettings,
    session_dir: Path,
    *,
    provider=None,
) -> IngestResult:
    """Run the full session-ingest flow against one session directory."""
    session_dir = session_dir.resolve()
    session_handler: logging.Handler | None = None
    session_log_path = session_dir / "logs" / "briefing.log"
    try:
        session_handler = _attach_session_log_handler(session_log_path)
    except OSError as exc:  # pragma: no cover - rare, captured as warning
        LOGGER.warning("Could not attach session log handler (%s): %s", session_log_path, exc)

    try:
        return _run(settings, session_dir, provider=provider)
    finally:
        if session_handler is not None:
            logging.getLogger().removeHandler(session_handler)
            session_handler.close()


def _run(
    settings: AppSettings,
    session_dir: Path,
    *,
    provider=None,
) -> IngestResult:
    LOGGER.info("Starting session ingest for %s", session_dir)

    # Step 1: completion.json first. Never infer from file presence.
    try:
        completion = read_completion(session_dir)
    except CompletionError as exc:
        LOGGER.error("Completion read failed: %s", exc)
        return _error_result(session_dir, exc.exit_code, str(exc))

    LOGGER.info(
        "Completion loaded: session_id=%s terminal_status=%s stop_reason=%s "
        "audio_capture_ok=%s transcript_ok=%s diarization_ok=%s",
        completion.session_id,
        completion.terminal_status,
        completion.stop_reason,
        completion.audio_capture_ok,
        completion.transcript_ok,
        completion.diarization_ok,
    )

    # Step 2: load manifest.
    try:
        loaded = load_session(session_dir, completion=completion)
    except SessionLoadError as exc:
        LOGGER.error("Session load failed: %s", exc)
        return _error_result(
            session_dir,
            exc.exit_code,
            str(exc),
            session_id=completion.session_id,
            terminal_status=completion.terminal_status,
            stop_reason=completion.stop_reason,
        )

    decision = decide(completion)
    LOGGER.info("Ingest decision: %s", decision.value)

    # Step 3: partial-context policy (B-18). Non-summary decisions exit 0.
    if not decision_should_summarise(decision):
        LOGGER.info(
            "No summary will be generated (%s); raw artefacts preserved for session-reprocess.",
            decision.value,
        )
        return IngestResult(
            ok=True,
            exit_code=0,
            session_id=completion.session_id,
            session_dir=str(session_dir),
            decision=decision.value,
            note_path=str(loaded.note_path),
            note_created=False,
            block_written=False,
            block_replaced=False,
            terminal_status=completion.terminal_status,
            stop_reason=completion.stop_reason,
        )

    # Step 4: transcript.
    try:
        transcript = load_transcript(loaded.transcript_text_path)
    except TranscriptError as exc:
        LOGGER.error("Transcript load failed: %s", exc)
        return _error_result(
            session_dir,
            exc.exit_code,
            str(exc),
            session_id=completion.session_id,
            decision=IngestDecision.TRANSCRIPT_MISSING.value,
            note_path=str(loaded.note_path),
            terminal_status=completion.terminal_status,
            stop_reason=completion.stop_reason,
        )

    # Step 5: LLM call.
    active_provider = provider if provider is not None else get_provider(settings)
    try:
        summary = generate_summary(
            settings,
            active_provider,
            PromptInputs(
                manifest=loaded.manifest,
                completion=completion,
                transcript=transcript,
            ),
            debug_key=completion.session_id,
        )
    except SummaryGenerationError as exc:
        LOGGER.error("Summary generation failed: %s", exc)
        return _error_result(
            session_dir,
            exc.exit_code,
            str(exc),
            session_id=completion.session_id,
            decision=decision.value,
            note_path=str(loaded.note_path),
            terminal_status=completion.terminal_status,
            stop_reason=completion.stop_reason,
        )

    # Step 6: managed summary-block write.
    try:
        write_result = write_summary_block(
            loaded.note_path,
            loaded.manifest,
            summary.text,
            session_id=completion.session_id,
            transcript_sha256=transcript.sha256,
            missing_note_template=_missing_note_template(settings)
            if not loaded.note_path.exists()
            else None,
        )
    except NoteStructureError as exc:
        LOGGER.error("Note structure error: %s", exc)
        return _error_result(
            session_dir,
            5,
            str(exc),
            session_id=completion.session_id,
            decision=decision.value,
            note_path=str(loaded.note_path),
            terminal_status=completion.terminal_status,
            stop_reason=completion.stop_reason,
        )
    except OSError as exc:
        LOGGER.error("Note write failed: %s", exc)
        return _error_result(
            session_dir,
            7,
            f"Failed to write note: {exc}",
            session_id=completion.session_id,
            decision=decision.value,
            note_path=str(loaded.note_path),
            terminal_status=completion.terminal_status,
            stop_reason=completion.stop_reason,
        )

    LOGGER.info(
        "Note write complete: path=%s created=%s replaced=%s written=%s",
        write_result.note_path,
        write_result.note_created,
        write_result.block_replaced,
        write_result.block_written,
    )

    return IngestResult(
        ok=True,
        exit_code=0,
        session_id=completion.session_id,
        session_dir=str(session_dir),
        decision=decision.value,
        note_path=str(write_result.note_path),
        note_created=write_result.note_created,
        block_written=write_result.block_written,
        block_replaced=write_result.block_replaced,
        terminal_status=completion.terminal_status,
        stop_reason=completion.stop_reason,
    )


def _error_result(
    session_dir: Path,
    exit_code: int,
    error: str,
    *,
    session_id: str | None = None,
    decision: str | None = None,
    note_path: str | None = None,
    terminal_status: str | None = None,
    stop_reason: str | None = None,
) -> IngestResult:
    return IngestResult(
        ok=False,
        exit_code=exit_code,
        session_id=session_id,
        session_dir=str(session_dir),
        decision=decision,
        note_path=note_path,
        note_created=False,
        block_written=False,
        block_replaced=False,
        terminal_status=terminal_status,
        stop_reason=stop_reason,
        error=error,
    )


def _attach_session_log_handler(log_path: Path) -> logging.Handler:
    """Append session-scoped logs to ``<session>/logs/briefing.log``."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(handler)
    return handler


def _missing_note_template(settings: AppSettings) -> MissingNoteTemplate:
    template_path = settings.paths.template_dir / settings.llm.note_template
    return MissingNoteTemplate(
        template_text=template_path.read_text(encoding="utf-8"),
        meeting_notes_placeholder=settings.output.meeting_notes_placeholder,
    )


def emit_stdout_result(result: IngestResult) -> None:
    """Write a single-line JSON result for noted to consume."""
    payload = result.as_stdout_payload()
    payload["emitted_at"] = datetime.now(timezone.utc).astimezone().isoformat()
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()
