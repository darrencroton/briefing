"""Prompt rendering."""

from __future__ import annotations

from datetime import datetime

from .models import MeetingEvent, SeriesConfig, SourceResult
from .utils import render_template


def render_summary_prompt(
    template_text: str,
    event: MeetingEvent,
    series: SeriesConfig,
    sources: list[SourceResult],
    now: datetime,
) -> str:
    """Render the tracked prompt template."""
    meeting_context = _build_meeting_context(event, series, now)
    source_blocks = _build_source_blocks(sources)
    return render_template(
        template_text,
        {
            "MEETING_CONTEXT": meeting_context,
            "SOURCE_BLOCKS": source_blocks,
        },
    )


def _build_meeting_context(event: MeetingEvent, series: SeriesConfig, now: datetime) -> str:
    attendees = ", ".join(
        attendee.get("name") or attendee.get("email") or "Unknown"
        for attendee in event.attendees
    ) or "not specified"
    location = event.location or "not specified"
    organizer = event.organizer_name or event.organizer_email or "not specified"
    return "\n".join(
        [
            f"Generated at: {now.isoformat()}",
            f"Series display name: {series.display_name}",
            f"Series note slug: {series.note_slug}",
            f"Series ID: {series.series_id}",
            f"Title: {event.title}",
            f"Start: {event.start.isoformat()}",
            f"End: {event.end.isoformat() if event.end else 'not specified'}",
            f"Calendar: {event.calendar_name or 'not specified'}",
            f"Organizer: {organizer}",
            f"Attendees: {attendees}",
            f"Location: {location}",
            f"Event notes: {event.notes or 'not specified'}",
        ]
    )


def _build_source_blocks(sources: list[SourceResult]) -> str:
    if not sources:
        return "No usable sources were collected."
    blocks = []
    for source in sources:
        blocks.append(f"=== SOURCE: {source.label} ===\n{source.content}\n=== END SOURCE ===")
    return "\n\n".join(blocks)
