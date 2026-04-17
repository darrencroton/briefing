from __future__ import annotations

from datetime import datetime

from briefing.models import MeetingEvent
from briefing.notes import (
    find_previous_note,
    normalize_summary_bullets,
    note_is_locked,
    parse_frontmatter,
    refresh_note,
    render_note,
    summarize_previous_note,
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
    )
    frontmatter, _ = parse_frontmatter(note)

    assert frontmatter == {
        "title": "CAS Strategy Meeting 10–11am",
        "series_id": "cas-strategy",
        "start": "2026-04-13T10:00:00+10:00",
    }
    assert 'title: CAS Strategy Meeting 10–11am' in note
    assert "\\u2013" not in note
    assert "[[2026-04-13]] | [[CAS Strategy Meeting Meetings]]" in note
    assert "## Briefing\n\n- First summary bullet" in note
    assert "## Meeting Notes\n\n- " in note

    updated = note.replace("## Meeting Notes\n\n- ", "## Meeting Notes\n\n- User note")
    refreshed = refresh_note(updated, "- New summary bullet")

    assert "- New summary bullet" in refreshed
    assert "- User note" in refreshed
    assert "## Briefing" in refreshed
    assert "<!-- BRIEFING:" not in refreshed


def test_render_note_uses_compact_same_meridiem_time_window(app_settings, series_config) -> None:
    event = MeetingEvent(
        uid="event-1",
        title="Barry",
        start=datetime.fromisoformat("2026-04-13T17:15:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T17:45:00+10:00"),
        calendar_name="Work",
    )
    template = (app_settings.paths.template_dir / "meeting_note.md").read_text(encoding="utf-8")

    note = render_note(app_settings, template, event, series_config, "- First summary bullet")
    frontmatter, _ = parse_frontmatter(note)

    assert "# Barry 5:15–5:45pm" in note
    assert "# Barry 5:15pm–5:45pm" not in note
    assert frontmatter["title"] == "Barry 5:15–5:45pm"


def test_render_note_keeps_both_meridiems_when_range_crosses(app_settings, series_config) -> None:
    event = MeetingEvent(
        uid="event-1",
        title="Lunch",
        start=datetime.fromisoformat("2026-04-13T11:45:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T12:15:00+10:00"),
        calendar_name="Work",
    )
    template = (app_settings.paths.template_dir / "meeting_note.md").read_text(encoding="utf-8")

    note = render_note(app_settings, template, event, series_config, "- First summary bullet")

    assert "# Lunch 11:45am–12:15pm" in note


def test_note_lock_detection_ignores_placeholder(app_settings) -> None:
    unlocked = "## Meeting Notes\n\n- \n"
    locked = "## Meeting Notes\n\n- Added an update\n"

    assert note_is_locked(app_settings, unlocked) == (False, None)
    assert note_is_locked(app_settings, locked) == (True, "meeting_notes_edited")


def test_find_previous_note_uses_series_id_and_start(app_settings, series_config) -> None:
    first = app_settings.paths.meeting_notes_dir / "2026-04-01-1000-cas-strategy.md"
    second = app_settings.paths.meeting_notes_dir / "2026-04-08-1000-cas-strategy.md"
    first.write_text(
        "---\nseries_id: cas-strategy\nstart: 2026-04-01T10:00:00+10:00\n---\n\n# First 10am–11am\n[[2026-04-01]] | [[CAS Strategy Meeting Meetings]]\n\n---\n## Briefing\n\n- One\n\n---\n## Meeting Notes\n\n- \n",
        encoding="utf-8",
    )
    second.write_text(
        "---\nseries_id: cas-strategy\nstart: 2026-04-08T10:00:00+10:00\n---\n\n# Second 10am–11am\n[[2026-04-08]] | [[CAS Strategy Meeting Meetings]]\n\n---\n## Briefing\n\n- Two\n\n---\n## Meeting Notes\n\n- \n",
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


def test_summarize_previous_note_extracts_title_from_compact_time_heading(app_settings) -> None:
    note_path = app_settings.paths.meeting_notes_dir / "2026-04-08-1000-barry.md"
    note_path.write_text(
        "---\nseries_id: barry\nstart: 2026-04-08T17:15:00+10:00\n---\n\n# Barry 5:15–5:45pm\n[[2026-04-08]] | [[Barry Meetings]]\n\n---\n## Briefing\n\n- Two\n\n---\n## Meeting Notes\n\n- \n",
        encoding="utf-8",
    )

    summary = summarize_previous_note(note_path)

    assert "Title: Barry" in summary
    assert "## Meeting Notes" not in summary


def test_summarize_previous_note_keeps_non_empty_meeting_notes(app_settings) -> None:
    note_path = app_settings.paths.meeting_notes_dir / "2026-04-08-1000-followup.md"
    note_path.write_text(
        "---\nseries_id: followup\nstart: 2026-04-08T10:00:00+10:00\n---\n\n# Followup 10am–11am\n[[2026-04-08]] | [[Followup Meetings]]\n\n---\n## Briefing\n\n- Review draft\n\n---\n## Meeting Notes\n\n- Send revised figures before Friday\n",
        encoding="utf-8",
    )

    summary = summarize_previous_note(note_path)

    assert "## Meeting Notes\n- Send revised figures before Friday" in summary


def test_normalize_summary_bullets_converts_lists() -> None:
    normalized = normalize_summary_bullets("1. First\n* Second\nThird")

    assert normalized.splitlines() == ["- First", "- Second", "- Third"]


def test_normalize_summary_bullets_preserves_single_blank_lines_between_groups() -> None:
    normalized = normalize_summary_bullets(
        "1. Open action\n\n* Previous note context\n\nSlack update"
    )

    assert normalized == (
        "- Open action\n\n- Previous note context\n\n- Slack update"
    )


def test_normalize_summary_bullets_strips_channel_style_hashes_but_keeps_issue_numbers() -> None:
    normalized = normalize_summary_bullets(
        "Per Slack (#general): follow up in #jayde-phd after issue #42"
    )

    assert normalized == "- Per Slack (general): follow up in jayde-phd after issue #42"
