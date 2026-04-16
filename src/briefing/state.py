"""Persistent run state."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import MeetingEvent, OccurrenceState
from .settings import AppSettings
from .utils import ensure_directory, sha256_text


class StateStore:
    """JSON-backed state store."""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.state_dir = ensure_directory(settings.paths.state_dir)
        self.occurrence_dir = ensure_directory(self.state_dir / "occurrences")
        self.runs_dir = ensure_directory(self.state_dir / "runs")

    def occurrence_key(self, event: MeetingEvent) -> str:
        """Create a stable occurrence key.

        Normalizes start to UTC so the key is independent of the local
        timezone (e.g. travel, DST boundary differences).
        """
        utc_start = event.start.astimezone(timezone.utc).isoformat()
        return sha256_text(f"{event.uid}|{utc_start}")[:24]

    def load_occurrence(self, occurrence_key: str) -> OccurrenceState | None:
        """Load stored occurrence state."""
        path = self.occurrence_dir / f"{occurrence_key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return OccurrenceState(**data)

    def save_occurrence(self, occurrence: OccurrenceState) -> Path:
        """Persist occurrence state."""
        path = self.occurrence_dir / f"{occurrence.occurrence_key}.json"
        path.write_text(json.dumps(asdict(occurrence), indent=2), encoding="utf-8")
        return path

    def write_run_diagnostic(self, payload: dict[str, object], now: datetime) -> Path:
        """Write one machine-readable run diagnostic."""
        name = now.strftime("%Y%m%dT%H%M%S")
        path = self.runs_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

