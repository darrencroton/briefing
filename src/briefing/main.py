"""CLI entrypoint."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

import yaml

from .calendar import EventKitClient
from .logging_utils import configure_logging
from .settings import SettingsError, load_series_configs, load_settings
from .runner import run_briefing
from .utils import ensure_directory, slugify
from .validation import validate_environment


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
    return 1


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
