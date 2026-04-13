"""Series matching."""

from __future__ import annotations

from .models import MeetingEvent, SeriesConfig
from .utils import normalize_text


def match_series(event: MeetingEvent, configs: list[SeriesConfig]) -> list[SeriesConfig]:
    """Return configs that match the event."""
    return [config for config in configs if _matches_config(event, config)]


def _matches_config(event: MeetingEvent, config: SeriesConfig) -> bool:
    match = config.match
    checks: list[bool] = []

    if match.title_any:
        event_title = normalize_text(event.title)
        checks.append(any(normalize_text(title) == event_title for title in match.title_any))

    if match.attendee_emails_any:
        attendee_emails = set(event.attendee_emails)
        checks.append(bool(attendee_emails.intersection(match.attendee_emails_any)))

    if match.organizer_emails_any:
        organizer = (event.organizer_email or "").lower()
        checks.append(organizer in match.organizer_emails_any)

    if match.calendar_names_any:
        calendar_name = (event.calendar_name or "").lower()
        checks.append(calendar_name in match.calendar_names_any)

    return bool(checks) and all(checks)

