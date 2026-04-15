from __future__ import annotations

from datetime import datetime, timezone

import pytest

from briefing.sources.slack_source import SlackClient, clean_slack_text


class FakeSlackClient:
    def resolve_user(self, user_id: str) -> str:
        return {"U123": "Barry"}.get(user_id, user_id)


def test_clean_slack_text_normalizes_mentions_and_links() -> None:
    client = FakeSlackClient()
    text = "Talk to <@U123> in <#C111|cas-strategy> and read <https://example.com|this link>"

    cleaned = clean_slack_text(client, text)

    assert cleaned == "Talk to @Barry in cas-strategy and read [this link](https://example.com)"


def test_fetch_dm_conversation_digest_reads_one_to_one_dm_by_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SlackClient(token="token", timeout=5, page_size=20, max_messages=50)
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_call(method: str, payload: dict[str, str] | None = None) -> dict:
        request = payload or {}
        calls.append((method, request))
        if method == "conversations.info":
            assert request == {"channel": "D123"}
            return {"channel": {"id": "D123", "is_im": True, "user": "U123"}}
        if method == "users.info":
            assert request == {"user": "U123"}
            return {"user": {"profile": {"display_name": "Barry"}}}
        if method == "conversations.history":
            assert request["channel"] == "D123"
            return {"messages": [{"ts": "1711972800.000100", "user": "U123", "text": "Status update"}]}
        raise AssertionError(f"Unexpected Slack API call: {method} {request}")

    monkeypatch.setattr(client, "_call", fake_call)

    label, content = client.fetch_dm_conversation_digest(
        "D123",
        datetime(2024, 4, 1, tzinfo=timezone.utc),
    )

    assert label == "Slack DM with Barry"
    assert "# DM Barry" in content
    assert "- **Barry** (12:00): Status update" in content
    assert all(method != "conversations.open" for method, _ in calls)


def test_fetch_dm_conversation_digest_reads_group_dm_by_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SlackClient(token="token", timeout=5, page_size=20, max_messages=50)

    def fake_call(method: str, payload: dict[str, str] | None = None) -> dict:
        request = payload or {}
        if method == "conversations.info":
            assert request == {"channel": "G123"}
            return {"channel": {"id": "G123", "is_mpim": True}}
        if method == "conversations.members":
            assert request == {"channel": "G123"}
            return {"members": ["U123", "U456"]}
        if method == "users.info":
            names = {
                "U123": {"user": {"profile": {"display_name": "Barry"}}},
                "U456": {"user": {"profile": {"display_name": "Dana"}}},
            }
            return names[request["user"]]
        if method == "conversations.history":
            assert request["channel"] == "G123"
            return {"messages": [{"ts": "1711972800.000100", "user": "U456", "text": "Shared prep"}]}
        raise AssertionError(f"Unexpected Slack API call: {method} {request}")

    monkeypatch.setattr(client, "_call", fake_call)

    label, content = client.fetch_dm_conversation_digest(
        "G123",
        datetime(2024, 4, 1, tzinfo=timezone.utc),
    )

    assert label == "Slack group DM with Barry, Dana"
    assert "# group DM Barry, Dana" in content
    assert "- **Dana** (12:00): Shared prep" in content


def test_fetch_dm_conversation_digest_rejects_non_dm_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SlackClient(token="token", timeout=5, page_size=20, max_messages=50)

    def fake_call(method: str, payload: dict[str, str] | None = None) -> dict:
        request = payload or {}
        if method == "conversations.info":
            assert request == {"channel": "C123"}
            return {"channel": {"id": "C123", "is_channel": True}}
        raise AssertionError(f"Unexpected Slack API call: {method} {request}")

    monkeypatch.setattr(client, "_call", fake_call)

    with pytest.raises(RuntimeError, match=r"move it to channel_refs"):
        client.fetch_dm_conversation_digest("C123", datetime(2024, 4, 1, tzinfo=timezone.utc))


def test_resolve_channel_rejects_dm_conversation_id_even_after_dm_cache_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SlackClient(token="token", timeout=5, page_size=20, max_messages=50)

    def fake_call(method: str, payload: dict[str, str] | None = None) -> dict:
        request = payload or {}
        if method == "conversations.info":
            assert request == {"channel": "D123"}
            return {"channel": {"id": "D123", "is_im": True, "user": "U123"}}
        if method == "users.info":
            assert request == {"user": "U123"}
            return {"user": {"profile": {"display_name": "Barry"}}}
        if method == "conversations.history":
            assert request["channel"] == "D123"
            return {"messages": [{"ts": "1711972800.000100", "user": "U123", "text": "Status update"}]}
        raise AssertionError(f"Unexpected Slack API call: {method} {request}")

    monkeypatch.setattr(client, "_call", fake_call)

    client.fetch_dm_conversation_digest("D123", datetime(2024, 4, 1, tzinfo=timezone.utc))

    with pytest.raises(RuntimeError, match=r"move it to dm_conversation_ids"):
        client._resolve_channel("D123")
