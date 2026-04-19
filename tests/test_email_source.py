from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone

import pytest

from briefing.models import EmailSourceConfig, MeetingEvent
from briefing.sources.email_source import (
    MailAdapter,
    collect_email_sources,
    _parse_sender,
    _format_messages,
)
from briefing.sources.types import SourceContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event() -> MeetingEvent:
    return MeetingEvent(
        uid="test-uid",
        title="Test Meeting",
        start=datetime(2026, 4, 16, 14, 0, tzinfo=timezone.utc),
        end=datetime(2026, 4, 16, 15, 0, tzinfo=timezone.utc),
        calendar_name="Calendar",
    )


def _make_context(app_settings, series_config) -> SourceContext:
    return SourceContext(
        settings=app_settings,
        event=_make_event(),
        series=series_config,
        logger=logging.getLogger("test"),
        env={},
    )


_CUTOFF = datetime(2026, 4, 9, tzinfo=timezone.utc)

_RAW_OUTPUT = (
    "<<MSG>>\n"
    "date: 2026-04-16 09:14\n"
    "from: Ben Smith <ben@example.com>\n"
    "to: darren@example.com,\n"
    "subject: Re: Q2 Planning\n"
    "body: Sounds good let's align Thursday\n"
    "<<MSG>>"
)


# ---------------------------------------------------------------------------
# _parse_sender
# ---------------------------------------------------------------------------

def test_parse_sender_with_angle_brackets() -> None:
    name, email = _parse_sender("Ben Smith <ben@example.com>")
    assert name == "Ben Smith"
    assert email == "ben@example.com"


def test_parse_sender_email_only() -> None:
    name, email = _parse_sender("ben@example.com")
    assert name == ""
    assert email == "ben@example.com"


def test_parse_sender_quoted_name() -> None:
    name, email = _parse_sender('"Ben Smith" <ben@example.com>')
    assert name == "Ben Smith"
    assert email == "ben@example.com"


# ---------------------------------------------------------------------------
# MailAdapter.validate
# ---------------------------------------------------------------------------

def test_mail_adapter_validate_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MailAdapter(timeout=5)
    monkeypatch.setattr(adapter, "_run_script", lambda _script: (0, "iCloud", ""))
    ok, msg = adapter.validate()
    assert ok
    assert "OK" in msg


def test_mail_adapter_validate_returns_error_when_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MailAdapter(timeout=5)
    monkeypatch.setattr(adapter, "_run_script", lambda _script: (1, "", "not authorized to send Apple events"))
    ok, msg = adapter.validate()
    assert not ok
    assert "Automation" in msg


def test_mail_adapter_validate_returns_error_when_mail_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MailAdapter(timeout=5)
    monkeypatch.setattr(adapter, "_run_script", lambda _script: (1, "", "Application Mail is not running"))
    ok, msg = adapter.validate()
    assert not ok
    assert "Mail.app" in msg


def test_mail_adapter_validate_returns_error_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MailAdapter(timeout=5)

    def raise_timeout(_script):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=5)

    monkeypatch.setattr(adapter, "_run_script", raise_timeout)
    ok, msg = adapter.validate()
    assert not ok
    assert "timed out" in msg


# ---------------------------------------------------------------------------
# MailAdapter.fetch_messages
# ---------------------------------------------------------------------------

def test_mail_adapter_fetch_messages_parses_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MailAdapter(timeout=5)
    monkeypatch.setattr(adapter, "_run_script", lambda _script: (0, _RAW_OUTPUT, ""))
    msgs = adapter.fetch_messages(account=None, mailboxes=[], cutoff=_CUTOFF, max_messages=20)
    assert len(msgs) == 1
    assert msgs[0]["subject"] == "Re: Q2 Planning"
    assert msgs[0]["from_email"] == "ben@example.com"
    assert msgs[0]["from_name"] == "Ben Smith"
    assert msgs[0]["date"] == "2026-04-16 09:14"
    assert "darren@example.com" in msgs[0]["to_emails"]


def test_mail_adapter_fetch_messages_returns_empty_list_on_no_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MailAdapter(timeout=5)
    monkeypatch.setattr(adapter, "_run_script", lambda _script: (0, "", ""))
    msgs = adapter.fetch_messages(account=None, mailboxes=[], cutoff=_CUTOFF, max_messages=20)
    assert msgs == []


def test_mail_adapter_fetch_messages_raises_on_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MailAdapter(timeout=5)
    monkeypatch.setattr(adapter, "_run_script", lambda _script: (1, "", "not authorized"))
    with pytest.raises(RuntimeError, match="not authorized"):
        adapter.fetch_messages(account=None, mailboxes=[], cutoff=_CUTOFF, max_messages=20)


def test_mail_adapter_fetch_messages_propagates_subprocess_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MailAdapter(timeout=5)

    def fail(_script):
        raise subprocess.SubprocessError("osascript not found")

    monkeypatch.setattr(adapter, "_run_script", fail)
    with pytest.raises(subprocess.SubprocessError):
        adapter.fetch_messages(account=None, mailboxes=[], cutoff=_CUTOFF, max_messages=20)


# ---------------------------------------------------------------------------
# collect_email_sources
# ---------------------------------------------------------------------------

def test_collect_email_sources_formats_output_grouped_by_date(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
    series_config,
) -> None:
    config = EmailSourceConfig()
    msgs = [
        {
            "subject": "Hello",
            "from_name": "Ben",
            "from_email": "ben@example.com",
            "to_emails": [],
            "date": "2026-04-16 09:14",
            "body": "Hi there",
        }
    ]
    monkeypatch.setattr(
        "briefing.sources.email_source.MailAdapter.fetch_messages",
        lambda *_args, **_kwargs: msgs,
    )
    results = collect_email_sources(_make_context(app_settings, series_config), [config])
    assert len(results) == 1
    result = results[0]
    assert result.status == "ok"
    assert result.source_type == "email"
    assert result.label == "Emails related to CAS Strategy Meeting"
    assert "Ben" in result.content
    assert "Hello" in result.content
    assert "Thursday" in result.content  # date heading


def test_collect_email_sources_filters_by_from_email(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
    series_config,
) -> None:
    config = EmailSourceConfig(email_addresses=["alice@example.com"])
    msgs = [
        {"subject": "From Alice", "from_name": "Alice", "from_email": "alice@example.com", "to_emails": [], "date": "2026-04-16 09:00", "body": "Hi"},
        {"subject": "From Bob", "from_name": "Bob", "from_email": "bob@example.com", "to_emails": [], "date": "2026-04-16 10:00", "body": "Hey"},
    ]
    monkeypatch.setattr(
        "briefing.sources.email_source.MailAdapter.fetch_messages",
        lambda *_args, **_kwargs: msgs,
    )
    results = collect_email_sources(_make_context(app_settings, series_config), [config])
    assert "From Alice" in results[0].content
    assert "From Bob" not in results[0].content


def test_collect_email_sources_filters_by_to_email(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
    series_config,
) -> None:
    """Sent email (from self to Ben) is included when Ben's address is configured."""
    config = EmailSourceConfig(email_addresses=["ben@example.com"])
    msgs = [
        # Received from Ben
        {"subject": "From Ben", "from_name": "Ben", "from_email": "ben@example.com", "to_emails": ["darren@example.com"], "date": "2026-04-15 10:00", "body": "Here's the report"},
        # Sent to Ben (from self) — currently no reply
        {"subject": "Report request", "from_name": "Darren", "from_email": "darren@example.com", "to_emails": ["ben@example.com"], "date": "2026-04-16 09:00", "body": "Can you send the report?"},
        # Unrelated — neither from nor to Ben
        {"subject": "Unrelated", "from_name": "Alice", "from_email": "alice@example.com", "to_emails": ["darren@example.com"], "date": "2026-04-16 10:00", "body": "Other"},
    ]
    monkeypatch.setattr(
        "briefing.sources.email_source.MailAdapter.fetch_messages",
        lambda *_args, **_kwargs: msgs,
    )
    results = collect_email_sources(_make_context(app_settings, series_config), [config])
    assert "From Ben" in results[0].content
    assert "Report request" in results[0].content   # sent email caught via to_emails
    assert "Unrelated" not in results[0].content


def test_collect_email_sources_filters_by_subject_regex(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
    series_config,
) -> None:
    config = EmailSourceConfig(subject_regex_any=["planning"])
    msgs = [
        {"subject": "Q2 Planning", "from_name": "Ben", "from_email": "ben@example.com", "to_emails": [], "date": "2026-04-16 09:00", "body": "..."},
        {"subject": "Team lunch", "from_name": "Ben", "from_email": "ben@example.com", "to_emails": [], "date": "2026-04-16 10:00", "body": "..."},
    ]
    monkeypatch.setattr(
        "briefing.sources.email_source.MailAdapter.fetch_messages",
        lambda *_args, **_kwargs: msgs,
    )
    results = collect_email_sources(_make_context(app_settings, series_config), [config])
    assert "Q2 Planning" in results[0].content
    assert "Team lunch" not in results[0].content


def test_collect_email_sources_returns_error_result_on_adapter_exception(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
    series_config,
) -> None:
    config = EmailSourceConfig(required=False)

    def fail(*_args, **_kwargs):
        raise RuntimeError("permission denied")

    monkeypatch.setattr(
        "briefing.sources.email_source.MailAdapter.fetch_messages",
        fail,
    )
    results = collect_email_sources(_make_context(app_settings, series_config), [config])
    assert results[0].status == "error"
    assert "permission denied" in results[0].error
    assert results[0].required is False


def test_collect_email_sources_empty_mailbox_returns_ok_with_empty_content(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
    series_config,
) -> None:
    config = EmailSourceConfig()
    monkeypatch.setattr(
        "briefing.sources.email_source.MailAdapter.fetch_messages",
        lambda *_args, **_kwargs: [],
    )
    results = collect_email_sources(_make_context(app_settings, series_config), [config])
    assert results[0].status == "ok"
    assert results[0].content == ""


def test_collect_email_sources_returns_one_result_per_config(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
    series_config,
) -> None:
    configs = [
        EmailSourceConfig(email_addresses=["ben@example.com"]),
        EmailSourceConfig(email_addresses=["alice@example.com"]),
    ]
    monkeypatch.setattr(
        "briefing.sources.email_source.MailAdapter.fetch_messages",
        lambda *_args, **_kwargs: [],
    )
    results = collect_email_sources(_make_context(app_settings, series_config), configs)
    assert len(results) == 2
    assert all(r.label == "Emails related to CAS Strategy Meeting" for r in results)


# ---------------------------------------------------------------------------
# _format_messages
# ---------------------------------------------------------------------------

def test_format_messages_returns_empty_string_for_no_messages() -> None:
    assert _format_messages([], "Label", 7, []) == ""


def test_format_messages_includes_label_and_scope() -> None:
    msgs = [{"subject": "Hi", "from_name": "Ben", "from_email": "ben@example.com", "to_emails": [], "date": "2026-04-16 09:00", "body": ""}]
    out = _format_messages(msgs, "My Emails", 7, ["INBOX"])
    assert "# My Emails" in out
    assert "INBOX" in out


def test_format_messages_shows_to_address_for_sent_emails() -> None:
    msgs = [{"subject": "Hi", "from_name": "Darren", "from_email": "darren@example.com", "to_emails": ["ben@example.com"], "date": "2026-04-16 09:00", "body": ""}]
    out = _format_messages(msgs, "Label", 7, [])
    assert "ben@example.com" in out
    assert "→" in out


def test_format_messages_groups_by_date_descending() -> None:
    msgs = [
        {"subject": "Earlier", "from_name": "A", "from_email": "a@x.com", "to_emails": [], "date": "2026-04-14 09:00", "body": ""},
        {"subject": "Later", "from_name": "B", "from_email": "b@x.com", "to_emails": [], "date": "2026-04-16 10:00", "body": ""},
    ]
    out = _format_messages(msgs, "Label", 7, [])
    assert out.index("Later") < out.index("Earlier")
