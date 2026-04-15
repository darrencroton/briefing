from __future__ import annotations

from datetime import datetime

from briefing.models import MatchRules, MeetingEvent, SeriesConfig, SeriesSources, SourceResult
from briefing.prompts import render_summary_prompt


def test_render_summary_prompt_includes_context_and_sources() -> None:
    template = "CTX\n{{MEETING_CONTEXT}}\nSRC\n{{SOURCE_BLOCKS}}\n"
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    series = SeriesConfig(
        path=__file__,
        series_id="cas-strategy",
        display_name="CAS Strategy Meeting",
        note_slug="cas-strategy-meeting",
        match=MatchRules(title_any=["CAS Strategy Meeting"]),
        sources=SeriesSources(),
    )
    sources = [
        SourceResult(
            source_type="file",
            label="Project tracker",
            content="Open item",
            required=False,
            status="ok",
        )
    ]

    prompt = render_summary_prompt(
        template,
        event,
        series,
        sources,
        datetime.fromisoformat("2026-04-13T09:00:00+10:00"),
    )

    assert "CAS Strategy Meeting" in prompt
    assert "Series note slug: cas-strategy-meeting" in prompt
    assert "Series ID: cas-strategy" in prompt
    assert "=== SOURCE: Project tracker ===" in prompt
    assert "Open item" in prompt
