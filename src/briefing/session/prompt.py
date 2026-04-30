"""Post-meeting prompt rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..utils import render_template
from .completion import Completion
from .loader import Manifest
from .transcript import Transcript


@dataclass(slots=True)
class PromptInputs:
    """Everything the post-meeting prompt template consumes."""

    manifest: Manifest
    completion: Completion
    transcript: Transcript
    meeting_note_context: str = "not available"


def render_post_meeting_prompt(template_text: str, inputs: PromptInputs) -> str:
    """Render the tracked post-meeting prompt template."""
    return render_template(
        template_text,
        {
            "MEETING_CONTEXT": _build_meeting_context(inputs.manifest, inputs.completion),
            "PARTICIPANTS": _build_participants_block(inputs.manifest),
            "WARNINGS": _build_warnings(inputs.completion),
            "TRANSCRIPT": inputs.transcript.text.strip(),
            "ATTRIBUTION_POLICY": _build_attribution_policy(inputs.completion, inputs.manifest),
            "MEETING_NOTE": inputs.meeting_note_context.strip() or "not available",
        },
    )


def load_meeting_note_context(note_path: Path) -> str:
    """Load the current meeting note as post-meeting context.

    Existing generated summaries are excluded so reprocess does not feed the
    previous `## Meeting Summary` back into the next summary generation.
    """
    if not note_path.exists():
        return "not available"
    try:
        note_text = note_path.read_text(encoding="utf-8")
    except OSError:
        return "not available"
    return _remove_existing_summary(note_text).strip() or "not available"


_SUMMARY_HEADING_PATTERN = re.compile(r"^## Meeting Summary\n", re.MULTILINE)
_NEXT_HEADING_PATTERN = re.compile(r"^## [^\n]+\n", re.MULTILINE)


def _remove_existing_summary(note_text: str) -> str:
    """Remove the existing managed summary block from prompt context, if present."""
    matches = list(_SUMMARY_HEADING_PATTERN.finditer(note_text))
    if not matches:
        return note_text
    heading = matches[-1]
    start = _include_immediate_divider(note_text, heading.start())
    next_heading = _NEXT_HEADING_PATTERN.search(note_text, heading.end())
    end = next_heading.start() if next_heading else len(note_text)
    return note_text[:start] + note_text[end:]


def _include_immediate_divider(note_text: str, heading_start: int) -> int:
    divider_start = heading_start - len("---\n")
    if divider_start >= 0 and note_text[divider_start:heading_start] == "---\n":
        return divider_start
    divider_start = heading_start - len("\n---\n")
    if divider_start >= 0 and note_text[divider_start:heading_start] == "\n---\n":
        return divider_start
    return heading_start


def _build_meeting_context(manifest: Manifest, completion: Completion) -> str:
    meeting = manifest.meeting
    lines = [
        f"Title: {manifest.title or '(untitled)'}",
        f"Start: {meeting.get('start_time', 'not specified')}",
        f"Scheduled end: {meeting.get('scheduled_end_time') or 'not specified'}",
        f"Timezone: {meeting.get('timezone', 'not specified')}",
        f"Location: {meeting.get('location') or 'not specified'}",
        f"Location type: {meeting.get('location_type') or 'not specified'}",
        f"Series id: {manifest.series_id or 'ad-hoc'}",
        f"Session id: {manifest.session_id}",
        f"Terminal status: {completion.terminal_status}",
        f"Stop reason: {completion.stop_reason}",
        f"Diarization available: {'yes' if completion.diarization_ok else 'no'}",
    ]
    return "\n".join(lines)


def _build_participants_block(manifest: Manifest) -> str:
    host = manifest.host_name or "not specified"
    names = manifest.participant_names
    expected = manifest.participants.get("attendees_expected")
    lines = [f"Host: {host}"]
    if expected:
        lines.append(f"Expected attendees: {expected}")
    if names:
        lines.append("Participant hints: " + ", ".join(names))
    else:
        lines.append("Participant hints: none provided")
    return "\n".join(lines)


def _build_warnings(completion: Completion) -> str:
    parts: list[str] = []
    if completion.warnings:
        parts.append(", ".join(completion.warnings))
    if completion.errors:
        parts.append("errors: " + ", ".join(completion.errors))
    if not parts:
        return "none"
    return "; ".join(parts)


def _build_attribution_policy(completion: Completion, manifest: Manifest) -> str:
    if completion.diarization_ok and manifest.participant_names:
        return (
            "Diarization produced speaker labels. Use the hinted participant names when a speaker "
            "label consistently aligns with one, otherwise use speaker-agnostic phrasing."
        )
    return (
        "Diarization did not produce reliable labels. Attribute statements speaker-agnostically "
        "(for example, 'someone noted', 'the team agreed') unless the transcript text itself "
        "names the speaker."
    )
