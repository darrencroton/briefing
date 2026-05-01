"""Raw-audio retention enforcement for completed noted sessions."""

from __future__ import annotations

import json
import logging
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .session.completion import CompletionError, read_completion
from .settings import AppSettings


LOGGER = logging.getLogger("briefing.retention")

_RAW_AUDIO_SUFFIXES = frozenset({".wav"})  # extend to include ".flac" when FLAC compression is wired


class RetentionTrashError(RuntimeError):
    """Raised when a file cannot be moved to the system Trash."""


TrashFn = Callable[[Path], None]


@dataclass(slots=True)
class RetentionResult:
    """Machine-readable result for one retention sweep."""

    ok: bool
    dry_run: bool
    sessions_root: str
    retention_days: int
    cutoff: str
    scanned_sessions: int = 0
    eligible_sessions: int = 0
    trashed_files: list[str] = field(default_factory=list)
    skipped_files: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def as_stdout_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "sessions_root": self.sessions_root,
            "retention_days": self.retention_days,
            "cutoff": self.cutoff,
            "scanned_sessions": self.scanned_sessions,
            "eligible_sessions": self.eligible_sessions,
            "trashed_files": self.trashed_files,
            "skipped_files": self.skipped_files,
            "errors": self.errors,
        }


def run_retention_sweep(
    settings: AppSettings,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
    trash_fn: TrashFn | None = None,
) -> RetentionResult:
    """Move expired raw audio files for completed sessions to macOS Trash."""
    now = now or datetime.now().astimezone()
    cutoff = now - timedelta(days=settings.meeting_intelligence.raw_audio_retention_days)
    result = RetentionResult(
        ok=True,
        dry_run=dry_run,
        sessions_root=str(settings.meeting_intelligence.sessions_root),
        retention_days=settings.meeting_intelligence.raw_audio_retention_days,
        cutoff=cutoff.isoformat(),
    )

    sessions_root = settings.meeting_intelligence.sessions_root
    if not sessions_root.exists():
        return result
    if not sessions_root.is_dir():
        result.ok = False
        result.errors.append({
            "path": str(sessions_root),
            "reason": "sessions_root_not_directory",
        })
        return result

    trash_fn = trash_fn or move_to_system_trash
    for session_dir in sorted(path for path in sessions_root.iterdir() if path.is_dir()):
        result.scanned_sessions += 1
        _sweep_session(session_dir, cutoff, result, dry_run=dry_run, trash_fn=trash_fn)

    result.ok = not result.errors
    return result


def run_retention_sweep_best_effort(settings: AppSettings, *, dry_run: bool = False) -> None:
    """Run retention without letting cleanup failures affect primary workflows."""
    try:
        result = run_retention_sweep(settings, dry_run=dry_run)
    except Exception as exc:  # pragma: no cover - defensive workflow isolation
        LOGGER.warning("Raw-audio retention sweep failed unexpectedly: %s", exc)
        return
    if result.errors:
        LOGGER.warning(
            "Raw-audio retention sweep completed with %d error(s): %s",
            len(result.errors),
            result.errors,
        )
    elif result.eligible_sessions or result.trashed_files:
        LOGGER.info(
            "Raw-audio retention sweep complete: scanned=%d eligible=%d trashed=%d dry_run=%s",
            result.scanned_sessions,
            result.eligible_sessions,
            len(result.trashed_files),
            dry_run,
        )


def _sweep_session(
    session_dir: Path,
    cutoff: datetime,
    result: RetentionResult,
    *,
    dry_run: bool,
    trash_fn: TrashFn,
) -> None:
    try:
        completion = read_completion(session_dir)
    except CompletionError as exc:
        result.skipped_files.append({
            "path": str(session_dir),
            "reason": f"completion_unavailable:{exc.__class__.__name__}",
        })
        return

    try:
        completed_at = _parse_completed_at(completion.completed_at)
    except ValueError as exc:
        result.skipped_files.append({
            "path": str(session_dir),
            "reason": f"completion_completed_at_invalid:{exc}",
        })
        return

    if completed_at > cutoff:
        result.skipped_files.append({
            "path": str(session_dir),
            "reason": "retention_window_active",
        })
        return

    audio_dir = session_dir / "audio"
    if not audio_dir.is_dir():
        result.skipped_files.append({
            "path": str(session_dir),
            "reason": "audio_dir_missing",
        })
        return

    candidates = list(_iter_raw_audio_files(audio_dir))
    if not candidates:
        result.skipped_files.append({
            "path": str(session_dir),
            "reason": "raw_audio_files_missing",
        })
        return

    result.eligible_sessions += 1
    for audio_path in candidates:
        if dry_run:
            result.trashed_files.append(str(audio_path))
            continue
        try:
            trash_fn(audio_path)
            result.trashed_files.append(str(audio_path))
        except Exception as exc:
            result.errors.append({
                "path": str(audio_path),
                "reason": str(exc),
            })


def _iter_raw_audio_files(audio_dir: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(audio_dir.iterdir())
        if path.is_file() and path.suffix.lower() in _RAW_AUDIO_SUFFIXES
    )


def _parse_completed_at(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no UTC offset")
    return parsed


def move_to_system_trash(path: Path) -> None:
    """Move one file to Trash using the native macOS Finder-like API."""
    if sys.platform != "darwin":
        raise RetentionTrashError("system Trash is only supported on macOS")

    try:
        from AppKit import NSWorkspace
        from Foundation import NSURL
    except ImportError as exc:  # pragma: no cover - pyobjc is installed on supported macOS
        raise RetentionTrashError(f"macOS Trash APIs unavailable: {exc}") from exc

    source = path.resolve()
    done = threading.Event()
    state: dict[str, object] = {"error": None}

    def completion_handler(_new_urls, error) -> None:
        state["error"] = error
        done.set()

    url = NSURL.fileURLWithPath_(str(source))
    NSWorkspace.sharedWorkspace().recycleURLs_completionHandler_([url], completion_handler)
    if not done.wait(timeout=30):
        raise RetentionTrashError("timed out waiting for Trash request")
    if state["error"] is not None:
        raise RetentionTrashError(str(state["error"]))
    if source.exists():
        raise RetentionTrashError("file still exists after Trash request")


def emit_retention_result(result: RetentionResult) -> None:
    """Write a single-line JSON retention result for humans and scripts."""
    json.dump(result.as_stdout_payload(), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    sys.stdout.flush()
