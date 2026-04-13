"""Previous-note source adapter."""

from __future__ import annotations

from .types import SourceContext
from ..models import SourceResult
from ..notes import find_previous_note, summarize_previous_note
from ..utils import shorten_text


def collect_previous_note(context: SourceContext) -> SourceResult:
    """Collect the most recent prior note for the same series."""
    path = find_previous_note(context.settings, context.event, context.series)
    if path is None:
        return SourceResult(
            source_type="previous_note",
            label="Previous meeting note",
            content="No previous meeting note was found for this series.",
            required=False,
            status="ok",
            metadata={},
        )
    content, truncated = shorten_text(
        summarize_previous_note(path),
        context.settings.files.max_characters,
    )
    return SourceResult(
        source_type="previous_note",
        label="Previous meeting note",
        content=content,
        required=False,
        status="ok",
        truncated=truncated,
        metadata={"path": str(path)},
    )

