"""Shared type coercion utilities used by both settings and planning."""

from __future__ import annotations

from typing import Any

_TRUE_STRINGS = frozenset({"true", "yes", "y", "1", "on"})
_FALSE_STRINGS = frozenset({"false", "no", "n", "0", "off"})


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def parse_optional_bool(value: Any) -> bool | None:
    """Parse an optional boolean value; raises ValueError for unrecognized input.

    Callers are responsible for re-raising as a domain-specific error type.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_STRINGS:
            return True
        if normalized in _FALSE_STRINGS:
            return False
        raise ValueError(f"boolean value {value!r} is not recognized")
    raise ValueError(f"expected a boolean value, got {value!r}")
