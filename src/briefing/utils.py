"""Shared helpers."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path


def normalize_text(value: str) -> str:
    """Normalize text for stable matching."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def slugify(value: str, fallback: str = "meeting") -> str:
    """Create a filesystem-safe slug."""
    normalized = normalize_text(value)
    return normalized or fallback


def sha256_text(value: str) -> str:
    """Return a stable content hash."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_directory(path: Path) -> Path:
    """Create a directory if needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def expand_path(path_str: str, root: Path | None = None) -> Path:
    """Expand ~ and resolve relative paths from the repo root."""
    path = Path(os.path.expandvars(path_str)).expanduser()
    if not path.is_absolute():
        if root is None:
            root = Path.cwd()
        path = root / path
    return path.resolve()


def render_template(template_text: str, values: dict[str, str]) -> str:
    """Replace {{KEY}} placeholders in tracked templates."""
    rendered = template_text
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def first_non_empty(candidates: Iterable[object]) -> object | None:
    """Return the first candidate that is not None or blank."""
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, str) and not candidate.strip():
            continue
        return candidate
    return None


def parse_datetime(value: object) -> datetime | None:
    """Parse the loose datetime values emitted by external tools."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value)).astimezone()
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.astimezone()
            return parsed
        except ValueError:
            continue
    return None


def ordinal(value: int) -> str:
    """Return the ordinal suffix for a day number."""
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def shorten_text(text: str, max_characters: int) -> tuple[str, bool]:
    """Trim long content while preserving a visible truncation marker."""
    if max_characters <= 0 or len(text) <= max_characters:
        return text, False
    trimmed = text[:max_characters].rstrip()
    return f"{trimmed}\n\n[TRUNCATED]", True


def shell_join(arguments: Iterable[str]) -> str:
    """Return a display-safe shell command preview."""
    escaped: list[str] = []
    for argument in arguments:
        if re.fullmatch(r"[A-Za-z0-9_./:-]+", argument):
            escaped.append(argument)
        else:
            escaped.append("'" + argument.replace("'", "'\\''") + "'")
    return " ".join(escaped)
