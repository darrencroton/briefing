"""Apple Calendar access through icalPal."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from datetime import datetime, timedelta

from .models import MeetingEvent
from .settings import AppSettings
from .utils import first_non_empty, parse_datetime, shell_join


class CalendarError(RuntimeError):
    """Raised when icalPal fails."""


class IcalPalClient:
    """Thin icalPal wrapper."""

    def __init__(self, settings: AppSettings):
        self.settings = settings

    def fetch_events(self, start: datetime, end: datetime) -> list[MeetingEvent]:
        """Fetch events in a specific window."""
        command = [
            self.settings.calendar.icalpal_path,
            "-o",
            "json",
            "-c",
            "events",
            f"--from={start.isoformat()}",
            f"--to={end.isoformat()}",
            "--uid",
            "--aep=all",
        ]
        if not self.settings.calendar.include_all_day:
            command.append("--ea")
        for calendar_name in self.settings.calendar.include_calendar_names:
            command.append(f"--ic={calendar_name}")
        for calendar_name in self.settings.calendar.exclude_calendar_names:
            command.append(f"--ec={calendar_name}")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise CalendarError(f"icalPal failed: {message}")

        return parse_icalpal_events(completed.stdout)

    def fetch_upcoming(self, now: datetime) -> list[MeetingEvent]:
        """Fetch upcoming candidate meetings."""
        window_start = now + timedelta(minutes=self.settings.calendar.window_min_minutes)
        window_end = now + timedelta(minutes=self.settings.calendar.window_max_minutes)
        return [
            event
            for event in self.fetch_events(window_start, window_end)
            if event.start >= window_start and event.start <= window_end
        ]

    def validate_access(self) -> tuple[bool, str]:
        """Check that icalPal is callable and can read the Calendar DB."""
        now = datetime.now().replace(second=0, microsecond=0)
        end = now + timedelta(minutes=1)
        command = [
            self.settings.calendar.icalpal_path,
            "-o",
            "json",
            "-c",
            "events",
            f"--from={now.isoformat()}",
            f"--to={end.isoformat()}",
            "--uid",
            "--aep=all",
            "--li=1",
        ]
        if not self.settings.calendar.include_all_day:
            command.append("--ea")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            return False, f"{shell_join(command)} :: {message}"
        return True, "icalPal calendar query succeeded"


def parse_icalpal_events(payload: str) -> list[MeetingEvent]:
    """Parse the loose JSON that icalPal returns."""
    if not payload.strip():
        return []
    data = json.loads(payload)
    if isinstance(data, dict):
        if "events" in data and isinstance(data["events"], list):
            records = data["events"]
        elif "items" in data and isinstance(data["items"], list):
            records = data["items"]
        else:
            records = [data]
    else:
        records = data
    return [_parse_event_record(record) for record in records if isinstance(record, dict)]


def _parse_event_record(record: dict[str, object]) -> MeetingEvent:
    uid = str(first_non_empty([record.get("uid"), record.get("UUID"), record.get("id")]) or "")
    title = str(first_non_empty([record.get("title"), record.get("summary"), record.get("name")]) or "")
    start = parse_datetime(
        first_non_empty(
            [
                record.get("start"),
                record.get("start_date"),
                record.get("startDate"),
                record.get("datetime"),
                record.get("date"),
            ]
        )
    )
    end = parse_datetime(
        first_non_empty([record.get("end"), record.get("end_date"), record.get("endDate")])
    )
    if not uid or not title or start is None:
        raise CalendarError(f"Could not parse icalPal event record: {record}")

    attendees = _parse_attendees(record.get("attendees"))
    organizer = _parse_person(record.get("organizer"))
    return MeetingEvent(
        uid=uid,
        title=title,
        start=start,
        end=end,
        calendar_name=_string_or_none(
            first_non_empty([record.get("calendar"), record.get("calendar_name")])
        ),
        organizer_name=organizer.get("name"),
        organizer_email=organizer.get("email"),
        location=_string_or_none(record.get("location")),
        notes=_string_or_none(first_non_empty([record.get("notes"), record.get("description")])),
        url=_string_or_none(first_non_empty([record.get("url"), record.get("conference_url")])),
        attendees=attendees,
        raw=record,
    )


def _parse_attendees(value: object) -> list[dict[str, str]]:
    if value is None:
        return []
    attendees: list[dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if item is None:
                continue
            if isinstance(item, dict):
                attendees.append(
                    {
                        "name": str(first_non_empty([item.get("name"), item.get("display_name")]) or ""),
                        "email": str(
                            first_non_empty([item.get("email"), item.get("address")]) or ""
                        ).lower(),
                    }
                )
            else:
                attendees.extend(_parse_attendee_strings([str(item)]))
        return [item for item in attendees if item.get("name") or item.get("email")]
    if isinstance(value, str):
        return _parse_attendee_strings(value.splitlines())
    return []


def _parse_attendee_strings(values: Iterable[str]) -> list[dict[str, str]]:
    attendees: list[dict[str, str]] = []
    for item in values:
        text = item.strip()
        if not text:
            continue
        if "<" in text and text.endswith(">"):
            name, email = text.rsplit("<", 1)
            attendees.append({"name": name.strip(), "email": email[:-1].strip().lower()})
        elif "@" in text:
            attendees.append({"name": "", "email": text.lower()})
        else:
            attendees.append({"name": text, "email": ""})
    return attendees


def _parse_person(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "name": str(first_non_empty([value.get("name"), value.get("display_name")]) or ""),
            "email": str(first_non_empty([value.get("email"), value.get("address")]) or "").lower(),
        }
    if isinstance(value, str):
        parsed = _parse_attendee_strings([value])
        if parsed:
            return parsed[0]
    return {}


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
