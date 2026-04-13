from __future__ import annotations

from datetime import datetime

from briefing.models import MeetingEvent
from briefing.notes import (
    find_previous_note,
    normalize_summary_bullets,
    note_is_locked,
    refresh_note,
    render_note,
)


def test_render_and_refresh_note_preserves_user_sections(app_settings, series_config) -> None:
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
        attendees=[{"name": "Barry", "email": "barry@example.edu"}],
    )
    template = (app_settings.paths.template_dir / "meeting_note.md").read_text(encoding="utf-8")
    note = render_note(
        app_settings,
        template,
        event,
        series_config,
        "- First summary bullet",
        datetime.fromisoformat("2026-04-13T09:00:00+10:00"),
    )
    updated = note.replace("## Meeting Notes\n- ", "## Meeting Notes\n- User note")
    refreshed = refresh_note(app_settings, updated, "- New summary bullet")

    assert "- New summary bullet" in refreshed
    assert "- User note" in refreshed


def test_note_lock_detection_ignores_placeholder(app_settings) -> None:
    unlocked = (
        "## Meeting Notes\n- \n\n## Actions\n- \n"
    )
    locked = (
        "## Meeting Notes\n- Added an update\n\n## Actions\n- \n"
    )

    assert note_is_locked(app_settings, unlocked) == (False, None)
    assert note_is_locked(app_settings, locked) == (True, "meeting_notes_edited")


def test_find_previous_note_uses_series_id_and_start(app_settings, series_config) -> None:
    first = app_settings.paths.meeting_notes_dir / "2026-04-01-1000-cas-strategy.md"
    second = app_settings.paths.meeting_notes_dir / "2026-04-08-1000-cas-strategy.md"
    first.write_text(
        "---\nseries_id: cas-strategy\nstart: 2026-04-01T10:00:00+10:00\ntitle: First\n---\n\n## Pre-Meeting Summary\n- One\n",
        encoding="utf-8",
    )
    second.write_text(
        "---\nseries_id: cas-strategy\nstart: 2026-04-08T10:00:00+10:00\ntitle: Second\n---\n\n## Pre-Meeting Summary\n- Two\n",
        encoding="utf-8",
    )
    event = MeetingEvent(
        uid="event-3",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-15T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-15T11:00:00+10:00"),
        calendar_name="Work",
    )

    path = find_previous_note(app_settings, event, series_config)

    assert path == second


def test_normalize_summary_bullets_converts_lists() -> None:
    normalized = normalize_summary_bullets("1. First\n* Second\nThird")

    assert normalized.splitlines() == ["- First", "- Second", "- Third"]

