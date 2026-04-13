"""Domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MeetingEvent:
    """Calendar event ready for matching and note generation."""

    uid: str
    title: str
    start: datetime
    end: datetime | None
    calendar_name: str | None
    organizer_name: str | None = None
    organizer_email: str | None = None
    location: str | None = None
    notes: str | None = None
    url: str | None = None
    attendees: list[dict[str, str]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def attendee_emails(self) -> list[str]:
        """Return normalized attendee emails."""
        emails = []
        for attendee in self.attendees:
            email = attendee.get("email")
            if email:
                emails.append(email.lower())
        return emails


@dataclass(slots=True)
class MatchRules:
    """Series matching rules."""

    title_any: list[str] = field(default_factory=list)
    attendee_emails_any: list[str] = field(default_factory=list)
    organizer_emails_any: list[str] = field(default_factory=list)
    calendar_names_any: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SlackSourceConfig:
    """Slack series configuration."""

    channel_refs: list[str] = field(default_factory=list)
    dm_user_ids: list[str] = field(default_factory=list)
    required: bool = False
    history_days: int | None = None
    max_characters: int | None = None


@dataclass(slots=True)
class NotionSourceConfig:
    """Notion source configuration."""

    label: str
    page_id: str
    required: bool = False
    max_characters: int | None = None


@dataclass(slots=True)
class FileSourceConfig:
    """Local file source configuration."""

    label: str
    path: str
    required: bool = False
    max_characters: int | None = None


@dataclass(slots=True)
class SeriesSources:
    """Configured sources for a meeting series."""

    slack: SlackSourceConfig | None = None
    notion: list[NotionSourceConfig] = field(default_factory=list)
    files: list[FileSourceConfig] = field(default_factory=list)


@dataclass(slots=True)
class SeriesConfig:
    """A meeting series definition."""

    path: Path
    series_id: str
    display_name: str
    note_slug: str
    match: MatchRules
    sources: SeriesSources = field(default_factory=SeriesSources)
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SourceResult:
    """The normalized output contract for all sources."""

    source_type: str
    label: str
    content: str
    required: bool
    status: str
    truncated: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether the source returned usable content."""
        return self.status == "ok"


@dataclass(slots=True)
class OccurrenceState:
    """Stored state for one meeting occurrence."""

    occurrence_key: str
    series_id: str
    event_uid: str
    start_iso: str
    output_path: str
    locked: bool = False
    lock_reason: str | None = None
    last_status: str = "pending"
    source_hashes: dict[str, str] = field(default_factory=dict)
    summary_hash: str | None = None
    last_generated_at: str | None = None
    last_error: str | None = None


@dataclass(slots=True)
class ValidationMessage:
    """Validation result item."""

    level: str
    code: str
    message: str

