from __future__ import annotations

from datetime import datetime

from briefing.models import MeetingEvent, SourceResult
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
    sources = [
        SourceResult(
            source_type="file",
            label="Project tracker",
            content="Open item",
            required=False,
            status="ok",
        )
    ]

    prompt = render_summary_prompt(template, event, sources, datetime.fromisoformat("2026-04-13T09:00:00+10:00"))

    assert "CAS Strategy Meeting" in prompt
    assert "=== SOURCE: Project tracker ===" in prompt
    assert "Open item" in prompt

