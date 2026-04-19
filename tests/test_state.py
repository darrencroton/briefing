from __future__ import annotations

from datetime import datetime, timedelta, timezone

from briefing.models import OccurrenceState
from briefing.state import StateStore


def test_prune_removes_old_occurrence_state(app_settings) -> None:
    store = StateStore(app_settings)
    old_start = datetime.now(timezone.utc) - timedelta(days=181)
    recent_start = datetime.now(timezone.utc) - timedelta(days=30)

    store.save_occurrence(
        OccurrenceState(
            occurrence_key="old",
            series_id="series",
            event_uid="event-old",
            start_iso=old_start.isoformat(),
            output_path="old.md",
        )
    )
    store.save_occurrence(
        OccurrenceState(
            occurrence_key="recent",
            series_id="series",
            event_uid="event-recent",
            start_iso=recent_start.isoformat(),
            output_path="recent.md",
        )
    )

    store.prune(datetime.now(timezone.utc))

    assert not (store.occurrence_dir / "old.json").exists()
    assert (store.occurrence_dir / "recent.json").exists()


def test_prune_removes_run_diagnostics_older_than_retention_window(app_settings) -> None:
    store = StateStore(app_settings)
    now = datetime.now().astimezone()
    old = now - timedelta(days=29)
    recent = now - timedelta(days=7)

    store.write_run_diagnostic({"index": 1}, old)
    store.write_run_diagnostic({"index": 2}, recent)

    files = sorted(store.runs_dir.glob("*.json"))

    assert len(files) == 1
    assert files[0].name == recent.strftime("%Y%m%dT%H%M%S.json")
