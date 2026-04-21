"""Meeting note rendering and refresh logic."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .models import MeetingEvent, SeriesConfig, SourceResult
from .settings import AppSettings
from .utils import render_template


class NoteStructureError(ValueError):
    """Raised when an existing note cannot be reconciled safely."""


def render_note(
    settings: AppSettings,
    template_text: str,
    event: MeetingEvent,
    series: SeriesConfig,
    summary_bullets: str,
    source_results: list[SourceResult],
) -> str:
    """Render a complete note from tracked template plus deterministic metadata."""
    heading = _build_heading(event)
    frontmatter = _build_frontmatter(event, series, heading)
    briefing_block = build_briefing_block(summary_bullets, source_results)
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


def refresh_note(
    settings: AppSettings,
    existing_text: str,
    event: MeetingEvent,
    series: SeriesConfig,
    summary_bullets: str,
    source_results: list[SourceResult],
) -> str:
    """Update the managed briefing section, adopting compatible manual notes when needed."""
    reconciled_note = reconcile_note_structure(settings, existing_text, event, series)
    briefing_block = build_briefing_block(summary_bullets, source_results)
    return _replace_section(reconciled_note, "Briefing", "Meeting Notes", briefing_block + "\n\n---\n")


def build_briefing_block(summary_bullets: str, source_results: list[SourceResult]) -> str:
    """Render the generated briefing block for the note template."""
    summary = normalize_summary_bullets(summary_bullets)
    sources_line = build_sources_line(source_results)
    return f"## Briefing\n\n{summary}\n\n{sources_line}"


def build_sources_line(source_results: list[SourceResult]) -> str:
    """Summarize source usage, empty sources, and source errors for the note footer."""
    used = _collect_unique_source_names(
        source_results,
        predicate=lambda source: source.status == "ok" and not _source_is_empty(source),
    )
    empty = _collect_unique_source_names(
        source_results,
        predicate=lambda source: source.status == "ok" and _source_is_empty(source),
        exclude=set(used),
    )
    errors = _collect_unique_source_names(
        source_results,
        predicate=lambda source: source.status == "error",
    )

    line = f"**Sources:** {', '.join(used) if used else 'none'}"
    details: list[str] = []
    if empty:
        details.append(f"empty: {', '.join(empty)}")
    if errors:
        details.append(f"errors: {', '.join(errors)} - please see logs")
    if details:
        line += f" ({'; '.join(details)})"
    return line


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


def _collect_unique_source_names(
    source_results: list[SourceResult],
    *,
    predicate,
    exclude: set[str] | None = None,
) -> list[str]:
    names: list[str] = []
    excluded = exclude or set()
    for source in source_results:
        if not predicate(source):
            continue
        name = _display_source_name(source)
        if name in excluded or name in names:
            continue
        names.append(name)
    return names


def _display_source_name(source: SourceResult) -> str:
    if source.source_type == "previous_note":
        return "past meeting note"
    if source.source_type == "slack":
        return "Slack"
    if source.source_type == "email":
        return "Email"
    if source.source_type == "notion":
        return source.label or "Notion"
    if source.source_type == "file":
        return source.label or "File"
    return source.label or source.source_type


def _source_is_empty(source: SourceResult) -> bool:
    empty = source.metadata.get("empty")
    if isinstance(empty, bool):
        return empty
    if source.source_type == "previous_note":
        return not bool(source.metadata.get("path"))
    return not bool(source.content.strip())


def _section_has_user_content(section_text: str) -> bool:
    """Treat empty bullet placeholders as no content for previous-note carryover."""
    return _normalize_section_value(section_text) not in {"", "-"}


def reconcile_note_structure(
    settings: AppSettings,
    note_text: str,
    event: MeetingEvent,
    series: SeriesConfig,
) -> str:
    """Ensure an existing note has the managed metadata and sections needed for refresh."""
    frontmatter, body = parse_frontmatter_for_update(note_text)
    merged_frontmatter = _merge_managed_frontmatter(frontmatter, event, series)
    reconciled_body = _reconcile_note_body(settings, body)
    return _compose_note(merged_frontmatter, reconciled_body)


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


def extract_section_to_end(note_text: str, heading: str) -> str:
    """Extract everything after a heading until the end of the note."""
    pattern = re.compile(rf"^## {re.escape(heading)}\n(?P<body>.*)\Z", re.MULTILINE | re.DOTALL)
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


def parse_frontmatter_for_update(note_text: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from the body with explicit errors for malformed notes."""
    if not note_text.startswith("---\n"):
        return {}, note_text
    try:
        _, remainder = note_text.split("---\n", 1)
        frontmatter_text, body = remainder.split("\n---\n", 1)
    except ValueError as exc:
        raise NoteStructureError("Existing note has malformed frontmatter.") from exc
    try:
        data = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise NoteStructureError("Existing note frontmatter is not valid YAML.") from exc
    if not isinstance(data, dict):
        raise NoteStructureError("Existing note frontmatter must be a mapping.")
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
    note_tail = extract_section_to_end(body, "Meeting Notes")
    title = _extract_title(body) or path.name
    parts = [f"Title: {title}"]
    if _section_has_user_content(note_tail):
        parts.append("## Meeting Notes\n" + note_tail)
    return "\n\n".join(parts)


def _merge_managed_frontmatter(
    frontmatter: dict[str, Any],
    event: MeetingEvent,
    series: SeriesConfig,
) -> dict[str, Any]:
    merged = dict(frontmatter)
    merged.update(
        {
            "title": _build_heading(event),
            "series_id": series.series_id,
            "start": event.start.isoformat(),
        }
    )
    return merged


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
    return "---\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip() + "\n---"


def _dump_frontmatter(payload: dict[str, Any]) -> str:
    return "---\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip() + "\n---"


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


def _reconcile_note_body(settings: AppSettings, body: str) -> str:
    briefing_matches = _find_heading_matches(body, "Briefing")
    meeting_notes_matches = _find_heading_matches(body, "Meeting Notes")

    if len(briefing_matches) > 1:
        raise NoteStructureError("Existing note has multiple '## Briefing' sections.")
    if len(meeting_notes_matches) > 1:
        raise NoteStructureError("Existing note has multiple '## Meeting Notes' sections.")

    if briefing_matches and meeting_notes_matches:
        if briefing_matches[0].start() > meeting_notes_matches[0].start():
            raise NoteStructureError("'## Briefing' must appear before '## Meeting Notes'.")
        return body

    if meeting_notes_matches:
        return _insert_briefing_before_meeting_notes(body, meeting_notes_matches[0].start())

    if briefing_matches:
        if _find_next_level_two_heading(body, briefing_matches[0].end()) is not None:
            raise NoteStructureError(
                "Existing note needs '## Meeting Notes' before later top-level sections."
            )
        return _append_meeting_notes_placeholder(settings, body)

    return _append_managed_sections(settings, body)


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


def _find_heading_matches(note_text: str, heading: str) -> list[re.Match[str]]:
    pattern = re.compile(rf"^## {re.escape(heading)}\n", re.MULTILINE)
    return list(pattern.finditer(note_text))


def _find_next_level_two_heading(note_text: str, start_index: int) -> re.Match[str] | None:
    pattern = re.compile(r"^## [^\n]+\n", re.MULTILINE)
    return pattern.search(note_text, start_index)


def _insert_briefing_before_meeting_notes(body: str, meeting_notes_start: int) -> str:
    prefix = body[:meeting_notes_start].rstrip("\n")
    suffix = body[meeting_notes_start:].lstrip("\n")
    injection = "---\n## Briefing\n\n- \n\n**Sources:** none\n"
    if prefix:
        return f"{prefix}\n\n{injection}\n---\n{suffix}"
    return f"{injection}\n---\n{suffix}"


def _append_meeting_notes_placeholder(settings: AppSettings, body: str) -> str:
    tail = f"---\n## Meeting Notes\n\n{settings.output.meeting_notes_placeholder}\n"
    stripped_body = body.rstrip("\n")
    if stripped_body:
        return f"{stripped_body}\n\n{tail}"
    return tail


def _append_managed_sections(settings: AppSettings, body: str) -> str:
    sections = (
        "---\n"
        "## Briefing\n\n"
        "- \n\n"
        "**Sources:** none\n\n"
        "---\n"
        "## Meeting Notes\n\n"
        f"{settings.output.meeting_notes_placeholder}\n"
    )
    stripped_body = body.rstrip("\n")
    if stripped_body:
        return f"{stripped_body}\n\n{sections}"
    return sections


def _compose_note(frontmatter: dict[str, Any], body: str) -> str:
    rendered_frontmatter = _dump_frontmatter(frontmatter)
    cleaned_body = body.lstrip("\n")
    if cleaned_body:
        return f"{rendered_frontmatter}\n\n{cleaned_body}"
    return f"{rendered_frontmatter}\n"


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
