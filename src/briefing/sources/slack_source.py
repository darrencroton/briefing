"""Slack source adapter."""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

import requests

from .types import SourceContext
from ..models import SlackSourceConfig, SourceResult
from ..utils import shorten_text


class SlackClient:
    """Small Slack Web API client using a user token."""

    def __init__(self, token: str, timeout: int, page_size: int, max_messages: int):
        self.token = token
        self.timeout = timeout
        self.page_size = page_size
        self.max_messages = max_messages
        self.base_url = "https://slack.com/api"
        self.user_cache: dict[str, str] = {}
        self.channel_cache: dict[str, dict] = {}

    def validate(self) -> tuple[bool, str]:
        """Validate the user token."""
        payload = self._call("auth.test")
        if not payload.get("ok"):
            return False, str(payload.get("error"))
        return True, f"Slack token validated for {payload.get('user')} in {payload.get('team')}"

    def fetch_channel_digest(self, channel_ref: str, oldest: datetime) -> tuple[str, str]:
        """Fetch a channel by ID or name."""
        channel = self._resolve_channel(channel_ref)
        channel_id = str(channel["id"])
        channel_name = str(channel.get("name") or channel_ref)
        messages = self._fetch_messages(channel_id, oldest)
        return f"Slack #{channel_name}", self._format_digest(channel_name, messages, oldest)

    def fetch_dm_digest(self, user_id: str, oldest: datetime) -> tuple[str, str]:
        """Fetch a DM conversation with a user."""
        response = self._call("conversations.open", {"users": user_id})
        channel = response["channel"]
        channel_id = str(channel["id"])
        user_name = self.resolve_user(user_id)
        messages = self._fetch_messages(channel_id, oldest)
        return f"Slack DMs with {user_name}", self._format_digest(f"DM {user_name}", messages, oldest)

    def _resolve_channel(self, channel_ref: str) -> dict:
        if channel_ref in self.channel_cache:
            return self.channel_cache[channel_ref]
        if re.fullmatch(r"[CGD][A-Z0-9]+", channel_ref):
            info = self._call("conversations.info", {"channel": channel_ref})
            channel = info["channel"]
            self.channel_cache[channel_ref] = channel
            return channel

        cursor: str | None = None
        while True:
            payload = {
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": str(self.page_size),
            }
            if cursor:
                payload["cursor"] = cursor
            response = self._call("conversations.list", payload)
            for channel in response.get("channels", []):
                if channel.get("name") == channel_ref:
                    self.channel_cache[channel_ref] = channel
                    return channel
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        raise RuntimeError(f"Slack channel not found: {channel_ref}")

    def _fetch_messages(self, channel_id: str, oldest: datetime) -> list[dict]:
        messages: list[dict] = []
        cursor: str | None = None
        oldest_ts = str(oldest.replace(tzinfo=timezone.utc).timestamp())
        while True:
            payload = {
                "channel": channel_id,
                "oldest": oldest_ts,
                "inclusive": "true",
                "limit": str(self.page_size),
            }
            if cursor:
                payload["cursor"] = cursor
            response = self._call("conversations.history", payload)
            messages.extend(response.get("messages", []))
            if len(messages) >= self.max_messages:
                messages = messages[: self.max_messages]
                break
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        for message in list(messages):
            if int(message.get("reply_count", 0)) <= 0:
                continue
            replies = self._call(
                "conversations.replies",
                {
                    "channel": channel_id,
                    "ts": message["ts"],
                    "oldest": oldest_ts,
                    "limit": str(self.page_size),
                },
            ).get("messages", [])
            message["_replies"] = [reply for reply in replies if reply.get("ts") != message.get("ts")]
            time.sleep(0.2)
        messages.reverse()
        return messages

    def resolve_user(self, user_id: str) -> str:
        if user_id in self.user_cache:
            return self.user_cache[user_id]
        response = self._call("users.info", {"user": user_id})
        profile = response.get("user", {}).get("profile", {})
        name = profile.get("display_name") or profile.get("real_name") or user_id
        self.user_cache[user_id] = str(name)
        return self.user_cache[user_id]

    def _call(self, method: str, payload: dict[str, str] | None = None) -> dict:
        attempts = 0
        payload = payload or {}
        while True:
            attempts += 1
            response = requests.post(
                f"{self.base_url}/{method}",
                headers={"Authorization": f"Bearer {self.token}"},
                data=payload,
                timeout=self.timeout,
            )
            if response.status_code == 429 and attempts < 4:
                wait_for = int(response.headers.get("Retry-After", "1"))
                time.sleep(wait_for)
                continue
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack API {method} failed: {data.get('error')}")
            return data

    def _format_digest(self, label: str, messages: list[dict], oldest: datetime) -> str:
        lines = [
            f"# {label}",
            "",
            f"History since {oldest.date().isoformat()}",
            "",
        ]
        current_date = None
        for message in messages:
            subtype = message.get("subtype")
            if subtype in {"channel_join", "channel_leave", "bot_message"}:
                continue
            dt = datetime.fromtimestamp(float(message["ts"]), tz=timezone.utc)
            date_label = dt.strftime("%Y-%m-%d")
            if date_label != current_date:
                current_date = date_label
                lines.append(f"## {dt.strftime('%A %d %B %Y')}")
                lines.append("")
            lines.append(self._format_message_line(message))
            for reply in message.get("_replies", []):
                lines.append(self._format_message_line(reply, indent="  "))
        return "\n".join(lines).strip()

    def _format_message_line(self, message: dict, indent: str = "") -> str:
        dt = datetime.fromtimestamp(float(message["ts"]), tz=timezone.utc)
        user_id = message.get("user")
        user_name = self.resolve_user(str(user_id)) if user_id else "system"
        text = clean_slack_text(self, str(message.get("text", "")).strip())
        reactions = _format_reactions(message.get("reactions", []))
        return f"{indent}- **{user_name}** ({dt.strftime('%H:%M')}): {text}{reactions}"


def clean_slack_text(client: SlackClient, text: str) -> str:
    """Normalize Slack markup into readable Markdown."""
    text = re.sub(
        r"<@(U[A-Z0-9]+)>",
        lambda match: f"@{client.resolve_user(match.group(1))}",
        text,
    )
    text = re.sub(r"<#([CGD][A-Z0-9]+)\|([^>]+)>", r"#\2", text)
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"[\2](\1)", text)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    return text


def collect_slack_sources(
    context: SourceContext,
    config: SlackSourceConfig,
    token: str,
) -> list[SourceResult]:
    """Collect all configured Slack channel and DM digests."""
    client = SlackClient(
        token=token,
        timeout=context.settings.slack.request_timeout_seconds,
        page_size=context.settings.slack.page_size,
        max_messages=context.settings.slack.max_messages,
    )
    days = config.history_days or context.settings.slack.history_days
    oldest = datetime.now(timezone.utc) - timedelta(days=days)
    max_characters = config.max_characters or context.settings.slack.max_characters

    results: list[SourceResult] = []
    for channel_ref in config.channel_refs:
        try:
            label, content = client.fetch_channel_digest(channel_ref, oldest)
            limited, truncated = shorten_text(content, max_characters)
            results.append(
                SourceResult(
                    source_type="slack",
                    label=label,
                    content=limited,
                    required=config.required,
                    status="ok",
                    truncated=truncated,
                    metadata={"channel_ref": channel_ref},
                )
            )
        except (requests.RequestException, RuntimeError) as exc:
            results.append(
                SourceResult(
                    source_type="slack",
                    label=f"Slack #{channel_ref}",
                    content="",
                    required=config.required,
                    status="error",
                    error=str(exc),
                    metadata={"channel_ref": channel_ref},
                )
            )

    for user_id in config.dm_user_ids:
        try:
            label, content = client.fetch_dm_digest(user_id, oldest)
            limited, truncated = shorten_text(content, max_characters)
            results.append(
                SourceResult(
                    source_type="slack",
                    label=label,
                    content=limited,
                    required=config.required,
                    status="ok",
                    truncated=truncated,
                    metadata={"dm_user_id": user_id},
                )
            )
        except (requests.RequestException, RuntimeError) as exc:
            results.append(
                SourceResult(
                    source_type="slack",
                    label=f"Slack DMs with {user_id}",
                    content="",
                    required=config.required,
                    status="error",
                    error=str(exc),
                    metadata={"dm_user_id": user_id},
                )
            )

    return results


def _format_reactions(reactions: Iterable[dict]) -> str:
    parts = []
    for reaction in reactions:
        name = reaction.get("name")
        count = int(reaction.get("count", 1))
        if not name:
            continue
        if count > 1:
            parts.append(f":{name}: ×{count}")
        else:
            parts.append(f":{name}:")
    return f"  {' '.join(parts)}" if parts else ""
