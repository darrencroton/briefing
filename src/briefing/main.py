"""CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from .calendar import EventKitClient
from .logging_utils import configure_logging
from .planning import plan_event_by_id
from .retention import emit_retention_result, run_retention_sweep
from .session.ingest import IngestResult, emit_stdout_result, run_session_ingest
from .session.reprocess import run_session_reprocess
from .settings import SettingsError, load_series_configs, load_settings
from .runner import run_briefing
from .utils import ensure_directory, slugify
from .validation import validate_environment
from .watch import run_watch


def cli() -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(description="Generate briefing notes for upcoming meetings")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Process upcoming configured meetings")
    run_parser.add_argument("--dry-run", action="store_true", help="Generate but do not write notes")
    run_parser.add_argument("--now", help="Override current time with an ISO timestamp")

    subparsers.add_parser("validate", help="Validate configuration, auth, and dependencies")

    init_parser = subparsers.add_parser("init-series", help="Bootstrap a series config from an upcoming event")
    init_parser.add_argument("--event-uid", help="Select an upcoming event by UID")
    init_parser.add_argument("--index", type=int, help="Select an upcoming event by 1-based index")
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing series file")

    ingest_parser = subparsers.add_parser(
        "session-ingest",
        help="Ingest a completed noted session directory and write the post-meeting summary",
    )
    ingest_parser.add_argument(
        "--session-dir",
        required=True,
        help="Path to the session directory produced by noted",
    )
    ingest_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read completion/transcript and generate the summary without writing the note",
    )

    reprocess_parser = subparsers.add_parser(
        "session-reprocess",
        help="Rerun summary generation from an existing transcript (recovery path)",
    )
    reprocess_parser.add_argument(
        "--session-dir",
        required=True,
        help="Path to the session directory produced by noted",
    )
    reprocess_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the summary without writing the note",
    )

    plan_parser = subparsers.add_parser(
        "session-plan",
        help="Write a noted manifest for one calendar event",
    )
    plan_parser.add_argument("--event-id", required=True, help="Calendar event UID to plan")
    plan_parser.add_argument("--now", help="Override current time with an ISO timestamp")

    watch_parser = subparsers.add_parser(
        "watch",
        help="Watch upcoming meetings and launch noted at pre-roll",
    )
    watch_parser.add_argument("--once", action="store_true", help="Run one watch cycle and exit")
    watch_parser.add_argument("--dry-run", action="store_true", help="Plan but do not launch noted")

    retention_parser = subparsers.add_parser(
        "retention-sweep",
        help="Move expired raw audio from completed sessions to macOS Trash",
    )
    retention_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report expired raw audio without moving files to Trash",
    )

    args = parser.parse_args()
    try:
        settings = load_settings()
    except (FileNotFoundError, SettingsError) as exc:
        print(exc, file=sys.stderr)
        return 1
    configure_logging(settings)

    if args.command == "run":
        now = datetime.fromisoformat(args.now) if args.now else None
        return run_briefing(settings, now=now, dry_run=args.dry_run)
    if args.command == "validate":
        return _validate(settings)
    if args.command == "init-series":
        return _init_series(settings, args.event_uid, args.index, args.force)
    if args.command == "session-ingest":
        return _session_ingest(settings, args.session_dir, dry_run=args.dry_run)
    if args.command == "session-reprocess":
        return _session_reprocess(settings, args.session_dir, dry_run=args.dry_run)
    if args.command == "session-plan":
        now = datetime.fromisoformat(args.now) if args.now else None
        return _session_plan(settings, args.event_id, now)
    if args.command == "watch":
        return run_watch(settings, once=args.once, dry_run=args.dry_run)
    if args.command == "retention-sweep":
        result = run_retention_sweep(settings, dry_run=args.dry_run)
        emit_retention_result(result)
        return result.exit_code
    return 1


def _session_ingest(settings, session_dir_arg: str, *, dry_run: bool = False) -> int:
    session_dir = Path(session_dir_arg).expanduser()
    if not session_dir.exists() or not session_dir.is_dir():
        emit_stdout_result(
            IngestResult(
                ok=False,
                exit_code=4,
                session_id=None,
                session_dir=str(session_dir),
                decision=None,
                note_path=None,
                note_created=False,
                block_written=False,
                block_replaced=False,
                terminal_status=None,
                stop_reason=None,
                error=f"session-dir not found or not a directory: {session_dir}",
                dry_run=dry_run,
            )
        )
        return 4
    result = run_session_ingest(settings, session_dir, dry_run=dry_run)
    emit_stdout_result(result)
    return result.exit_code


def _session_reprocess(settings, session_dir_arg: str, *, dry_run: bool = False) -> int:
    session_dir = Path(session_dir_arg).expanduser()
    if not session_dir.exists() or not session_dir.is_dir():
        emit_stdout_result(
            IngestResult(
                ok=False,
                exit_code=4,
                session_id=None,
                session_dir=str(session_dir),
                decision=None,
                note_path=None,
                note_created=False,
                block_written=False,
                block_replaced=False,
                terminal_status=None,
                stop_reason=None,
                error=f"session-dir not found or not a directory: {session_dir}",
                dry_run=dry_run,
            )
        )
        return 4
    result = run_session_reprocess(settings, session_dir, dry_run=dry_run)
    emit_stdout_result(result)
    return result.exit_code


def _session_plan(settings, event_id: str, now: datetime | None) -> int:
    try:
        result = plan_event_by_id(settings, event_id, now=now)
    except Exception as exc:
        print(
            json.dumps({
                "ok": False,
                "status": "error",
                "event_uid": event_id,
                "skip_reason": str(exc),
            }, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(result.to_json_line())
    if result.status == "not_found":
        return 2
    return 0


def _validate(settings) -> int:
    series_configs = load_series_configs(settings)
    messages = validate_environment(settings, series_configs)
    exit_code = 0
    for message in messages:
        print(f"[{message.level.upper()}] {message.code}: {message.message}")
        if message.level == "error":
            exit_code = 1
    return exit_code


def _init_series(settings, event_uid: str | None, index: int | None, force: bool) -> int:
    client = EventKitClient(settings)
    now = datetime.now().astimezone()
    end = now + timedelta(days=settings.calendar.lookback_days_for_init)
    events = client.fetch_events(now, end)
    if not events:
        print("No upcoming events found in the configured window.")
        return 1

    event = None
    if event_uid:
        for candidate in events:
            if candidate.uid == event_uid:
                event = candidate
                break
    elif index is not None:
        if 1 <= index <= len(events):
            event = events[index - 1]
    elif len(events) == 1:
        event = events[0]
    else:
        print("Multiple upcoming events found. Re-run with --index or --event-uid:")
        for idx, candidate in enumerate(events, start=1):
            print(f"{idx}. {candidate.start.isoformat()} :: {candidate.title} :: {candidate.uid}")
        return 1

    if event is None:
        print("Selected event was not found.")
        return 1

    note_slug = slugify(event.title)
    path = settings.paths.series_dir / f"{note_slug}.yaml"
    if path.exists() and not force:
        print(f"Series file already exists: {path}")
        return 1

    payload = {
        "series_id": note_slug,
        "display_name": event.title,
        "note_slug": note_slug,
        "match": {
            "title_any": [event.title],
            "attendee_emails_any": [email for email in event.attendee_emails if email],
            "organizer_emails_any": [event.organizer_email] if event.organizer_email else [],
            "calendar_names_any": [event.calendar_name] if event.calendar_name else [],
        },
        "sources": {
            "slack": {"channel_refs": [], "dm_conversation_ids": [], "required": False},
            "notion": [],
            "files": [],
            "email": [],
        },
    }
    ensure_directory(settings.paths.series_dir)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
