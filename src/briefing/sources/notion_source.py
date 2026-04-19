"""Notion source adapter."""

from __future__ import annotations

import time

import requests

from .types import SourceContext
from ..models import NotionSourceConfig, SourceResult
from ..utils import shorten_text


class NotionClient:
    """Very small Notion API client."""

    def __init__(self, token: str, version: str, timeout: int):
        self.token = token
        self.version = version
        self.timeout = timeout
        self.base_url = "https://api.notion.com/v1"

    def fetch_page_content(self, page_id: str) -> str:
        """Fetch a page's block tree as plain Markdown-ish text."""
        blocks = self._fetch_children(page_id)
        lines: list[str] = []
        for block in blocks:
            rendered = self._flatten_block(block)
            if rendered:
                lines.append(rendered)
        return "\n".join(lines).strip()

    def validate(self) -> tuple[bool, str]:
        """Validate the token."""
        response = requests.get(
            f"{self.base_url}/users/me",
            headers=self._headers(),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            return False, response.text
        return True, "Notion token validated"

    def _fetch_children(self, block_id: str) -> list[dict]:
        blocks: list[dict] = []
        cursor: str | None = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            response = requests.get(
                f"{self.base_url}/blocks/{block_id}/children",
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            for block in payload.get("results", []):
                if block.get("has_children"):
                    block["_children"] = self._fetch_children(block["id"])
                blocks.append(block)
            cursor = payload.get("next_cursor")
            if not payload.get("has_more"):
                break
            time.sleep(0.2)
        return blocks

    def _flatten_block(self, block: dict) -> str:
        block_type = block.get("type", "")
        content = block.get(block_type, {})
        text = self._rich_text_to_plain(content.get("rich_text", []))
        prefix = {
            "heading_1": "# ",
            "heading_2": "## ",
            "heading_3": "### ",
            "bulleted_list_item": "- ",
            "numbered_list_item": "1. ",
            "to_do": "- [ ] " if not content.get("checked") else "- [x] ",
            "quote": "> ",
            "code": "```text\n",
        }.get(block_type, "")
        if block_type == "child_page":
            text = content.get("title", "")
        if block_type == "bookmark":
            text = content.get("caption", []) and self._rich_text_to_plain(content["caption"]) or content.get("url", "")
        line = f"{prefix}{text}".rstrip()
        if block_type == "code" and text:
            line = f"```text\n{text}\n```"
        children = "\n".join(self._flatten_block(child) for child in block.get("_children", []))
        return "\n".join(part for part in [line, children] if part).strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.version,
        }

    @staticmethod
    def _rich_text_to_plain(items: list[dict]) -> str:
        return "".join(str(item.get("plain_text", "")) for item in items)


def collect_notion_source(
    context: SourceContext,
    config: NotionSourceConfig,
    token: str,
) -> SourceResult:
    """Fetch a Notion page as plain text."""
    client = NotionClient(
        token=token,
        version=context.settings.notion.version,
        timeout=context.settings.notion.request_timeout_seconds,
    )
    try:
        content = client.fetch_page_content(config.page_id)
    except requests.RequestException as exc:
        return SourceResult(
            source_type="notion",
            label=config.label,
            content="",
            required=config.required,
            status="error",
            error=str(exc),
            metadata={"page_id": config.page_id},
        )
    limited, truncated = shorten_text(
        content,
        config.max_characters or context.settings.notion.max_characters,
    )
    return SourceResult(
        source_type="notion",
        label=config.label,
        content=limited,
        required=config.required,
        status="ok",
        truncated=truncated,
        metadata={"page_id": config.page_id, "empty": not bool(limited.strip())},
    )
