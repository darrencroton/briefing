"""Shared helpers."""

from __future__ import annotations

import hashlib
import os
import re
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
