"""Shared source collection types."""

from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from ..models import MeetingEvent, SeriesConfig
from ..settings import AppSettings


@dataclass(slots=True)
class SourceContext:
    """Shared context passed to every source adapter."""

    settings: AppSettings
    event: MeetingEvent
    series: SeriesConfig
    logger: Logger
    env: dict[str, str]

