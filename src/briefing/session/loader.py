"""Completed-session directory model and loader.

The session directory is the canonical layout from the contracts (section 11 / v1.0).
Callers pass one directory; this module resolves every artefact path from the
manifest. The note path is always read from ``manifest.paths.note_path``;
never inferred from filenames (guardrail 6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .completion import Completion


class SessionLoadError(Exception):
    """Raised when a session directory cannot be loaded."""

    exit_code: int = 4

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class ManifestMissing(SessionLoadError):
    exit_code = 4


class ManifestInvalid(SessionLoadError):
    exit_code = 4


class ManifestUnsupportedVersion(SessionLoadError):
    exit_code = 4


class SessionIdentityMismatch(SessionLoadError):
    exit_code = 4


_MAJOR_ONE = re.compile(r"^1\.[0-9]+$")

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "vendor"
    / "contracts"
    / "contracts"
    / "schemas"
    / "manifest.v1.json"
)

_VALIDATOR: Draft202012Validator | None = None


def _validator() -> Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        _VALIDATOR = Draft202012Validator(schema, format_checker=FormatChecker())
    return _VALIDATOR


@dataclass(slots=True)
class Manifest:
    """Parsed and validated manifest payload (read-only by ingest)."""

    schema_version: str
    session_id: str
    meeting: dict[str, Any]
    mode: dict[str, Any]
    participants: dict[str, Any]
    recording_policy: dict[str, Any]
    next_meeting: dict[str, Any]
    paths: dict[str, Any]
    transcription: dict[str, Any]
    raw: dict[str, Any]

    @property
    def note_path(self) -> Path:
        return Path(self.paths["note_path"])

    @property
    def title(self) -> str:
        return str(self.meeting.get("title", "")).strip()

    @property
    def event_id(self) -> str | None:
        value = self.meeting.get("event_id")
        return str(value) if value else None

    @property
    def series_id(self) -> str | None:
        value = self.meeting.get("series_id")
        return str(value) if value else None

    @property
    def host_name(self) -> str:
        return str(self.participants.get("host_name", "")).strip()

    @property
    def participant_names(self) -> list[str]:
        names = self.participants.get("participant_names") or []
        return [str(name) for name in names if str(name).strip()]


@dataclass(slots=True)
class LoadedSession:
    """Every path and payload an ingest run needs from one session directory."""

    session_dir: Path
    manifest: Manifest
    completion: Completion | None
    manifest_path: Path
    transcript_text_path: Path
    transcript_json_path: Path
    briefing_log_path: Path
    note_path: Path


def load_manifest(session_dir: Path) -> Manifest:
    """Load and validate ``manifest.json`` from a session directory."""
    path = session_dir / "manifest.json"
    if not path.exists():
        raise ManifestMissing(f"Manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestInvalid(f"Manifest is not valid JSON: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise ManifestInvalid(f"Manifest must be a JSON object: {path}")

    version = payload.get("schema_version")
    if not isinstance(version, str) or not _MAJOR_ONE.match(version):
        raise ManifestUnsupportedVersion(
            f"Unsupported manifest schema_version {version!r}; reader accepts 1.x only."
        )

    errors = sorted(
        _validator().iter_errors(payload),
        key=lambda err: list(err.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
            for err in errors[:5]
        )
        raise ManifestInvalid(f"Manifest schema validation failed for {path}: {details}")

    return Manifest(
        schema_version=version,
        session_id=str(payload["session_id"]),
        meeting=dict(payload["meeting"]),
        mode=dict(payload["mode"]),
        participants=dict(payload["participants"]),
        recording_policy=dict(payload["recording_policy"]),
        next_meeting=dict(payload["next_meeting"]),
        paths=dict(payload["paths"]),
        transcription=dict(payload["transcription"]),
        raw=payload,
    )


def resolve_paths(session_dir: Path, manifest: Manifest) -> dict[str, Path]:
    """Resolve the fixed artefact paths for a session directory."""
    return {
        "manifest": session_dir / "manifest.json",
        "transcript_text": session_dir / "transcript" / "transcript.txt",
        "transcript_json": session_dir / "transcript" / "transcript.json",
        "briefing_log": session_dir / "logs" / "briefing.log",
        "note": manifest.note_path,
    }


def load_session(session_dir: Path, *, completion: Completion | None = None) -> LoadedSession:
    """Load manifest + completion and resolve artefact paths.

    ``completion`` may be passed in when the caller has already validated it
    (normal case); pass ``None`` when the caller wants the manifest alone.
    """
    session_dir = session_dir.resolve()
    manifest = load_manifest(session_dir)
    if completion is not None:
        _validate_completion_matches_manifest(completion, manifest)
    paths = resolve_paths(session_dir, manifest)
    return LoadedSession(
        session_dir=session_dir,
        manifest=manifest,
        completion=completion,
        manifest_path=paths["manifest"],
        transcript_text_path=paths["transcript_text"],
        transcript_json_path=paths["transcript_json"],
        briefing_log_path=paths["briefing_log"],
        note_path=paths["note"],
    )


def _validate_completion_matches_manifest(completion: Completion, manifest: Manifest) -> None:
    if completion.session_id != manifest.session_id:
        raise SessionIdentityMismatch(
            "Completion session_id does not match manifest session_id: "
            f"{completion.session_id!r} != {manifest.session_id!r}"
        )
    if completion.manifest_schema_version != manifest.schema_version:
        raise SessionIdentityMismatch(
            "Completion manifest_schema_version does not match manifest schema_version: "
            f"{completion.manifest_schema_version!r} != {manifest.schema_version!r}"
        )
