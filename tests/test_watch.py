from __future__ import annotations

import json
import pytest
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from briefing.models import MeetingEvent
from briefing.planning import invalidate_stale_plans, plan_event
from briefing.session.completion import read_completion
from briefing.state import StateStore
from briefing.watch import run_watch


class FakeCalendar:
    def __init__(self, events: list[MeetingEvent]) -> None:
        self.events = events

    def fetch_events(self, start: datetime, end: datetime) -> list[MeetingEvent]:
        return [event for event in self.events if start <= event.start <= end]


@pytest.fixture(autouse=True)
def no_noted_pause_marker(monkeypatch) -> None:
    monkeypatch.setattr("briefing.watch._noted_scheduled_recording_paused", lambda: False)


def test_watch_once_dry_run_plans_without_marking_launch(app_settings) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )

    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=True,
        now_provider=lambda: now,
        calendar=FakeCalendar([event]),
    )

    assert exit_code == 0
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "planned"
    assert plans[0].launched_at is None
    assert plans[0].launch_exit_code is None


def test_watch_cycle_runs_retention_best_effort(monkeypatch, app_settings) -> None:
    calls: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        "briefing.watch.run_retention_sweep_best_effort",
        lambda settings, *, dry_run=False: calls.append((settings, dry_run)),
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")

    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=True,
        now_provider=lambda: now,
        calendar=FakeCalendar([]),
    )

    assert exit_code == 0
    assert calls == [(app_settings, True)]


def test_watch_refreshes_eventkit_store_per_poll(monkeypatch, app_settings) -> None:
    refresh_values: list[bool] = []

    class FakeEventKitClient:
        def __init__(self, settings, *, refresh_before_fetch: bool = False) -> None:
            refresh_values.append(refresh_before_fetch)

        def fetch_events(self, start: datetime, end: datetime) -> list[MeetingEvent]:
            return []

    monkeypatch.setattr("briefing.watch.EventKitClient", FakeEventKitClient)
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")

    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=True,
        now_provider=lambda: now,
    )

    assert exit_code == 0
    assert refresh_values == [True]


def test_watch_dry_run_does_not_block_later_real_launch(monkeypatch, app_settings) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )
    launches: list[list[str]] = []

    def fake_run(command, **kwargs):
        launches.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=True,
        now_provider=lambda: now,
        calendar=FakeCalendar([event]),
    )
    assert exit_code == 0

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run)
    exit_code = run_watch(
        app_settings,
        once=True,
        now_provider=lambda: now,
        calendar=FakeCalendar([event]),
    )

    assert exit_code == 0
    assert len(launches) == 1
    assert launches[0][:3] == [app_settings.meeting_intelligence.noted_command, "start", "--manifest"]


def test_watch_skips_planning_when_noted_pause_marker_exists(monkeypatch, app_settings) -> None:
    monkeypatch.setattr("briefing.watch._noted_scheduled_recording_paused", lambda: True)
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )

    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=False,
        now_provider=lambda: now,
        calendar=FakeCalendar([event]),
    )

    assert exit_code == 0
    assert StateStore(app_settings).list_session_plans() == []
    assert list(app_settings.meeting_intelligence.sessions_root.glob("*/manifest.json")) == []


def test_watch_invalidates_unlaunched_plans_when_noted_pause_marker_exists(monkeypatch, app_settings) -> None:
    monkeypatch.setattr("briefing.watch._noted_scheduled_recording_paused", lambda: True)
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )
    result = plan_event(app_settings, event, events=[event], now=now)
    assert result.manifest_path is not None
    assert Path(result.manifest_path).exists()

    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=False,
        now_provider=lambda: now,
        calendar=FakeCalendar([event]),
    )

    assert exit_code == 0
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "invalidated"
    assert plans[0].invalidation_reason == "scheduled_recording_disabled"
    assert not Path(result.manifest_path).exists()


def test_watch_replans_after_noted_pause_marker_is_removed(app_settings) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )
    result = plan_event(app_settings, event, events=[event], now=now)
    plan = StateStore(app_settings).load_session_plan_for_event(event)
    assert plan is not None
    plan.status = "invalidated"
    plan.invalidation_reason = "scheduled_recording_disabled"
    StateStore(app_settings).save_session_plan(plan)
    Path(result.manifest_path).unlink()

    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=True,
        now_provider=lambda: now,
        calendar=FakeCalendar([event]),
    )

    assert exit_code == 0
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "planned"
    assert Path(plans[0].manifest_path).exists()


def test_watch_does_not_relaunch_after_prior_launch_attempt(
    monkeypatch,
    app_settings,
) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )
    launches: list[list[str]] = []

    def fake_run(command, **kwargs):
        launches.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run)

    for _ in range(2):
        exit_code = run_watch(
            app_settings,
            once=True,
            now_provider=lambda: now,
            calendar=FakeCalendar([event]),
        )
        assert exit_code == 0

    assert len(launches) == 1
    assert launches[0][:3] == [app_settings.meeting_intelligence.noted_command, "start", "--manifest"]
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "launched"
    assert plans[0].launched_at is not None


def test_watch_treats_matching_session_already_running_as_launched(
    monkeypatch,
    app_settings,
) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )

    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=5,
            stdout='{"ok":false,"error":"session_already_running","session_id":"2026-04-13T100000+1000-cas-strategy-meeting"}',
            stderr="",
        )

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run)
    exit_code = run_watch(
        app_settings,
        once=True,
        now_provider=lambda: now,
        calendar=FakeCalendar([event]),
    )

    assert exit_code == 0
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "launched"
    assert plans[0].launch_exit_code == 5
    assert plans[0].launched_at is not None


def test_watch_keeps_unrelated_session_already_running_as_launch_blocked(
    monkeypatch,
    app_settings,
) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )

    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=5,
            stdout='{"ok":false,"error":"session_already_running","running_session_id":"other-session","session_id":"different-session"}',
            stderr="",
        )

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run)
    exit_code = run_watch(
        app_settings,
        once=True,
        now_provider=lambda: now,
        calendar=FakeCalendar([event]),
    )

    assert exit_code == 0
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "launch_blocked"
    assert plans[0].launch_exit_code == 5
    assert plans[0].launched_at is None


def test_watch_retries_blocked_launch_when_blocker_clears(
    monkeypatch,
    app_settings,
) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    # Event has started (start <= now) but end is in the future — retry window is open
    now = datetime.fromisoformat("2026-04-13T10:05:00+10:00")
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    calls: list[str] = []

    def fake_run_blocked(command, **kwargs):
        calls.append("blocked")
        return SimpleNamespace(
            returncode=5,
            stdout='{"ok":false,"error":"session_already_running","running_session_id":"other-session","session_id":"other-session"}',
            stderr="",
        )

    def fake_run_success(command, **kwargs):
        calls.append("success")
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run_blocked)
    # First cycle: pre-roll fires, noted returns blocked
    run_watch(app_settings, once=True, now_provider=lambda: now - timedelta(minutes=6), calendar=FakeCalendar([event]))
    plans = StateStore(app_settings).list_session_plans()
    assert plans[0].status == "launch_blocked"
    assert plans[0].launched_at is None

    # Second cycle: after event.start, retry path fires and succeeds
    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run_success)
    run_watch(app_settings, once=True, now_provider=lambda: now, calendar=FakeCalendar([event]))
    plans = StateStore(app_settings).list_session_plans()
    assert plans[0].status == "launched"
    assert plans[0].launched_at is not None
    assert len(calls) == 2


def test_watch_marks_blocked_launch_invalidated_when_event_window_closes(
    monkeypatch,
    app_settings,
) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )

    def fake_run_blocked(command, **kwargs):
        return SimpleNamespace(
            returncode=5,
            stdout='{"ok":false,"error":"session_already_running","running_session_id":"other-session","session_id":"other-session"}',
            stderr="",
        )

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run_blocked)
    # First cycle: pre-roll fires, noted returns blocked
    pre_roll = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    run_watch(app_settings, once=True, now_provider=lambda: pre_roll, calendar=FakeCalendar([event]))
    plans = StateStore(app_settings).list_session_plans()
    assert plans[0].status == "launch_blocked"

    # Second cycle: past event.end — window is closed, stop retrying
    past_end = datetime.fromisoformat("2026-04-13T11:05:00+10:00")
    monkeypatch.setattr("briefing.watch.subprocess.run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not call noted")))
    run_watch(app_settings, once=True, now_provider=lambda: past_end, calendar=FakeCalendar([event]))
    plans = StateStore(app_settings).list_session_plans()
    assert plans[0].status == "invalidated"
    assert plans[0].invalidation_reason == "launch_blocked_window_closed"
    completion = json.loads((Path(plans[0].session_dir) / "outputs" / "completion.json").read_text(encoding="utf-8"))
    assert completion["schema_version"] == "1.0"
    assert completion["session_id"] == plans[0].session_id
    assert completion["terminal_status"] == "failed"
    assert completion["stop_reason"] == "startup_failure"
    assert completion["audio_capture_ok"] is False
    assert completion["transcript_ok"] is False
    assert completion["diarization_ok"] is False
    assert completion["errors"] == ["launch_blocked_window_closed"]
    parsed = read_completion(Path(plans[0].session_dir))
    assert parsed.terminal_status == "failed"
    assert parsed.stop_reason == "startup_failure"


def test_watch_launches_rewritten_reschedule_plan_without_duplicate(
    monkeypatch,
    app_settings,
) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    original = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    moved = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:02:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:02:00+10:00"),
        calendar_name="Work",
    )
    result = plan_event(
        app_settings,
        original,
        events=[original],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )
    assert result.manifest_path is not None
    invalidated = invalidate_stale_plans(
        app_settings,
        [moved],
        now=datetime.fromisoformat("2026-04-13T09:59:00+10:00"),
    )
    assert invalidated == []
    launches: list[list[str]] = []

    def fake_run(command, **kwargs):
        launches.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run)
    exit_code = run_watch(
        app_settings,
        once=True,
        now_provider=lambda: datetime.fromisoformat("2026-04-13T10:00:45+10:00"),
        calendar=FakeCalendar([moved]),
    )

    assert exit_code == 0
    assert launches == [[app_settings.meeting_intelligence.noted_command, "start", "--manifest", result.manifest_path]]
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "launched"
    assert plans[0].start_iso == "2026-04-13T10:02:00+10:00"


def test_watch_replans_out_of_tolerance_reschedule(
    monkeypatch,
    app_settings,
) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    original = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    moved = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:30:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:30:00+10:00"),
        calendar_name="Work",
    )
    result = plan_event(
        app_settings,
        original,
        events=[original],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )
    assert result.manifest_path is not None
    invalidated = invalidate_stale_plans(
        app_settings,
        [moved],
        now=datetime.fromisoformat("2026-04-13T10:10:00+10:00"),
    )
    assert [plan.invalidation_reason for plan in invalidated] == ["event_rescheduled_out_of_tolerance"]
    launches: list[list[str]] = []

    def fake_run(command, **kwargs):
        launches.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run)
    exit_code = run_watch(
        app_settings,
        once=True,
        now_provider=lambda: datetime.fromisoformat("2026-04-13T10:28:45+10:00"),
        calendar=FakeCalendar([moved]),
    )

    assert exit_code == 0
    assert len(launches) == 1
    assert launches[0][:3] == [app_settings.meeting_intelligence.noted_command, "start", "--manifest"]
    assert launches[0][3] != result.manifest_path
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "launched"
    assert plans[0].start_iso == "2026-04-13T10:30:00+10:00"


def test_watch_refreshes_next_manifest_for_active_launched_meeting(
    monkeypatch,
    app_settings,
) -> None:
    for series_id, title in (
        ("cas-strategy", "CAS Strategy Meeting"),
        ("ops-review", "Ops Review"),
    ):
        (app_settings.paths.series_dir / f"{series_id}.yaml").write_text(
            yaml.safe_dump(
                {
                    "series_id": series_id,
                    "display_name": title,
                    "note_slug": series_id,
                    "match": {"title_any": [title]},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    current = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=datetime.fromisoformat("2026-04-13T10:00:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T10:30:00+10:00"),
        calendar_name="Work",
    )
    launches: list[list[str]] = []

    def fake_run(command, **kwargs):
        launches.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("briefing.watch.subprocess.run", fake_run)
    exit_code = run_watch(
        app_settings,
        once=True,
        now_provider=lambda: datetime.fromisoformat("2026-04-13T09:58:45+10:00"),
        calendar=FakeCalendar([current]),
    )
    assert exit_code == 0
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "launched"
    manifest_path = Path(plans[0].manifest_path)
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["next_meeting"] == {"exists": False}

    next_event = MeetingEvent(
        uid="event-2",
        title="Ops Review",
        start=datetime.fromisoformat("2026-04-13T10:35:00+10:00"),
        end=datetime.fromisoformat("2026-04-13T11:00:00+10:00"),
        calendar_name="Work",
    )
    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=True,
        now_provider=lambda: datetime.fromisoformat("2026-04-13T10:10:00+10:00"),
        calendar=FakeCalendar([current, next_event]),
    )

    assert exit_code == 0
    refreshed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert refreshed["next_meeting"]["exists"] is True
    assert refreshed["next_meeting"]["event_id"] == "event-2"
    assert Path(refreshed["next_meeting"]["manifest_path"]).exists()
    assert len(launches) == 1


def test_watch_continues_after_bad_event_config(app_settings) -> None:
    (app_settings.paths.series_dir / "cas-strategy.yaml").write_text(
        yaml.safe_dump(
            {
                "series_id": "cas-strategy",
                "display_name": "CAS Strategy Meeting",
                "note_slug": "cas-strategy-meeting",
                "match": {"title_any": ["CAS Strategy Meeting"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    now = datetime.fromisoformat("2026-04-13T09:58:45+10:00")
    bad = MeetingEvent(
        uid="bad-event",
        title="Bad One-Off",
        start=now + timedelta(seconds=70),
        end=now + timedelta(hours=1),
        calendar_name="Work",
        notes="noted config:\nrecord: flase\n",
    )
    good = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=now + timedelta(seconds=75),
        end=now + timedelta(hours=1),
        calendar_name="Work",
    )

    exit_code = run_watch(
        app_settings,
        once=True,
        dry_run=True,
        now_provider=lambda: now,
        calendar=FakeCalendar([bad, good]),
    )

    assert exit_code == 1
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].event_uid == "event-1"
