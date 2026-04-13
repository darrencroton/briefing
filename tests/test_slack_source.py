from __future__ import annotations

from briefing.sources.slack_source import clean_slack_text


class FakeSlackClient:
    def resolve_user(self, user_id: str) -> str:
        return {"U123": "Barry"}.get(user_id, user_id)


def test_clean_slack_text_normalizes_mentions_and_links() -> None:
    client = FakeSlackClient()
    text = "Talk to <@U123> in <#C111|cas-strategy> and read <https://example.com|this link>"

    cleaned = clean_slack_text(client, text)

    assert cleaned == "Talk to @Barry in #cas-strategy and read [this link](https://example.com)"
