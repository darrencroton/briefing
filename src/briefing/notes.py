"""Meeting note rendering and refresh logic."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .models import MeetingEvent, SeriesConfig
from .settings import AppSettings
from .utils import render_template


def render_note(
    settings: AppSettings,
    template_text: str,
    event: MeetingEvent,
    series: SeriesConfig,
    summary_bullets: str,
) -> str:
    """Render a complete note from tracked template plus deterministic metadata."""
    heading = _build_heading(event)
    frontmatter = _build_frontmatter(event, series, heading)
    briefing_block = build_briefing_block(summary_bullets)
    return render_template(
        template_text,
        {
            "FRONTMATTER": frontmatter,
            "HEADING": heading,
            "DATE_LINK": event.start.date().isoformat(),
            "SERIES_LINK": f"{series.display_name} Meetings",
            "BRIEFING_BLOCK": briefing_block,
            "MEETING_NOTES_PLACEHOLDER": settings.output.meeting_notes_placeholder,
        },
    )


def refresh_note(existing_text: str, summary_bullets: str) -> str:
    """Update only the managed briefing section."""
    briefing_block = build_briefing_block(summary_bullets)
    return _replace_section(existing_text, "Briefing", "Meeting Notes", briefing_block + "\n\n---\n")


def build_briefing_block(summary_bullets: str) -> str:
    """Render the generated briefing block for the note template."""
    summary = normalize_summary_bullets(summary_bullets)
    return f"## Briefing\n\n{summary}"


def normalize_summary_bullets(summary_bullets: str) -> str:
    """Ensure the LLM output is a clean Markdown bullet list, preserving group spacing."""
    bullets: list[str] = []
    for raw_line in summary_bullets.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if bullets and bullets[-1] != "":
                bullets.append("")
            continue

        cleaned = _strip_slack_channel_hashes(line.strip())
        if cleaned.startswith("- "):
            bullets.append(cleaned)
        elif cleaned.startswith("* "):
            bullets.append(f"- {cleaned[2:].strip()}")
        elif re.match(r"^\d+\.\s+", cleaned):
            bullets.append(f"- {re.sub(r'^\d+\.\s+', '', cleaned)}")
        else:
            bullets.append(f"- {cleaned}")

    while bullets and bullets[-1] == "":
        bullets.pop()
    if not bullets:
        bullets = ["- "]
    return "\n".join(bullets)


def _strip_slack_channel_hashes(text: str) -> str:
    """Remove leading hashes from channel-style tokens so Obsidian does not treat them as tags."""
    return re.sub(
        r"(^|[\s(])#([a-z][a-z0-9._-]*)(?=$|[\s),.:;!?])",
        lambda match: f"{match.group(1)}{match.group(2)}",
        text,
    )


def _section_has_user_content(section_text: str) -> bool:
    """Treat empty bullet placeholders as no content for previous-note carryover."""
    return _normalize_section_value(section_text) not in {"", "-"}


def note_is_locked(settings: AppSettings, note_text: str) -> tuple[bool, str | None]:
    """Determine whether user note sections have been edited."""
    if not note_text.strip():
        return False, None
    meeting_notes = extract_section(note_text, "Meeting Notes")
    if _normalize_section_value(meeting_notes) != _normalize_section_value(
        settings.output.meeting_notes_placeholder
    ):
        return True, "meeting_notes_edited"
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
        start = _parse_frontmatter_start(frontmatter.get("start"))
        if start is None:
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
    _, body = parse_frontmatter(text)
    summary = extract_section(body, "Briefing")
    meeting_notes = extract_section(body, "Meeting Notes")
    title = _extract_title(body) or path.name
    parts = [f"Title: {title}"]
    if summary:
        parts.append("## Briefing\n" + summary)
    if _section_has_user_content(meeting_notes):
        parts.append("## Meeting Notes\n" + meeting_notes)
    return "\n\n".join(parts)


def _build_frontmatter(
    event: MeetingEvent,
    series: SeriesConfig,
    title: str,
) -> str:
    payload = {
        "title": title,
        "series_id": series.series_id,
        "start": event.start.isoformat(),
    }
    return "---\n" + yaml.safe_dump(payload, sort_keys=False).strip() + "\n---"


def _build_heading(event: MeetingEvent) -> str:
    end = event.end
    time_display = _format_time_window(event.start, end)
    return f"{event.title} {time_display}"


def _format_time_window(start: datetime, end: datetime | None) -> str:
    def _fmt(dt: datetime, with_minutes: bool, include_meridiem: bool) -> str:
        if with_minutes:
            base = dt.strftime("%-I:%M")
        else:
            base = dt.strftime("%-I")
        if include_meridiem:
            return f"{base}{dt.strftime('%p').lower()}"
        return base

    start_has_minutes = start.minute != 0
    start_meridiem = start.strftime("%p").lower()
    start_text = _fmt(start, start_has_minutes, True)
    if end is None:
        return start_text
    end_has_minutes = end.minute != 0
    end_meridiem = end.strftime("%p").lower()
    show_start_meridiem = start_meridiem != end_meridiem
    start_text = _fmt(start, start_has_minutes, show_start_meridiem)
    end_text = _fmt(end, end_has_minutes, True)
    return f"{start_text}–{end_text}"


def _normalize_section_value(value: str) -> str:
    normalized = "\n".join(line.rstrip() for line in value.splitlines()).strip()
    return normalized


def _replace_section(
    note_text: str,
    start_heading: str,
    end_heading: str,
    replacement: str,
) -> str:
    start_pattern = re.compile(rf"^## {re.escape(start_heading)}\n", re.MULTILINE)
    end_pattern = re.compile(rf"^## {re.escape(end_heading)}\n", re.MULTILINE)
    start_match = start_pattern.search(note_text)
    if not start_match:
        raise ValueError(f"Section heading not found: {start_heading}")
    end_match = end_pattern.search(note_text, start_match.end())
    if not end_match:
        raise ValueError(f"Section heading not found: {end_heading}")
    return note_text[: start_match.start()] + replacement + note_text[end_match.start() :]


def _parse_frontmatter_start(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _extract_title(body: str) -> str | None:
    match = re.search(r"^# (?P<title>.+)$", body, re.MULTILINE)
    if not match:
        return None
    heading = match.group("title").strip()
    return re.sub(
        r"\s+\d{1,2}(?::\d{2})?(?:am|pm)?[–-]\d{1,2}(?::\d{2})?(?:am|pm)\s*$",
        "",
        heading,
        flags=re.IGNORECASE,
    )
