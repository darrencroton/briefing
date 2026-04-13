"""Meeting note rendering and refresh logic."""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .models import MeetingEvent, SeriesConfig
from .settings import AppSettings
from .utils import ordinal, render_template


def render_note(
    settings: AppSettings,
    template_text: str,
    event: MeetingEvent,
    series: SeriesConfig,
    summary_bullets: str,
    generated_at: datetime,
) -> str:
    """Render a complete note from tracked template plus deterministic metadata."""
    frontmatter = _build_frontmatter(event, series, generated_at)
    heading = _build_heading(event)
    summary_block = build_managed_summary_block(settings, summary_bullets)
    return render_template(
        template_text,
        {
            "FRONTMATTER": frontmatter,
            "HEADING": heading,
            "SERIES_LINK": f"{series.display_name} Meeting",
            "SUMMARY_BLOCK": summary_block,
            "MEETING_NOTES_PLACEHOLDER": settings.output.meeting_notes_placeholder,
            "ACTIONS_PLACEHOLDER": settings.output.actions_placeholder,
        },
    )


def refresh_note(settings: AppSettings, existing_text: str, summary_bullets: str) -> str:
    """Update only the managed summary block."""
    summary_block = build_managed_summary_block(settings, summary_bullets)
    begin = settings.output.managed_summary_marker_begin
    end = settings.output.managed_summary_marker_end
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(existing_text):
        raise ValueError("Managed summary block not found")
    return pattern.sub(summary_block, existing_text, count=1)


def build_managed_summary_block(settings: AppSettings, summary_bullets: str) -> str:
    """Wrap the generated summary in explicit managed markers."""
    summary = normalize_summary_bullets(summary_bullets)
    begin = settings.output.managed_summary_marker_begin
    end = settings.output.managed_summary_marker_end
    return f"{begin}\n## Pre-Meeting Summary\n{summary}\n{end}"


def normalize_summary_bullets(summary_bullets: str) -> str:
    """Ensure the LLM output is a clean Markdown bullet list."""
    lines = [line.rstrip() for line in summary_bullets.splitlines() if line.strip()]
    bullets: list[str] = []
    for line in lines:
        cleaned = line.strip()
        if cleaned.startswith("- "):
            bullets.append(cleaned)
        elif cleaned.startswith("* "):
            bullets.append(f"- {cleaned[2:].strip()}")
        elif re.match(r"^\d+\.\s+", cleaned):
            bullets.append(f"- {re.sub(r'^\d+\.\s+', '', cleaned)}")
        else:
            bullets.append(f"- {cleaned}")
    if not bullets:
        bullets = ["- "]
    return "\n".join(bullets)


def note_is_locked(settings: AppSettings, note_text: str) -> tuple[bool, str | None]:
    """Determine whether user note sections have been edited."""
    if not note_text.strip():
        return False, None
    meeting_notes = extract_section(note_text, "Meeting Notes")
    actions = extract_section(note_text, "Actions")
    if _normalize_section_value(meeting_notes) != _normalize_section_value(
        settings.output.meeting_notes_placeholder
    ):
        return True, "meeting_notes_edited"
    if _normalize_section_value(actions) != _normalize_section_value(
        settings.output.actions_placeholder
    ):
        return True, "actions_edited"
    return False, None


def extract_section(note_text: str, heading: str) -> str:
    """Extract a heading body without nested Markdown parsing."""
    pattern = re.compile(
        rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(note_text)
    if not match:
        return ""
    return match.group("body").strip()


def parse_frontmatter(note_text: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from the body."""
    if not note_text.startswith("---\n"):
        return {}, note_text
    _, remainder = note_text.split("---\n", 1)
    frontmatter_text, body = remainder.split("\n---\n", 1)
    data = yaml.safe_load(frontmatter_text) or {}
    return data, body


def find_previous_note(
    settings: AppSettings,
    current_event: MeetingEvent,
    series: SeriesConfig,
) -> Path | None:
    """Find the latest prior note for the same series."""
    candidates: list[tuple[datetime, Path]] = []
    for path in sorted(settings.paths.meeting_notes_dir.glob("*.md")):
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        if frontmatter.get("series_id") != series.series_id:
            continue
        start_value = frontmatter.get("start")
        if isinstance(start_value, datetime):
            start = start_value
        elif isinstance(start_value, str):
            start = datetime.fromisoformat(start_value)
        else:
            continue
        if start >= current_event.start:
            continue
        candidates.append((start, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def summarize_previous_note(path: Path) -> str:
    """Return the high-value sections from a previous note."""
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    summary = extract_section(body, "Pre-Meeting Summary")
    meeting_notes = extract_section(body, "Meeting Notes")
    actions = extract_section(body, "Actions")
    title = frontmatter.get("title") or path.name
    parts = [f"Title: {title}"]
    if summary:
        parts.append("## Pre-Meeting Summary\n" + summary)
    if meeting_notes:
        parts.append("## Meeting Notes\n" + meeting_notes)
    if actions:
        parts.append("## Actions\n" + actions)
    return "\n\n".join(parts)


def _build_frontmatter(
    event: MeetingEvent,
    series: SeriesConfig,
    generated_at: datetime,
) -> str:
    attendees = [attendee for attendee in event.attendees if attendee.get("name") or attendee.get("email")]
    payload = {
        "title": event.title,
        "series_id": series.series_id,
        "event_uid": event.uid,
        "generated_at": generated_at.isoformat(),
        "date": event.start.date().isoformat(),
        "start": event.start.isoformat(),
        "end": event.end.isoformat() if event.end else None,
        "calendar_name": event.calendar_name,
        "location": event.location,
        "organizer_name": event.organizer_name,
        "organizer_email": event.organizer_email,
        "attendees": attendees,
    }
    return "---\n" + yaml.safe_dump(payload, sort_keys=False).strip() + "\n---"


def _build_heading(event: MeetingEvent) -> str:
    end = event.end
    time_display = _format_time_window(event.start, end)
    return (
        f"{event.title} {time_display} "
        f"{event.start.strftime('%A')} {ordinal(event.start.day)} "
        f"{event.start.strftime('%B %Y')}"
    )


def _format_time_window(start: datetime, end: datetime | None) -> str:
    def _fmt(dt: datetime, with_minutes: bool) -> str:
        if with_minutes:
            return dt.strftime("%-I:%M%p").lower()
        return dt.strftime("%-I%p").lower()

    start_has_minutes = start.minute != 0
    start_text = _fmt(start, start_has_minutes)
    if end is None:
        return start_text
    end_has_minutes = end.minute != 0
    end_text = _fmt(end, end_has_minutes)
    return f"{start_text}–{end_text}"


def _normalize_section_value(value: str) -> str:
    normalized = "\n".join(line.rstrip() for line in value.splitlines()).strip()
    return normalized
