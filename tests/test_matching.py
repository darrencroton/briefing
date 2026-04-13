from __future__ import annotations

from datetime import datetime

from briefing.matching import match_series
from briefing.models import MatchRules, MeetingEvent, SeriesConfig, SeriesSources


def test_match_series_requires_all_populated_match_groups() -> None:
    event = MeetingEvent(
        uid="abc",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
        organizer_email="barry@example.edu",
        attendees=[{"name": "Darren", "email": "darren@example.edu"}],
    )
    matching = SeriesConfig(
        path=None,
        series_id="match",
        display_name="Match",
        note_slug="match",
        match=MatchRules(
            title_any=["CAS Strategy Meeting"],
            organizer_emails_any=["barry@example.edu"],
            calendar_names_any=["work"],
        ),
        sources=SeriesSources(),
    )
    non_matching = SeriesConfig(
        path=None,
        series_id="miss",
        display_name="Miss",
        note_slug="miss",
        match=MatchRules(
            title_any=["CAS Strategy Meeting"],
            attendee_emails_any=["someone@example.edu"],
        ),
        sources=SeriesSources(),
    )

    matches = match_series(event, [matching, non_matching])

    assert [config.series_id for config in matches] == ["match"]

