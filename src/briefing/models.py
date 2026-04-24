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
    dm_conversation_ids: list[str] = field(default_factory=list)
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
class EmailSourceConfig:
    """Apple Mail email source configuration."""

    email_addresses: list[str] = field(default_factory=list)
    account: str | None = None
    mailboxes: list[str] = field(default_factory=list)
    subject_regex_any: list[str] = field(default_factory=list)
    history_days: int | None = None
    max_messages: int | None = None
    max_characters: int | None = None
    required: bool = False


@dataclass(slots=True)
class SeriesSources:
    """Configured sources for a meeting series."""

    slack: SlackSourceConfig | None = None
    notion: list[NotionSourceConfig] = field(default_factory=list)
    files: list[FileSourceConfig] = field(default_factory=list)
    emails: list[EmailSourceConfig] = field(default_factory=list)


@dataclass(slots=True)
class RecordingPolicyConfig:
    """Optional recording policy overrides for a series or calendar marker."""

    auto_start: bool | None = None
    auto_stop: bool | None = None
    default_extension_minutes: int | None = None
    max_single_extension_minutes: int | None = None
    pre_end_prompt_minutes: int | None = None
    no_interaction_grace_minutes: int | None = None


@dataclass(slots=True)
class RecordingConfig:
    """Meeting Intelligence recording metadata."""

    record: bool | None = None
    mode: str | None = None
    audio_strategy: str | None = None
    host_name: str | None = None
    attendees_expected: int | None = None
    participant_names: list[str] = field(default_factory=list)
    names_are_hints_only: bool = True
    language: str | None = None
    asr_backend: str | None = None
    diarization_enabled: bool | None = None
    speaker_count_hint: int | None = None
    note_dir: str | None = None
    note_slug: str | None = None
    recording_policy: RecordingPolicyConfig = field(default_factory=RecordingPolicyConfig)


@dataclass(slots=True)
class SeriesConfig:
    """A meeting series definition."""

    path: Path
    series_id: str
    display_name: str
    note_slug: str
    match: MatchRules
    sources: SeriesSources = field(default_factory=SeriesSources)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
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


@dataclass(slots=True)
class SessionPlanState:
    """Stored state for one planned recording session."""

    occurrence_key: str
    event_uid: str
    start_iso: str
    title: str
    session_id: str
    manifest_path: str
    session_dir: str
    note_path: str
    status: str = "planned"
    planned_at: str | None = None
    launched_at: str | None = None
    launch_exit_code: int | None = None
    invalidated_at: str | None = None
    invalidation_reason: str | None = None
