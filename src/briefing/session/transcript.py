"""Transcript source adapter (B-14).

Reads ``transcript/transcript.txt`` first; later work can extend this to parse
``transcript.json`` for structured segments without changing the prompt shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..utils import sha256_text


class TranscriptError(Exception):
    """Raised when a transcript cannot be loaded."""

    exit_code: int = 6


class TranscriptMissing(TranscriptError):
    exit_code = 6


class TranscriptEmpty(TranscriptError):
    exit_code = 6


@dataclass(slots=True)
class Transcript:
    """Loaded transcript content plus provenance."""

    text: str
    sha256: str
    source_path: Path
    character_count: int

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def load_transcript(transcript_text_path: Path) -> Transcript:
    """Load ``transcript/transcript.txt`` and hash its contents."""
    if not transcript_text_path.exists():
        raise TranscriptMissing(f"Transcript not found: {transcript_text_path}")
    text = transcript_text_path.read_text(encoding="utf-8")
    if not text.strip():
        raise TranscriptEmpty(f"Transcript is empty: {transcript_text_path}")
    return Transcript(
        text=text,
        sha256=sha256_text(text),
        source_path=transcript_text_path,
        character_count=len(text),
    )
