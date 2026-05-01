from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from briefing.calendar import EventKitClient, _ekevent_to_meeting


class FakeNSString:
    def __init__(self, value: str):
        self.value = value

    def __bool__(self) -> bool:
        return bool(self.value)

    def __str__(self) -> str:
        return self.value


def _make_ns_date(dt: datetime):
    """Create a fake NSDate-like object from a datetime."""
    return SimpleNamespace(timeIntervalSince1970=lambda: dt.timestamp())


def _make_url(email: str):
    """Create a fake NSURL-like object with a mailto resource specifier."""
    return SimpleNamespace(resourceSpecifier=lambda: f"//{email}")


def _make_participant(name: str, email: str):
    return SimpleNamespace(
        name=lambda: name,
        URL=lambda: _make_url(email) if email else None,
    )


def _make_ek_event(
    *,
    uid: str = "event-123",
    title: str = "CAS Strategy Meeting",
    start: datetime | None = None,
    end: datetime | None = None,
    calendar_title: str = "Work",
    organizer_name: str | None = "Barry",
    organizer_email: str | None = "barry@example.edu",
    attendees: list[tuple[str, str]] | None = None,
    location: str | None = "Building A",
    notes: str | None = "Discuss staffing and budget.",
    url: str | None = None,
    is_all_day: bool = False,
):
    tz = timezone(timedelta(hours=10))
    if start is None:
        start = datetime(2026, 4, 13, 10, 0, tzinfo=tz)
    if end is None:
        end = datetime(2026, 4, 13, 11, 0, tzinfo=tz)
    if attendees is None:
        attendees = [("Darren", "darren@example.edu"), ("Barry", "barry@example.edu")]

    organizer = None
    if organizer_name or organizer_email:
        organizer = SimpleNamespace(
            name=lambda: organizer_name,
            URL=lambda: _make_url(organizer_email) if organizer_email else None,
        )

    ek_attendees = [_make_participant(name, email) for name, email in attendees]

    ek_calendar = SimpleNamespace(title=lambda: calendar_title) if calendar_title else None
    ek_url = type("FakeURL", (), {"__str__": lambda self: url})() if url else None

    return SimpleNamespace(
        eventIdentifier=lambda: uid,
        title=lambda: title,
        startDate=lambda: _make_ns_date(start),
        endDate=lambda: _make_ns_date(end) if end else None,
        calendar=lambda: ek_calendar,
        organizer=lambda: organizer,
        attendees=lambda: ek_attendees,
        location=lambda: location,
        notes=lambda: notes,
        URL=lambda: ek_url,
        isAllDay=lambda: is_all_day,
    )


def test_ekevent_to_meeting_extracts_expected_fields() -> None:
    ek_event = _make_ek_event()
    event = _ekevent_to_meeting(ek_event)

    assert event is not None
    assert event.uid == "event-123"
    assert event.title == "CAS Strategy Meeting"
    assert event.calendar_name == "Work"
    assert event.organizer_email == "barry@example.edu"
    assert event.attendee_emails == ["darren@example.edu", "barry@example.edu"]
    assert event.location == "Building A"


def test_ekevent_to_meeting_handles_missing_organizer() -> None:
    ek_event = _make_ek_event(organizer_name=None, organizer_email=None)
    # Override organizer to return None
    ek_event.organizer = lambda: None
    event = _ekevent_to_meeting(ek_event)

    assert event is not None
    assert event.organizer_name is None
    assert event.organizer_email is None


def test_ekevent_to_meeting_handles_no_attendees() -> None:
    ek_event = _make_ek_event(attendees=[])
    event = _ekevent_to_meeting(ek_event)

    assert event is not None
    assert event.attendees == []
    assert event.attendee_emails == []


def test_ekevent_to_meeting_returns_none_for_missing_uid() -> None:
    ek_event = _make_ek_event(uid="")
    assert _ekevent_to_meeting(ek_event) is None


def test_ekevent_to_meeting_returns_none_for_missing_title() -> None:
    ek_event = _make_ek_event(title="")
    assert _ekevent_to_meeting(ek_event) is None


def test_ekevent_to_meeting_returns_none_for_missing_start() -> None:
    ek_event = _make_ek_event()
    ek_event.startDate = lambda: None
    assert _ekevent_to_meeting(ek_event) is None


def test_ekevent_to_meeting_handles_none_end_date() -> None:
    ek_event = _make_ek_event()
    ek_event.endDate = lambda: None
    event = _ekevent_to_meeting(ek_event)

    assert event is not None
    assert event.end is None


def test_ekevent_to_meeting_captures_url() -> None:
    ek_event = _make_ek_event(url="https://meet.example.com/abc")
    event = _ekevent_to_meeting(ek_event)

    assert event is not None
    assert event.url == "https://meet.example.com/abc"


def test_ekevent_to_meeting_normalizes_objc_string_like_values() -> None:
    ek_event = _make_ek_event(
        uid=FakeNSString("event-objc"),
        title=FakeNSString("Harry"),
        calendar_title=FakeNSString("Calendar"),
        organizer_name=FakeNSString("Barry"),
        organizer_email=FakeNSString("barry@example.edu"),
        attendees=[(FakeNSString("Darren"), FakeNSString("darren@example.edu"))],
        location=FakeNSString("Building A"),
        notes=FakeNSString("Discuss status."),
    )

    event = _ekevent_to_meeting(ek_event)

    assert event is not None
    assert isinstance(event.uid, str)
    assert isinstance(event.title, str)
    assert isinstance(event.calendar_name, str)
    assert isinstance(event.organizer_name, str)
    assert event.uid == "event-objc"
    assert event.title == "Harry"
    assert event.organizer_email == "barry@example.edu"
    assert event.attendees == [{"name": "Darren", "email": "darren@example.edu"}]
    assert event.location == "Building A"
    assert event.notes == "Discuss status."


def test_eventkit_client_fetch_events_filters_all_day(app_settings) -> None:
    all_day_event = _make_ek_event(uid="all-day-1", is_all_day=True)
    normal_event = _make_ek_event(uid="normal-1", is_all_day=False)

    fake_store = SimpleNamespace(
        predicateForEventsWithStartDate_endDate_calendars_=lambda s, e, c: "predicate",
        eventsMatchingPredicate_=lambda p: [all_day_event, normal_event],
        calendarsForEntityType_=lambda t: [],
    )

    with patch("briefing.calendar._get_event_store", return_value=fake_store), \
         patch("briefing.calendar._request_access"), \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings)
        events = client.fetch_events(
            datetime(2026, 4, 13, tzinfo=timezone.utc),
            datetime(2026, 4, 14, tzinfo=timezone.utc),
        )

    assert len(events) == 1
    assert events[0].uid == "normal-1"


def test_eventkit_client_reuses_event_store_and_access_grant(app_settings) -> None:
    normal_event = _make_ek_event(uid="normal-1", is_all_day=False)
    fake_store = SimpleNamespace(
        predicateForEventsWithStartDate_endDate_calendars_=lambda s, e, c: "predicate",
        eventsMatchingPredicate_=lambda p: [normal_event],
        calendarsForEntityType_=lambda t: [],
    )

    with patch("briefing.calendar._get_event_store", return_value=fake_store) as get_store, \
         patch("briefing.calendar._request_access") as request_access, \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings)
        client.fetch_events(
            datetime(2026, 4, 13, tzinfo=timezone.utc),
            datetime(2026, 4, 14, tzinfo=timezone.utc),
        )
        client.fetch_events(
            datetime(2026, 4, 14, tzinfo=timezone.utc),
            datetime(2026, 4, 15, tzinfo=timezone.utc),
        )

    get_store.assert_called_once_with()
    request_access.assert_called_once_with(fake_store)


def test_eventkit_client_can_refresh_event_store_before_each_fetch(app_settings) -> None:
    first_event = _make_ek_event(uid="event-1", notes="noted config:\nlocation_type: office\n")
    updated_event = _make_ek_event(uid="event-1", notes="noted config:\nlocation_type: home\n")
    events_by_fetch = [[first_event], [updated_event]]

    class RefreshingStore:
        def __init__(self) -> None:
            self.reset_count = 0

        def reset(self) -> None:
            self.reset_count += 1

        def calendarsForEntityType_(self, event_type):
            return []

        def predicateForEventsWithStartDate_endDate_calendars_(self, start, end, calendars):
            return "predicate"

        def eventsMatchingPredicate_(self, predicate):
            return events_by_fetch[self.reset_count - 1]

    fake_store = RefreshingStore()

    with patch("briefing.calendar._get_event_store", return_value=fake_store) as get_store, \
         patch("briefing.calendar._request_access") as request_access, \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings, refresh_before_fetch=True)
        first = client.fetch_events(
            datetime(2026, 4, 13, tzinfo=timezone.utc),
            datetime(2026, 4, 14, tzinfo=timezone.utc),
        )
        updated = client.fetch_events(
            datetime(2026, 4, 13, tzinfo=timezone.utc),
            datetime(2026, 4, 14, tzinfo=timezone.utc),
        )

    get_store.assert_called_once_with()
    request_access.assert_called_once_with(fake_store)
    assert fake_store.reset_count == 2
    assert first[0].notes == "noted config:\nlocation_type: office\n"
    assert updated[0].notes == "noted config:\nlocation_type: home\n"


def test_eventkit_client_fetch_events_includes_all_day_when_configured(app_settings) -> None:
    app_settings.calendar.include_all_day = True
    all_day_event = _make_ek_event(uid="all-day-1", is_all_day=True)
    normal_event = _make_ek_event(uid="normal-1", is_all_day=False)

    fake_store = SimpleNamespace(
        predicateForEventsWithStartDate_endDate_calendars_=lambda s, e, c: "predicate",
        eventsMatchingPredicate_=lambda p: [all_day_event, normal_event],
        calendarsForEntityType_=lambda t: [],
    )

    with patch("briefing.calendar._get_event_store", return_value=fake_store), \
         patch("briefing.calendar._request_access"), \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings)
        events = client.fetch_events(
            datetime(2026, 4, 13, tzinfo=timezone.utc),
            datetime(2026, 4, 14, tzinfo=timezone.utc),
        )

    assert len(events) == 2


def _make_fake_calendar(title: str):
    return SimpleNamespace(title=lambda: title)


def _make_store_with_calendars(calendar_titles: list[str], events):
    """Build a fake store whose calendarsForEntityType_ returns named calendars."""
    calendars = [_make_fake_calendar(t) for t in calendar_titles]
    return SimpleNamespace(
        predicateForEventsWithStartDate_endDate_calendars_=lambda s, e, c: "predicate",
        eventsMatchingPredicate_=lambda p: events,
        calendarsForEntityType_=lambda t: calendars,
    )


def test_get_calendars_include_filter(app_settings) -> None:
    app_settings.calendar.include_calendar_names = ["Work"]
    event = _make_ek_event(uid="e1", calendar_title="Work")
    fake_store = _make_store_with_calendars(["Work", "Personal", "Holidays"], [event])

    with patch("briefing.calendar._get_event_store", return_value=fake_store), \
         patch("briefing.calendar._request_access"), \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings)
        events = client.fetch_events(
            datetime(2026, 4, 13, tzinfo=timezone.utc),
            datetime(2026, 4, 14, tzinfo=timezone.utc),
        )

    assert len(events) == 1
    assert events[0].uid == "e1"


def test_get_calendars_include_is_case_insensitive(app_settings) -> None:
    app_settings.calendar.include_calendar_names = ["work"]
    event = _make_ek_event(uid="e1", calendar_title="Work")
    fake_store = _make_store_with_calendars(["Work"], [event])

    with patch("briefing.calendar._get_event_store", return_value=fake_store), \
         patch("briefing.calendar._request_access"), \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings)
        events = client.fetch_events(
            datetime(2026, 4, 13, tzinfo=timezone.utc),
            datetime(2026, 4, 14, tzinfo=timezone.utc),
        )

    assert len(events) == 1


def test_get_calendars_exclude_filter(app_settings) -> None:
    app_settings.calendar.exclude_calendar_names = ["Holidays"]
    event = _make_ek_event(uid="e1", calendar_title="Work")
    fake_store = _make_store_with_calendars(["Work", "Holidays"], [event])

    with patch("briefing.calendar._get_event_store", return_value=fake_store), \
         patch("briefing.calendar._request_access"), \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings)
        events = client.fetch_events(
            datetime(2026, 4, 13, tzinfo=timezone.utc),
            datetime(2026, 4, 14, tzinfo=timezone.utc),
        )

    assert len(events) == 1


def test_get_calendars_include_and_exclude_combined(app_settings) -> None:
    app_settings.calendar.include_calendar_names = ["Work", "Work-Archive"]
    app_settings.calendar.exclude_calendar_names = ["Work-Archive"]
    event = _make_ek_event(uid="e1", calendar_title="Work")
    fake_store = _make_store_with_calendars(["Work", "Work-Archive", "Personal"], [event])

    with patch("briefing.calendar._get_event_store", return_value=fake_store), \
         patch("briefing.calendar._request_access"), \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings)
        # _get_calendars should include "Work" and "Work-Archive" then exclude "Work-Archive"
        calendars = client._get_calendars(fake_store)

    assert len(calendars) == 1
    assert calendars[0].title() == "Work"


def test_get_calendars_include_matching_nothing_returns_empty(app_settings) -> None:
    app_settings.calendar.include_calendar_names = ["NonExistent"]
    fake_store = _make_store_with_calendars(["Work", "Personal"], [])

    with patch("briefing.calendar._get_event_store", return_value=fake_store), \
         patch("briefing.calendar._request_access"), \
         patch("briefing.calendar._ns_date", side_effect=lambda dt: dt):
        client = EventKitClient(app_settings)
        calendars = client._get_calendars(fake_store)

    assert calendars == []
