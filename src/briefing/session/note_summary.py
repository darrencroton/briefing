"""Managed post-meeting `## Meeting Summary` section writer.

Guardrail 6: user content in the Obsidian note must be byte-identical across
rewrites. The visible ``## Meeting Summary`` heading is the managed boundary;
re-ingest replaces that section and leaves all surrounding bytes unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..notes import NoteStructureError
from ..utils import render_template
from .loader import Manifest


SUMMARY_HEADING = "## Meeting Summary"

_MEETING_NOTES_PATTERN = re.compile(r"^## Meeting Notes\n", re.MULTILINE)
_NEXT_HEADING_PATTERN = re.compile(r"^## [^\n]+\n", re.MULTILINE)
_SUMMARY_HEADING_PATTERN = re.compile(r"^## Meeting Summary\n", re.MULTILINE)


@dataclass(slots=True)
class NoteWriteResult:
    """Outcome of a managed-summary note write."""

    note_path: Path
    note_created: bool
    block_replaced: bool
    block_written: bool


@dataclass(frozen=True, slots=True)
class MissingNoteTemplate:
    """Configured note-template inputs for safe missing-note creation."""

    template_text: str
    meeting_notes_placeholder: str


def write_summary_block(
    note_path: Path,
    manifest: Manifest,
    summary_body: str,
    *,
    session_id: str,
    transcript_sha256: str,
    missing_note_template: MissingNoteTemplate | None = None,
) -> NoteWriteResult:
    """Create or update the managed `## Meeting Summary` section in the note.

    - If the note does not exist, renders the configured meeting-note template
      from the manifest and appends the managed section.
    - If the note exists with a `## Meeting Notes` section, appends the section
      to the end of the note.
    - If a managed section is already present, replaces only that section and
      appends the new version to the end.
    """
    block = _render_managed_block(
        summary_body=summary_body,
    )
    _ = (session_id, transcript_sha256)

    if not note_path.exists():
        if missing_note_template is None:
            raise NoteStructureError(
                f"Missing note at {note_path} requires the configured note template before "
                "a post-meeting summary can be inserted."
            )
        base_note = _render_missing_note_from_template(manifest, missing_note_template)
        note_text = _append_summary_section(base_note, block)
        _write_note(note_path, note_text)
        return NoteWriteResult(
            note_path=note_path,
            note_created=True,
            block_replaced=False,
            block_written=True,
        )

    existing_text = note_path.read_text(encoding="utf-8")
    summary_range = _find_summary_section(existing_text)
    if summary_range:
        body_without_summary = (
            existing_text[: summary_range[0]]
            + existing_text[summary_range[1] :]
        )
        new_text = _append_summary_section(body_without_summary, block)
        if new_text == existing_text:
            return NoteWriteResult(
                note_path=note_path,
                note_created=False,
                block_replaced=False,
                block_written=False,
            )
        _write_note(note_path, new_text)
        return NoteWriteResult(
            note_path=note_path,
            note_created=False,
            block_replaced=True,
            block_written=True,
        )

    meeting_notes = _MEETING_NOTES_PATTERN.search(existing_text)
    if not meeting_notes:
        raise NoteStructureError(
            f"Existing note at {note_path} has no '## Meeting Notes' section; "
            "cannot safely insert a post-meeting summary."
        )

    new_text = _append_summary_section(existing_text, block)
    _write_note(note_path, new_text)
    return NoteWriteResult(
        note_path=note_path,
        note_created=False,
        block_replaced=False,
        block_written=True,
    )


def _append_summary_section(note_text: str, block: str) -> str:
    return note_text + _prefix_separator(note_text) + block + "\n"


def _prefix_separator(prefix: str) -> str:
    if not prefix:
        return ""
    if prefix.endswith("\n\n"):
        return ""
    if prefix.endswith("\n"):
        return "\n"
    return "\n\n"


def _render_managed_block(
    *,
    summary_body: str,
) -> str:
    normalised = summary_body.strip("\n")
    return (
        "---\n"
        f"{SUMMARY_HEADING}\n\n"
        f"{normalised}"
    )


def _find_summary_section(note_text: str) -> tuple[int, int] | None:
    """Return the visible managed-summary section range, if present."""
    matches = list(_SUMMARY_HEADING_PATTERN.finditer(note_text))
    if not matches:
        return None
    heading = matches[-1]
    start = _include_immediate_divider(note_text, heading.start())
    next_heading = _NEXT_HEADING_PATTERN.search(note_text, heading.end())
    if next_heading:
        return (start, next_heading.start())
    return (start, len(note_text))


def _include_immediate_divider(note_text: str, heading_start: int) -> int:
    divider_start = heading_start - len("---\n")
    if divider_start >= 0 and note_text[divider_start:heading_start] == "---\n":
        return divider_start
    divider_start = heading_start - len("\n---\n")
    if divider_start >= 0 and note_text[divider_start:heading_start] == "\n---\n":
        return divider_start
    return heading_start


def _render_missing_note_from_template(
    manifest: Manifest,
    missing_note_template: MissingNoteTemplate,
) -> str:
    return render_template(
        missing_note_template.template_text,
        {
            "FRONTMATTER": _build_missing_note_frontmatter(manifest),
            "HEADING": manifest.title or manifest.session_id,
            "DATE_LINK": _meeting_date_link(manifest),
            "SERIES_LINK": _series_link(manifest),
            "BRIEFING_BLOCK": "## Briefing\n\n- \n\n**Sources:** none",
            "MEETING_NOTES_PLACEHOLDER": missing_note_template.meeting_notes_placeholder,
        },
    )


def _build_missing_note_frontmatter(manifest: Manifest) -> str:
    frontmatter_lines = [
        "---",
        f"title: {_escape_yaml_scalar(manifest.title or manifest.session_id)}",
        f"session_id: {_escape_yaml_scalar(manifest.session_id)}",
    ]
    if manifest.series_id:
        frontmatter_lines.append(f"series_id: {_escape_yaml_scalar(manifest.series_id)}")
    start_time = manifest.meeting.get("start_time")
    if start_time:
        frontmatter_lines.append(f"start: {start_time}")
    frontmatter_lines.append("---")
    return "\n".join(frontmatter_lines)


def _meeting_date_link(manifest: Manifest) -> str:
    start_time = str(manifest.meeting.get("start_time") or "").strip()
    if "T" in start_time:
        return start_time.split("T", 1)[0]
    return start_time[:10] if len(start_time) >= 10 else manifest.session_id


def _series_link(manifest: Manifest) -> str:
    if manifest.series_id:
        return f"{manifest.series_id} Meetings"
    return "Ad Hoc Meetings"


def _escape_yaml_scalar(value: str) -> str:
    """Quote YAML scalar values that could otherwise be misparsed."""
    if value == "" or any(ch in value for ch in (":", "#", '"')) or value.startswith("-"):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _write_note(note_path: Path, text: str) -> None:
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(text, encoding="utf-8")
