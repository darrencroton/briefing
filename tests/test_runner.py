from __future__ import annotations

from datetime import datetime

from briefing.llm import LLMResponse
from briefing.models import MeetingEvent, OccurrenceState, SourceResult
from briefing.runner import process_event
from briefing.runner import run_briefing
from briefing.state import StateStore


class FakeProvider:
    def generate(self, prompt: str) -> LLMResponse:
        assert "Sources:" in prompt
        return LLMResponse(text="- Generated summary", raw='{"result":"- Generated summary"}')


class EmptyCalendar:
    def fetch_upcoming(self, now: datetime) -> list[MeetingEvent]:
        return []


def test_process_event_writes_note_and_locks_after_user_edit(monkeypatch, app_settings, series_config) -> None:
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    state_store = StateStore(app_settings)
    monkeypatch.setattr(
        "briefing.runner.collect_sources",
        lambda settings, event, series, logger, env: [
            SourceResult(
                source_type="previous_note",
                label="Previous meeting note",
                content="No previous note found.",
                required=False,
                status="ok",
            )
        ],
    )

    result = process_event(
        settings=app_settings,
        event=event,
        series_configs=[series_config],
        env={},
        state_store=state_store,
        provider=FakeProvider(),
        now=datetime.fromisoformat("2026-04-13T09:30:00+10:00"),
        dry_run=False,
    )

    assert result["status"] == "written"
    output_path = app_settings.paths.meeting_notes_dir / "2026-04-13-1000-cas-strategy-meeting.md"
    assert output_path.exists()
    text = output_path.read_text(encoding="utf-8")
    assert "- Generated summary" in text

    edited = text.replace("## Meeting Notes\n\n- ", "## Meeting Notes\n\n- User wrote notes")
    output_path.write_text(edited, encoding="utf-8")

    second = process_event(
        settings=app_settings,
        event=event,
        series_configs=[series_config],
        env={},
        state_store=state_store,
        provider=FakeProvider(),
        now=datetime.fromisoformat("2026-04-13T09:35:00+10:00"),
        dry_run=False,
    )

    assert second["status"] == "skipped"
    assert second["reason"] == "meeting_notes_edited"


def test_process_event_locks_after_edit_below_meeting_notes(
    monkeypatch, app_settings, series_config
) -> None:
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    state_store = StateStore(app_settings)
    monkeypatch.setattr(
        "briefing.runner.collect_sources",
        lambda settings, event, series, logger, env: [
            SourceResult(
                source_type="previous_note",
                label="Previous meeting note",
                content="No previous note found.",
                required=False,
                status="ok",
            )
        ],
    )

    result = process_event(
        settings=app_settings,
        event=event,
        series_configs=[series_config],
        env={},
        state_store=state_store,
        provider=FakeProvider(),
        now=datetime.fromisoformat("2026-04-13T09:30:00+10:00"),
        dry_run=False,
    )

    assert result["status"] == "written"
    output_path = app_settings.paths.meeting_notes_dir / "2026-04-13-1000-cas-strategy-meeting.md"
    text = output_path.read_text(encoding="utf-8")
    edited = text + "\n## Transcript Summary\n\n- Added later\n"
    output_path.write_text(edited, encoding="utf-8")

    second = process_event(
        settings=app_settings,
        event=event,
        series_configs=[series_config],
        env={},
        state_store=state_store,
        provider=FakeProvider(),
        now=datetime.fromisoformat("2026-04-13T09:35:00+10:00"),
        dry_run=False,
    )

    assert second["status"] == "skipped"
    assert second["reason"] == "meeting_notes_edited"


def test_process_event_preserves_duplicate_source_labels_in_state(
    monkeypatch, app_settings, series_config
) -> None:
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    state_store = StateStore(app_settings)
    monkeypatch.setattr(
        "briefing.runner.collect_sources",
        lambda settings, event, series, logger, env: [
            SourceResult(
                source_type="email",
                label="Emails related to CAS Strategy Meeting",
                content="First email block",
                required=False,
                status="ok",
            ),
            SourceResult(
                source_type="email",
                label="Emails related to CAS Strategy Meeting",
                content="Second email block",
                required=False,
                status="ok",
            ),
        ],
    )

    result = process_event(
        settings=app_settings,
        event=event,
        series_configs=[series_config],
        env={},
        state_store=state_store,
        provider=FakeProvider(),
        now=datetime.fromisoformat("2026-04-13T09:30:00+10:00"),
        dry_run=False,
    )

    assert result["status"] == "written"
    occurrence = state_store.load_occurrence(state_store.occurrence_key(event))
    assert occurrence is not None
    assert len(occurrence.source_hashes) == 2


def test_process_event_refreshes_existing_note_when_briefing_format_changes(
    monkeypatch, app_settings, series_config
) -> None:
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    state_store = StateStore(app_settings)
    sources = [
        SourceResult(
            source_type="slack",
            label="Slack channel general",
            content="Slack digest",
            required=False,
            status="ok",
            metadata={"empty": False},
        )
    ]
    monkeypatch.setattr(
        "briefing.runner.collect_sources",
        lambda settings, event, series, logger, env: sources,
    )

    output_path = app_settings.paths.meeting_notes_dir / "2026-04-13-1000-cas-strategy-meeting.md"
    output_path.write_text(
        "---\n"
        "title: CAS Strategy Meeting 10–11am\n"
        "series_id: cas-strategy\n"
        "start: 2026-04-13T10:00:00+10:00\n"
        "---\n\n"
        "# CAS Strategy Meeting 10–11am\n"
        "[[2026-04-13]] | [[CAS Strategy Meeting Meetings]]\n\n"
        "---\n"
        "## Briefing\n\n"
        "- Generated summary\n\n"
        "---\n"
        "## Meeting Notes\n\n"
        "- \n",
        encoding="utf-8",
    )

    occurrence_key = state_store.occurrence_key(event)
    state_store.save_occurrence(
        OccurrenceState(
            occurrence_key=occurrence_key,
            series_id=series_config.series_id,
            event_uid=event.uid,
            start_iso=event.start.isoformat(),
            output_path=str(output_path),
            summary_hash="a95a01ed49fd53388e1222d445bb9a1d1fdbfd8f3cb08d0d968ae6dc02055bbb",
            source_hashes={
                "0:slack:Slack channel general": "972d62dd33095ecfa2800f600694f2427c85e3e3fdf97b351ce861f7e48725e8"
            },
        )
    )

    result = process_event(
        settings=app_settings,
        event=event,
        series_configs=[series_config],
        env={},
        state_store=state_store,
        provider=FakeProvider(),
        now=datetime.fromisoformat("2026-04-13T09:30:00+10:00"),
        dry_run=False,
    )

    assert result["status"] == "written"
    assert "**Sources:** Slack" in output_path.read_text(encoding="utf-8")


def test_run_briefing_does_not_write_diagnostic_for_successful_empty_run(
    monkeypatch, app_settings
) -> None:
    monkeypatch.setattr("briefing.runner.load_series_configs", lambda settings: [])
    monkeypatch.setattr("briefing.runner.load_env_file", lambda path: {})
    monkeypatch.setattr("briefing.runner.EventKitClient", lambda settings: EmptyCalendar())
    monkeypatch.setattr("briefing.runner.get_provider", lambda settings: FakeProvider())

    exit_code = run_briefing(
        app_settings,
        now=datetime.fromisoformat("2026-04-13T09:30:00+10:00"),
        dry_run=False,
    )

    assert exit_code == 0
    assert list((app_settings.paths.state_dir / "runs").glob("*.json")) == []
