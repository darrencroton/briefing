"""Completion-file reader and ingest-decision resolver (B-12).

`briefing session-ingest` must read `outputs/completion.json` first; it never
infers session outcome from file presence or log parsing (guardrail 3).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class CompletionError(Exception):
    """Raised when a completion payload cannot be accepted."""

    exit_code: int = 3

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class CompletionMissing(CompletionError):
    """No completion.json on disk."""

    exit_code = 2


class CompletionInvalid(CompletionError):
    """Payload exists but is malformed JSON or fails schema validation."""

    exit_code = 3


class CompletionUnsupportedVersion(CompletionError):
    """Schema major version is not 1."""

    exit_code = 3


@dataclass(frozen=True, slots=True)
class Completion:
    """Parsed and validated completion payload."""

    schema_version: str
    session_id: str
    manifest_schema_version: str
    terminal_status: str
    stop_reason: str
    audio_capture_ok: bool
    transcript_ok: bool
    diarization_ok: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    completed_at: str
    raw: dict[str, Any]


class IngestDecision(str, Enum):
    """Next action derived from completion payload and on-disk state.

    - ``SUMMARISE`` / ``SUMMARISE_WITH_WARNINGS``: transcript is available, run
      the full post-meeting flow.
    - ``TRANSCRIPT_MISSING``: raw audio survived but the transcript did not —
      recoverable via ``session-reprocess`` once that lands.
    - ``STARTUP_FAILED``: no audio captured at all; nothing to recover.
    """

    SUMMARISE = "summarise"
    SUMMARISE_WITH_WARNINGS = "summarise_with_warnings"
    TRANSCRIPT_MISSING = "transcript_missing"
    STARTUP_FAILED = "startup_failed"


_MAJOR_ONE = re.compile(r"^1\.[0-9]+$")

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "vendor"
    / "contracts"
    / "contracts"
    / "schemas"
    / "completion.v1.json"
)


def _load_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


_VALIDATOR: Draft202012Validator | None = None


def _validator() -> Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        _VALIDATOR = _load_validator()
    return _VALIDATOR


def completion_path(session_dir: Path) -> Path:
    """Return the on-disk path of the completion file for a session."""
    return session_dir / "outputs" / "completion.json"


def read_completion(session_dir: Path) -> Completion:
    """Read and validate outputs/completion.json.

    Raises ``CompletionMissing``, ``CompletionInvalid``, or
    ``CompletionUnsupportedVersion`` when the payload cannot be accepted.
    """
    path = completion_path(session_dir)
    if not path.exists():
        raise CompletionMissing(f"Completion file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CompletionInvalid(f"Completion file is not valid JSON: {path} ({exc})") from exc

    if not isinstance(payload, dict):
        raise CompletionInvalid(f"Completion file must be a JSON object: {path}")

    version = payload.get("schema_version")
    if not isinstance(version, str) or not _MAJOR_ONE.match(version):
        raise CompletionUnsupportedVersion(
            f"Unsupported completion schema_version {version!r}; reader accepts 1.x only."
        )

    errors = sorted(
        _validator().iter_errors(payload),
        key=lambda err: list(err.absolute_path),
    )
    if errors:
        details = "; ".join(f"{'.'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}" for err in errors[:5])
        raise CompletionInvalid(f"Completion schema validation failed for {path}: {details}")

    return Completion(
        schema_version=version,
        session_id=str(payload["session_id"]),
        manifest_schema_version=str(payload["manifest_schema_version"]),
        terminal_status=str(payload["terminal_status"]),
        stop_reason=str(payload["stop_reason"]),
        audio_capture_ok=bool(payload["audio_capture_ok"]),
        transcript_ok=bool(payload["transcript_ok"]),
        diarization_ok=bool(payload["diarization_ok"]),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
        completed_at=str(payload["completed_at"]),
        raw=payload,
    )


def decide(completion: Completion) -> IngestDecision:
    """Map a completion payload onto the ingest decision tree (§27.5)."""
    if not completion.audio_capture_ok:
        return IngestDecision.STARTUP_FAILED
    if not completion.transcript_ok:
        return IngestDecision.TRANSCRIPT_MISSING
    if completion.terminal_status == "failed":
        return IngestDecision.TRANSCRIPT_MISSING
    if completion.terminal_status == "completed_with_warnings" or completion.warnings:
        return IngestDecision.SUMMARISE_WITH_WARNINGS
    return IngestDecision.SUMMARISE


def decision_should_summarise(decision: IngestDecision) -> bool:
    return decision in (IngestDecision.SUMMARISE, IngestDecision.SUMMARISE_WITH_WARNINGS)
