from __future__ import annotations

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

