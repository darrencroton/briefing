from __future__ import annotations

from datetime import datetime

from briefing.llm import LLMResponse
from briefing.models import MeetingEvent, SourceResult
from briefing.runner import process_event
from briefing.state import StateStore


class FakeProvider:
    def generate(self, prompt: str) -> LLMResponse:
        assert "Sources:" in prompt
        return LLMResponse(text="- Generated summary", raw='{"result":"- Generated summary"}')


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

    edited = text.replace("## Meeting Notes\n- ", "## Meeting Notes\n- User wrote notes")
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

