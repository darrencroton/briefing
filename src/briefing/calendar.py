"""Apple Calendar access through EventKit."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from .models import MeetingEvent
from .settings import AppSettings

# Stable public constant from EventKit — safe to inline since the value
# is part of Apple's C enum and has never changed.  Avoids importing the
# framework at module level (which fails on non-macOS).
_EK_ENTITY_TYPE_EVENT = 0  # EventKit.EKEntityTypeEvent


class CalendarError(RuntimeError):
    """Raised when EventKit access fails."""


def _python_str(value) -> str | None:
    """Convert Objective-C string-like values into plain Python strings."""
    if value is None:
        return None
    return str(value)


def _get_event_store():
    """Create and return an EKEventStore instance.

    Isolated for testability -- tests can monkeypatch this function to
    avoid hitting the real EventKit framework.
    """
    import EventKit  # pyobjc-framework-EventKit

    return EventKit.EKEventStore.alloc().init()


def _request_access(store) -> None:
    """Request calendar access synchronously.

    On macOS 14+ this uses ``requestFullAccessToEventsWithCompletion_``.
    On older releases it falls back to
    ``requestAccessToEntityType_completion_``.
    """
    import EventKit

    granted = False
    error_ref = None
    done = False

    def _callback(ok, err):
        nonlocal granted, error_ref, done
        granted = ok
        error_ref = err
        done = True

    # macOS 14 (Sonoma) introduced requestFullAccessToEventsWithCompletion_.
    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(_callback)
    else:
        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeEvent, _callback
        )

    # The callback may require the main runloop to continue processing while
    # the user responds to the system permission prompt.  Wait until the
    # completion callback reports the result.
    if not done:
        from Foundation import NSRunLoop, NSDate

        while not done:
            NSRunLoop.currentRunLoop().runMode_beforeDate_(
                "kCFRunLoopDefaultMode",
                NSDate.dateWithTimeIntervalSinceNow_(0.1),
            )

    if not granted:
        detail = str(error_ref) if error_ref else "denied or restricted"
        raise CalendarError(
            f"Calendar access not granted: {detail}. "
            "Open System Settings > Privacy & Security > Calendars and enable access."
        )


def _ns_date(dt: datetime):
    """Convert a Python datetime to an NSDate."""
    from Foundation import NSDate

    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _ekevent_to_meeting(event) -> MeetingEvent | None:
    """Map an EKEvent to a MeetingEvent."""
    # eventIdentifier() is Apple's recommended persistent identifier for
    # events.  calendarItemExternalIdentifier (the iCalendar UID) can be
    # nil for some providers and is not guaranteed unique across stores.
    uid = _python_str(event.eventIdentifier())
    title = _python_str(event.title()) or ""
    if not uid or not title:
        return None

    start_ns = event.startDate()
    end_ns = event.endDate()
    start = datetime.fromtimestamp(start_ns.timeIntervalSince1970()).astimezone() if start_ns else None
    end = datetime.fromtimestamp(end_ns.timeIntervalSince1970()).astimezone() if end_ns else None
    if start is None:
        return None

    calendar_name = None
    ek_calendar = event.calendar()
    if ek_calendar:
        calendar_name = _python_str(ek_calendar.title())

    organizer_name = None
    organizer_email = None
    ek_organizer = event.organizer()
    if ek_organizer:
        organizer_name = _python_str(ek_organizer.name()) or None
        url = ek_organizer.URL()
        if url:
            resource = url.resourceSpecifier()
            if resource and resource.startswith("//"):
                organizer_email = str(resource[2:]).lower()
            elif resource:
                organizer_email = str(resource).lower()

    attendees: list[dict[str, str]] = []
    ek_attendees = event.attendees() or []
    for participant in ek_attendees:
        name = _python_str(participant.name()) or ""
        email = ""
        p_url = participant.URL()
        if p_url:
            resource = p_url.resourceSpecifier()
            if resource and resource.startswith("//"):
                email = str(resource[2:]).lower()
            elif resource:
                email = str(resource).lower()
        if name or email:
            attendees.append({"name": name, "email": email})

    location = _python_str(event.location()) or None
    notes = _python_str(event.notes()) or None
    url_value = None
    ek_url = event.URL()
    if ek_url:
        url_value = str(ek_url)

    return MeetingEvent(
        uid=uid,
        title=title,
        start=start,
        end=end,
        calendar_name=calendar_name,
        organizer_name=organizer_name,
        organizer_email=organizer_email,
        location=location,
        notes=notes,
        url=url_value,
        attendees=attendees,
        raw={},
    )


class EventKitClient:
    """Calendar client using Apple EventKit framework."""

    def __init__(self, settings: AppSettings):
        self.settings = settings

    def _get_calendars(self, store):
        """Resolve the calendar objects to query based on include/exclude settings."""
        all_calendars = store.calendarsForEntityType_(_EK_ENTITY_TYPE_EVENT)
        include = {name.lower() for name in self.settings.calendar.include_calendar_names}
        exclude = {name.lower() for name in self.settings.calendar.exclude_calendar_names}

        if not include and not exclude:
            # None means "all calendars" in the EventKit predicate.
            return None

        calendars = list(all_calendars)
        if include:
            calendars = [c for c in calendars if (c.title() or "").lower() in include]
        if exclude:
            calendars = [c for c in calendars if (c.title() or "").lower() not in exclude]
        return calendars

    def fetch_events(self, start: datetime, end: datetime) -> list[MeetingEvent]:
        """Fetch events in a specific window."""
        store = _get_event_store()
        _request_access(store)
        calendars = self._get_calendars(store)
        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            _ns_date(start), _ns_date(end), calendars
        )
        ek_events = store.eventsMatchingPredicate_(predicate)

        events: list[MeetingEvent] = []
        for ek_event in ek_events or []:
            if not self.settings.calendar.include_all_day and ek_event.isAllDay():
                continue
            meeting = _ekevent_to_meeting(ek_event)
            if meeting is not None:
                events.append(meeting)
        return events

    def fetch_upcoming(self, now: datetime) -> list[MeetingEvent]:
        """Fetch upcoming candidate meetings."""
        window_start = now + timedelta(minutes=self.settings.calendar.window_min_minutes)
        window_end = now + timedelta(minutes=self.settings.calendar.window_max_minutes)
        return [
            event
            for event in self.fetch_events(window_start, window_end)
            if event.start >= window_start and event.start <= window_end
        ]

    def validate_access(self) -> tuple[bool, str]:
        """Check that EventKit can access the Calendar store."""
        try:
            store = _get_event_store()
            _request_access(store)
            return True, "EventKit calendar access granted"
        except CalendarError as exc:
            return False, str(exc)
        except ImportError:
            if sys.platform != "darwin":
                return False, "EventKit requires macOS"
            return False, (
                "pyobjc-framework-EventKit is not installed. "
                "Run: uv sync"
            )
        except Exception as exc:
            return False, f"EventKit access check failed: {exc}"
