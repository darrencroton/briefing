from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from briefing.models import MeetingEvent, RecordingConfig
from briefing.planning import (
    PlanningError,
    assemble_manifest,
    invalidate_stale_plans,
    manifest_validator,
    parse_noted_config,
    plan_event,
    resolve_event_eligibility,
)
from briefing.state import StateStore


def _write_series(app_settings, payload: dict) -> Path:
    path = app_settings.paths.series_dir / f"{payload['series_id']}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _event(
    uid: str = "event-1",
    title: str = "CAS Strategy Meeting",
    start: str = "2026-04-13T10:00:00+10:00",
    notes: str | None = None,
) -> MeetingEvent:
    start_dt = datetime.fromisoformat(start)
    return MeetingEvent(
        uid=uid,
        title=title,
        start=start_dt,
        end=start_dt + timedelta(hours=1),
        calendar_name="Work",
        organizer_name="Barry",
        organizer_email="barry@example.edu",
        location="Room 1",
        notes=notes,
        attendees=[{"name": "Darren", "email": "darren@example.edu"}],
    )


def test_parse_noted_config_marker_is_case_insensitive_and_typed() -> None:
    config = parse_noted_config(
        """
Intro text
NoTeD CoNfIg
record: true
mode: online
participants:
  host_name: Casey
  attendees_expected: 3
transcription:
  language: en-US
  speaker_count_hint: 2
"""
    )

    assert config is not None
    assert config.record is True
    assert config.mode == "online"
    assert config.host_name == "Casey"
    assert config.attendees_expected == 3
    assert config.language == "en-US"
    assert config.speaker_count_hint == 2


def test_series_matched_event_uses_noted_config_field_overrides(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
            "recording": {
                "record": True,
                "mode": "in_person",
                "participants": {"host_name": "Barry"},
                "transcription": {"language": "en-AU"},
            },
        },
    )
    event = _event(notes="noted config\nmode: online\nparticipants:\n  host_name: Casey\n")

    from briefing.settings import load_series_configs

    eligibility = resolve_event_eligibility(event, load_series_configs(app_settings))

    assert eligibility.eligible is True
    assert eligibility.series is not None
    assert eligibility.recording is not None
    assert eligibility.recording.mode == "online"
    assert eligibility.recording.host_name == "Casey"
    assert eligibility.recording.language == "en-AU"


def test_record_false_skips_series_recording(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
            "recording": {"record": True},
        },
    )
    event = _event(notes="noted config\nrecord: false\n")

    from briefing.settings import load_series_configs

    eligibility = resolve_event_eligibility(event, load_series_configs(app_settings))

    assert eligibility.eligible is False
    assert eligibility.reason == "recording_disabled"


def test_noted_config_rejects_invalid_boolean_string() -> None:
    with pytest.raises(PlanningError, match="Invalid boolean"):
        parse_noted_config("noted config:\nrecord: flase\n")


def test_assemble_manifest_validates_against_contract(app_settings, series_config) -> None:
    event = _event()
    eligibility = resolve_event_eligibility(event, [series_config])

    manifest = assemble_manifest(
        settings=app_settings,
        eligibility=eligibility,
        created_at=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )

    errors = list(manifest_validator().iter_errors(manifest))
    assert errors == []
    assert manifest["session_id"] == "2026-04-13T100000+1000-cas-strategy-meeting"
    assert manifest["paths"]["note_path"].endswith("2026-04-13-1000-cas-strategy-meeting.md")
    assert manifest["transcription"]["speaker_count_hint"] == 2


def test_assemble_manifest_rejects_naive_datetimes(app_settings, series_config) -> None:
    event = _event()
    event.start = datetime(2026, 4, 13, 10, 0, 0)
    eligibility = resolve_event_eligibility(event, [series_config])

    with pytest.raises(PlanningError, match="timezone offset"):
        assemble_manifest(
            settings=app_settings,
            eligibility=eligibility,
            created_at=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
        )


def test_plan_event_does_not_publish_invalid_manifest(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "bad-policy",
            "display_name": "Bad Policy",
            "note_slug": "bad-policy",
            "match": {"title_any": ["Bad Policy"]},
            "recording": {
                "recording_policy": {
                    "default_extension_minutes": -1,
                },
            },
        },
    )
    event = _event(title="Bad Policy")

    with pytest.raises(PlanningError, match="Generated manifest failed schema validation"):
        plan_event(
            app_settings,
            event,
            events=[event],
            now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
        )

    assert list(app_settings.meeting_intelligence.sessions_root.glob("*/manifest.json")) == []


def test_plan_event_prewrites_next_manifest_and_state(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
        },
    )
    _write_series(
        app_settings,
        {
            "series_id": "ops-review",
            "display_name": "Ops Review",
            "note_slug": "ops-review",
            "match": {"title_any": ["Ops Review"]},
            "recording": {
                "mode": "online",
                "participants": {"attendees_expected": 4},
            },
        },
    )
    first = _event()
    second = _event(uid="event-2", title="Ops Review", start="2026-04-13T11:30:00+10:00")

    result = plan_event(
        app_settings,
        first,
        events=[first, second],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )

    assert result.status == "planned"
    assert result.manifest_path is not None
    assert result.next_manifest_path is not None
    current = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert current["next_meeting"]["exists"] is True
    assert current["next_meeting"]["manifest_path"] == result.next_manifest_path
    assert Path(result.next_manifest_path).exists()
    plans = StateStore(app_settings).list_session_plans()
    assert {plan.event_uid for plan in plans} == {"event-1", "event-2"}


def test_invalidation_sweep_archives_cancelled_unlaunched_manifest(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
        },
    )
    event = _event()
    result = plan_event(
        app_settings,
        event,
        events=[event],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )
    assert result.manifest_path is not None

    invalidated = invalidate_stale_plans(
        app_settings,
        [],
        now=datetime.fromisoformat("2026-04-13T10:01:00+10:00"),
    )

    assert [plan.invalidation_reason for plan in invalidated] == ["event_cancelled"]
    assert not Path(result.manifest_path).exists()
    assert list((app_settings.repo_root / "archive" / "manifests").glob("*.json"))


def test_invalidation_sweep_ignores_missing_plan_outside_fetch_window(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
        },
    )
    event = _event(start="2026-04-13T16:00:00+10:00")
    result = plan_event(
        app_settings,
        event,
        events=[event],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )
    assert result.manifest_path is not None

    invalidated = invalidate_stale_plans(
        app_settings,
        [],
        now=datetime.fromisoformat("2026-04-13T10:01:00+10:00"),
        fetched_start=datetime.fromisoformat("2026-04-13T10:01:00+10:00"),
        fetched_end=datetime.fromisoformat("2026-04-13T13:01:00+10:00"),
    )

    assert invalidated == []
    assert Path(result.manifest_path).exists()
    plans = StateStore(app_settings).list_session_plans()
    assert len(plans) == 1
    assert plans[0].status == "planned"


def test_event_cancelled_state_can_replan_if_same_uid_reappears_at_new_start(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
        },
    )
    original = _event()
    result = plan_event(
        app_settings,
        original,
        events=[original],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )
    assert result.manifest_path is not None
    invalidated = invalidate_stale_plans(
        app_settings,
        [],
        now=datetime.fromisoformat("2026-04-13T10:01:00+10:00"),
    )
    assert [plan.invalidation_reason for plan in invalidated] == ["event_cancelled"]
    assert not Path(result.manifest_path).exists()

    moved = _event(start="2026-04-13T11:00:00+10:00")
    replanned = plan_event(
        app_settings,
        moved,
        events=[moved],
        now=datetime.fromisoformat("2026-04-13T10:58:30+10:00"),
    )

    assert replanned.status == "planned"
    assert replanned.manifest_path is not None
    assert replanned.manifest_path != result.manifest_path
    assert Path(replanned.manifest_path).exists()


def test_invalidation_sweep_clears_current_next_pointer_when_next_is_cancelled(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
        },
    )
    _write_series(
        app_settings,
        {
            "series_id": "ops-review",
            "display_name": "Ops Review",
            "note_slug": "ops-review",
            "match": {"title_any": ["Ops Review"]},
        },
    )
    first = _event()
    second = _event(uid="event-2", title="Ops Review", start="2026-04-13T11:30:00+10:00")
    result = plan_event(
        app_settings,
        first,
        events=[first, second],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )
    assert result.manifest_path is not None
    assert result.next_manifest_path is not None

    invalidated = invalidate_stale_plans(
        app_settings,
        [first],
        now=datetime.fromisoformat("2026-04-13T10:01:00+10:00"),
        fetched_start=datetime.fromisoformat("2026-04-13T10:01:00+10:00"),
        fetched_end=datetime.fromisoformat("2026-04-13T13:01:00+10:00"),
    )

    assert [plan.event_uid for plan in invalidated] == ["event-2"]
    assert not Path(result.next_manifest_path).exists()
    current = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert current["next_meeting"] == {"exists": False}


def test_plan_event_skips_invalid_next_candidate_without_writing_manifest(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
        },
    )
    _write_series(
        app_settings,
        {
            "series_id": "bad-next",
            "display_name": "Bad Next",
            "note_slug": "bad-next",
            "match": {"title_any": ["Bad Next"]},
            "recording": {
                "recording_policy": {
                    "default_extension_minutes": -1,
                },
            },
        },
    )
    first = _event()
    bad_next = _event(uid="event-2", title="Bad Next", start="2026-04-13T11:30:00+10:00")

    result = plan_event(
        app_settings,
        first,
        events=[first, bad_next],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )

    assert result.status == "planned"
    assert result.next_manifest_path is None
    assert result.manifest_path is not None
    current = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert current["next_meeting"] == {"exists": False}
    plans = StateStore(app_settings).list_session_plans()
    assert {plan.event_uid for plan in plans} == {"event-1"}
    assert not list(app_settings.meeting_intelligence.sessions_root.glob("*bad-next*"))


def test_invalidation_sweep_rewrites_in_tolerance_reschedule_in_place(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
        },
    )
    event = _event()
    result = plan_event(
        app_settings,
        event,
        events=[event],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )
    assert result.manifest_path is not None
    original_path = Path(result.manifest_path)
    original_session_id = json.loads(original_path.read_text(encoding="utf-8"))["session_id"]
    moved = _event(start="2026-04-13T10:02:00+10:00")

    invalidated = invalidate_stale_plans(
        app_settings,
        [moved],
        now=datetime.fromisoformat("2026-04-13T09:59:00+10:00"),
    )

    rewritten = json.loads(original_path.read_text(encoding="utf-8"))
    assert invalidated == []
    assert rewritten["session_id"] == original_session_id
    assert rewritten["meeting"]["start_time"] == "2026-04-13T10:02:00+10:00"
    assert rewritten["paths"]["session_dir"] == str(original_path.parent)


def test_invalidation_sweep_preserves_next_manifest_on_in_tolerance_reschedule(app_settings) -> None:
    _write_series(
        app_settings,
        {
            "series_id": "cas-strategy",
            "display_name": "CAS Strategy Meeting",
            "note_slug": "cas-strategy-meeting",
            "match": {"title_any": ["CAS Strategy Meeting"]},
        },
    )
    _write_series(
        app_settings,
        {
            "series_id": "ops-review",
            "display_name": "Ops Review",
            "note_slug": "ops-review",
            "match": {"title_any": ["Ops Review"]},
        },
    )
    first = _event()
    second = _event(uid="event-2", title="Ops Review", start="2026-04-13T11:30:00+10:00")
    result = plan_event(
        app_settings,
        first,
        events=[first, second],
        now=datetime.fromisoformat("2026-04-13T09:58:30+10:00"),
    )
    assert result.manifest_path is not None
    assert result.next_manifest_path is not None
    moved_first = _event(start="2026-04-13T10:02:00+10:00")

    invalidated = invalidate_stale_plans(
        app_settings,
        [moved_first, second],
        now=datetime.fromisoformat("2026-04-13T09:59:00+10:00"),
    )

    rewritten = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert invalidated == []
    assert rewritten["next_meeting"]["exists"] is True
    assert rewritten["next_meeting"]["event_id"] == "event-2"
    assert rewritten["next_meeting"]["manifest_path"] == result.next_manifest_path
