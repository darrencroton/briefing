from __future__ import annotations

from datetime import datetime
from pathlib import Path

from briefing.calendar import parse_icalpal_events


def test_parse_icalpal_events_extracts_expected_fields() -> None:
    payload = Path("tests/fixtures/icalpal/events.json").read_text(encoding="utf-8")
    events = parse_icalpal_events(payload)

    assert len(events) == 1
    event = events[0]
    assert event.uid == "event-123"
    assert event.title == "CAS Strategy Meeting"
    assert event.calendar_name == "Work"
    assert event.organizer_email == "barry@example.edu"
    assert event.attendee_emails == ["darren@example.edu", "barry@example.edu"]
    assert event.location == "Building A"


def test_parse_icalpal_events_accepts_exchange_uuid_and_epoch_dates() -> None:
    payload = """
    [
      {
        "UUID": "D802F715-B20A-4EA7-BF93-C75815A49CD3",
        "title": "Ray",
        "calendar": "Calendar",
        "start_date": 1776135600,
        "end_date": 1776137400,
        "start_tz": "Australia/Melbourne",
        "end_tz": "Australia/Melbourne",
        "attendees": [null]
      }
    ]
    """

    events = parse_icalpal_events(payload)

    assert len(events) == 1
    event = events[0]
    assert event.uid == "D802F715-B20A-4EA7-BF93-C75815A49CD3"
    assert event.title == "Ray"
    assert event.calendar_name == "Calendar"
    assert event.attendees == []
    assert event.start.timestamp() == datetime.fromtimestamp(1776135600).timestamp()
    assert event.end is not None
    assert event.end.timestamp() == datetime.fromtimestamp(1776137400).timestamp()
