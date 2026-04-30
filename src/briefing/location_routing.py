"""Helpers for local machine recording-location routing."""

from __future__ import annotations

import platform
import socket
import subprocess
from functools import lru_cache


def normalize_location_type(value: str | None) -> str | None:
    """Normalize a user-facing location label for comparison."""
    if value is None:
        return None
    normalized = str(value).strip().lower().replace(" ", "_")
    return normalized or None


def normalize_machine_name(value: str | None) -> str | None:
    """Normalize a macOS machine name for lookup."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


@lru_cache(maxsize=1)
def current_machine_names() -> tuple[str, ...]:
    """Return known names for this Mac, ordered from most explicit to fallback."""
    candidates: list[str] = []
    for name_key in ("HostName", "LocalHostName", "ComputerName"):
        value = _scutil_get(name_key)
        if value:
            candidates.append(value)
    candidates.extend([socket.gethostname(), platform.node()])

    seen: set[str] = set()
    names: list[str] = []
    for candidate in candidates:
        normalized = normalize_machine_name(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            names.append(str(candidate).strip())
    return tuple(names)


def resolve_local_location_type(
    *,
    local_location_type: str | None,
    location_type_by_host: dict[str, str],
    machine_names: tuple[str, ...] | None = None,
) -> str | None:
    """Resolve the configured recording-location label for this machine."""
    explicit = normalize_location_type(local_location_type)
    if explicit:
        return explicit

    names = machine_names if machine_names is not None else current_machine_names()
    normalized_map = {
        normalize_machine_name(host): normalize_location_type(location)
        for host, location in location_type_by_host.items()
    }
    for name in names:
        location = normalized_map.get(normalize_machine_name(name))
        if location:
            return location
    return None


def _scutil_get(name_key: str) -> str | None:
    try:
        completed = subprocess.run(
            ["scutil", "--get", name_key],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None
