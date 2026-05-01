"""Session planning and manifest assembly for noted handoff."""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .calendar import EventKitClient
from .location_routing import normalize_location_type, resolve_location_route
from .matching import match_series
from .models import MeetingEvent, RecordingConfig, RecordingPolicyConfig, SeriesConfig, SessionPlanState
from .recording_config import RecordingConfigError, parse_noted_config as _parse_noted_config
from .runner import build_output_filename
from .settings import AppSettings, load_series_configs
from .state import StateStore
from .utils import ensure_directory, expand_path, slugify


class PlanningError(RuntimeError):
    """Raised when session planning cannot continue."""


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """Resolved recording eligibility for one calendar event."""

    eligible: bool
    reason: str | None
    event: MeetingEvent
    series: SeriesConfig | None
    recording: RecordingConfig | None
    one_off: bool = False
    target_location_type: str | None = None
    local_location_type: str | None = None


@dataclass(frozen=True, slots=True)
class SessionPlanResult:
    """Machine-readable result for one planning attempt."""

    ok: bool
    status: str
    event_uid: str | None
    series_id: str | None = None
    session_id: str | None = None
    manifest_path: str | None = None
    session_dir: str | None = None
    note_path: str | None = None
    skip_reason: str | None = None
    next_manifest_path: str | None = None

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "vendor"
    / "contracts"
    / "contracts"
    / "schemas"
    / "manifest.v1.json"
)
_VALIDATOR: Draft202012Validator | None = None
_VALID_MODES = {"in_person", "online", "hybrid"}
_VALID_AUDIO_STRATEGIES = {"room_mic", "mic_plus_system"}
_VALID_ASR_BACKENDS = {"whisperkit", "fluidaudio-parakeet", "sfspeech"}
_REPLAN_BLOCKING_STATUSES = {"invalidated", "launched", "launch_failed"}


def manifest_validator() -> Draft202012Validator:
    """Return the pinned manifest schema validator."""
    global _VALIDATOR
    if _VALIDATOR is None:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        _VALIDATOR = Draft202012Validator(schema, format_checker=FormatChecker())
    return _VALIDATOR


def parse_noted_config(notes: str | None) -> RecordingConfig | None:
    """Parse a case-insensitive ``noted config`` YAML marker from event notes."""
    try:
        return _parse_noted_config(notes)
    except RecordingConfigError as exc:
        raise PlanningError(str(exc)) from exc


def resolve_event_eligibility(
    event: MeetingEvent,
    series_configs: list[SeriesConfig],
    settings: AppSettings | None = None,
) -> EligibilityResult:
    """Resolve whether an event should enter the automated recording path."""
    marker = parse_noted_config(event.notes)
    matches = match_series(event, series_configs)
    if len(matches) > 1:
        return EligibilityResult(False, "multiple_series_matches", event, None, None)

    if matches:
        series = matches[0]
        recording = merge_recording_config(series.recording, marker)
        if recording.record is False:
            return EligibilityResult(False, "recording_disabled", event, series, recording)
        route_skip = _recording_location_skip_reason(settings, recording)
        if route_skip:
            reason, target, local = route_skip
            return EligibilityResult(
                False,
                reason,
                event,
                series,
                recording,
                target_location_type=target,
                local_location_type=local,
            )
        return EligibilityResult(True, None, event, series, recording)

    if marker is None:
        return EligibilityResult(False, "no_series_or_noted_config", event, None, None)
    if marker.record is False:
        return EligibilityResult(False, "recording_disabled", event, None, marker, one_off=True)
    route_skip = _recording_location_skip_reason(settings, marker)
    if route_skip:
        reason, target, local = route_skip
        return EligibilityResult(
            False,
            reason,
            event,
            None,
            marker,
            one_off=True,
            target_location_type=target,
            local_location_type=local,
        )
    return EligibilityResult(True, None, event, None, marker, one_off=True)


def merge_recording_config(base: RecordingConfig, override: RecordingConfig | None) -> RecordingConfig:
    """Merge recording metadata field by field."""
    if override is None:
        return base
    return RecordingConfig(
        record=_choose(override.record, base.record),
        location_type=_choose(override.location_type, base.location_type),
        mode=_choose(override.mode, base.mode),
        audio_strategy=_choose(override.audio_strategy, base.audio_strategy),
        host_name=_choose(override.host_name, base.host_name),
        attendees_expected=_choose(override.attendees_expected, base.attendees_expected),
        participant_names=override.participant_names or list(base.participant_names),
        language=_choose(override.language, base.language),
        asr_backend=_choose(override.asr_backend, base.asr_backend),
        diarization_enabled=_choose(override.diarization_enabled, base.diarization_enabled),
        speaker_count_hint=_choose(override.speaker_count_hint, base.speaker_count_hint),
        note_dir=_choose(override.note_dir, base.note_dir),
        note_slug=_choose(override.note_slug, base.note_slug),
        recording_policy=RecordingPolicyConfig(
            auto_start=_choose(override.recording_policy.auto_start, base.recording_policy.auto_start),
            auto_stop=_choose(override.recording_policy.auto_stop, base.recording_policy.auto_stop),
            default_extension_minutes=_choose(
                override.recording_policy.default_extension_minutes,
                base.recording_policy.default_extension_minutes,
            ),
            max_single_extension_minutes=_choose(
                override.recording_policy.max_single_extension_minutes,
                base.recording_policy.max_single_extension_minutes,
            ),
            pre_end_prompt_minutes=_choose(
                override.recording_policy.pre_end_prompt_minutes,
                base.recording_policy.pre_end_prompt_minutes,
            ),
            no_interaction_grace_minutes=_choose(
                override.recording_policy.no_interaction_grace_minutes,
                base.recording_policy.no_interaction_grace_minutes,
            ),
        ),
    )


def _recording_location_skip_reason(
    settings: AppSettings | None,
    recording: RecordingConfig,
) -> tuple[str, str, str | None] | None:
    if settings is None:
        return None
    route = resolve_location_route(
        target_location_type=recording.location_type,
        default_location_type=settings.meeting_intelligence.default_location_type,
        local_location_type=settings.meeting_intelligence.local_location_type,
        location_type_by_host=settings.meeting_intelligence.location_type_by_host,
        reason_prefix="recording",
    )
    if route.skip_reason is None:
        return None
    assert route.target_location_type is not None
    return (route.skip_reason, route.target_location_type, route.local_location_type)


def _target_location_type(settings: AppSettings, recording: RecordingConfig) -> str | None:
    return normalize_location_type(
        recording.location_type or settings.meeting_intelligence.default_location_type
    )


def plan_event_by_id(
    settings: AppSettings,
    event_id: str,
    *,
    now: datetime | None = None,
    calendar: EventKitClient | None = None,
) -> SessionPlanResult:
    """Find an event by id, write its manifest, and prewrite next manifest when eligible."""
    now = now or datetime.now().astimezone()
    calendar = calendar or EventKitClient(settings)
    start = now - timedelta(days=1)
    end = now + timedelta(days=settings.calendar.lookback_days_for_init)
    events = calendar.fetch_events(start, end)
    event = next((candidate for candidate in events if candidate.uid == event_id), None)
    if event is None:
        return SessionPlanResult(False, "not_found", event_id, skip_reason="event_not_found")
    return plan_event(settings, event, events=events, now=now)


def plan_event(
    settings: AppSettings,
    event: MeetingEvent,
    *,
    events: list[MeetingEvent],
    now: datetime | None = None,
    state_store: StateStore | None = None,
) -> SessionPlanResult:
    """Write a manifest for one eligible event."""
    now = now or datetime.now().astimezone()
    series_configs = load_series_configs(settings)
    eligibility = resolve_event_eligibility(event, series_configs, settings)
    if not eligibility.eligible or eligibility.recording is None:
        return SessionPlanResult(
            ok=True,
            status="skipped",
            event_uid=event.uid,
            series_id=eligibility.series.series_id if eligibility.series else None,
            skip_reason=eligibility.reason,
        )

    store = state_store or StateStore(settings)
    existing_plan = store.load_session_plan_for_event(event)
    if existing_plan and not plan_allows_replanning_for_event(existing_plan, event):
        if plan_blocks_replanning(existing_plan):
            return _result_from_existing_plan(
                event=event,
                series=eligibility.series,
                plan=existing_plan,
                skip_reason=existing_plan.invalidation_reason or "launch_already_attempted",
            )
        if existing_plan.status == "planned" and Path(existing_plan.manifest_path).exists():
            return _result_from_existing_plan(
                event=event,
                series=eligibility.series,
                plan=existing_plan,
                skip_reason=None,
            )

    # Write primary manifest first so that a failure here commits nothing
    manifest = assemble_manifest(settings=settings, eligibility=eligibility, created_at=now)
    manifest_path = write_manifest(settings, manifest)
    plan_state = _plan_state_from_manifest(store, event, manifest, manifest_path, now)
    store.save_session_plan(plan_state)

    # Prewrite next manifest now that primary is safely on disk; patch primary if a next exists
    next_event, next_result = _prewrite_next_manifest(settings, event, events, series_configs, now, store)
    if next_event is not None:
        manifest["next_meeting"] = _next_meeting(next_event, next_result.manifest_path if next_result else None)
        _validate_manifest_payload(manifest, manifest_path)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return SessionPlanResult(
        ok=True,
        status="planned",
        event_uid=event.uid,
        series_id=eligibility.series.series_id if eligibility.series else None,
        session_id=str(manifest["session_id"]),
        manifest_path=str(manifest_path),
        session_dir=str(manifest["paths"]["session_dir"]),
        note_path=str(manifest["paths"]["note_path"]),
        next_manifest_path=next_result.manifest_path if next_result else None,
    )


def plan_blocks_replanning(plan: SessionPlanState) -> bool:
    """Return whether a stored plan must not be overwritten by automatic planning."""
    return bool(plan.launched_at) or plan.status in _REPLAN_BLOCKING_STATUSES


def plan_allows_replanning_for_event(plan: SessionPlanState, event: MeetingEvent) -> bool:
    """Return whether a stored plan is scoped to a different occurrence and may be superseded.

    A different start time always permits replanning: the event UID is reused when macOS Calendar
    copies an event, so the same UID can legitimately refer to a new occurrence at a new time.
    """
    if plan.start_iso != event.start.isoformat():
        return True
    return (
        (
            plan.status == "invalidated"
            and plan.invalidation_reason in {
                "event_cancelled",
                "event_rescheduled_out_of_tolerance",
                "scheduled_recording_disabled",
                "recording_disabled",
                "recording_location_mismatch",
                "recording_location_unknown",
                "event_rescheduled_became_ineligible",
                "event_became_ineligible",
            }
        )
        or plan.status == "launch_failed"
    )


def _result_from_existing_plan(
    *,
    event: MeetingEvent,
    series: SeriesConfig | None,
    plan: SessionPlanState,
    skip_reason: str | None,
) -> SessionPlanResult:
    """Convert persisted planning state into the public machine-readable result."""
    return SessionPlanResult(
        ok=True,
        status=plan.status,
        event_uid=event.uid,
        series_id=series.series_id if series else None,
        session_id=plan.session_id,
        manifest_path=plan.manifest_path,
        session_dir=plan.session_dir,
        note_path=plan.note_path,
        skip_reason=skip_reason,
    )


def assemble_manifest(
    *,
    settings: AppSettings,
    eligibility: EligibilityResult,
    created_at: datetime,
    next_event: MeetingEvent | None = None,
    next_manifest_path: str | None = None,
) -> dict[str, Any]:
    """Assemble the manifest.v1 payload for one eligible event."""
    event = eligibility.event
    recording = eligibility.recording or RecordingConfig()
    _reject_naive(event.start, "event.start")
    if event.end is not None:
        _reject_naive(event.end, "event.end")
    _reject_naive(created_at, "created_at")

    title_slug = recording.note_slug or (eligibility.series.note_slug if eligibility.series else slugify(event.title))
    session_id = f"{event.start.strftime('%Y-%m-%dT%H%M%S%z')}-{slugify(title_slug)}"
    session_dir = settings.meeting_intelligence.sessions_root / session_id
    note_path = _note_path(settings, eligibility, title_slug)
    participants = _participants(settings, event, recording)
    mode = _mode(settings, recording)
    transcription = _transcription(settings, recording, participants)

    meeting: dict[str, Any] = {
        "event_id": event.uid,
        "title": event.title,
        "start_time": event.start.isoformat(),
        "scheduled_end_time": event.end.isoformat() if event.end else None,
        "timezone": _timezone_name(event.start),
    }
    if eligibility.series:
        meeting["series_id"] = eligibility.series.series_id
    if event.location:
        meeting["location"] = event.location
    target_location_type = _target_location_type(settings, recording)
    if target_location_type:
        meeting["location_type"] = target_location_type

    return {
        "schema_version": "1.0",
        "session_id": session_id,
        "created_at": created_at.isoformat(),
        "meeting": meeting,
        "mode": mode,
        "participants": participants,
        "recording_policy": _recording_policy(settings, recording),
        "next_meeting": _next_meeting(next_event, next_manifest_path),
        "paths": {
            "session_dir": str(session_dir),
            "output_dir": str(session_dir / "outputs"),
            "note_path": str(note_path),
        },
        "transcription": transcription,
        "hooks": {"completion_callback": None},
    }


def write_manifest(settings: AppSettings, manifest: dict[str, Any]) -> Path:
    """Write a manifest under the planned session directory."""
    manifest_path = _manifest_path(manifest)
    _validate_manifest_payload(manifest, manifest_path)
    session_dir = ensure_directory(manifest_path.parent)
    ensure_directory(session_dir / "outputs")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def invalidate_stale_plans(
    settings: AppSettings,
    events: list[MeetingEvent],
    *,
    now: datetime | None = None,
    state_store: StateStore | None = None,
    fetched_start: datetime | None = None,
    fetched_end: datetime | None = None,
) -> list[SessionPlanState]:
    """Archive stale, unlaunched manifest plans and rewrite in-tolerance reschedules."""
    now = now or datetime.now().astimezone()
    store = state_store or StateStore(settings)
    events_by_uid = {event.uid: event for event in events}
    series_configs = load_series_configs(settings)
    invalidated: list[SessionPlanState] = []
    for plan in store.list_session_plans():
        if plan.status != "planned" or plan.launched_at:
            continue
        current = events_by_uid.get(plan.event_uid)
        if current is None:
            if not _plan_was_within_fetch_window(plan, fetched_start, fetched_end):
                continue
            invalidated.append(_invalidate_plan(settings, store, plan, now, "event_cancelled"))
            continue
        eligibility = resolve_event_eligibility(current, series_configs, settings)
        if not eligibility.eligible:
            invalidated.append(
                _invalidate_plan(
                    settings,
                    store,
                    plan,
                    now,
                    eligibility.reason or "event_became_ineligible",
                )
            )
            continue
        planned_start = datetime.fromisoformat(plan.start_iso)
        delta = abs((current.start - planned_start).total_seconds())
        if delta > settings.meeting_intelligence.reschedule_tolerance_seconds:
            invalidated.append(_invalidate_plan(settings, store, plan, now, "event_rescheduled_out_of_tolerance"))
            continue
        if current.start != planned_start:
            _rewrite_plan_for_reschedule(settings, store, plan, current, events, now)
    return invalidated


def invalidate_recording_paused_plans(
    settings: AppSettings,
    *,
    now: datetime | None = None,
    state_store: StateStore | None = None,
) -> list[SessionPlanState]:
    """Archive unlaunched plans when scheduled recording is globally paused."""
    now = now or datetime.now().astimezone()
    store = state_store or StateStore(settings)
    invalidated: list[SessionPlanState] = []
    for plan in store.list_session_plans():
        if plan.status != "planned" or plan.launched_at:
            continue
        invalidated.append(_invalidate_plan(settings, store, plan, now, "scheduled_recording_disabled"))
    return invalidated


def _prewrite_next_manifest(
    settings: AppSettings,
    current_event: MeetingEvent,
    events: list[MeetingEvent],
    series_configs: list[SeriesConfig],
    now: datetime,
    state_store: StateStore,
) -> tuple[MeetingEvent | None, SessionPlanResult | None]:
    for candidate in sorted(events, key=lambda item: item.start):
        if candidate.uid == current_event.uid:
            continue
        if candidate.start <= current_event.start:
            continue
        try:
            eligibility = resolve_event_eligibility(candidate, series_configs, settings)
            if not eligibility.eligible or eligibility.recording is None:
                continue
            existing = state_store.load_session_plan_for_event(candidate)
            if existing and not plan_allows_replanning_for_event(existing, candidate):
                if existing.status == "invalidated":
                    continue
                if plan_blocks_replanning(existing) or Path(existing.manifest_path).exists():
                    return candidate, _result_from_existing_plan(
                        event=candidate,
                        series=eligibility.series,
                        plan=existing,
                        skip_reason=(
                            existing.invalidation_reason
                            if existing.status == "invalidated"
                            else None
                        ),
                    )
            manifest = assemble_manifest(settings=settings, eligibility=eligibility, created_at=now)
            manifest_path = write_manifest(settings, manifest)
        except PlanningError:
            logging.getLogger("briefing.watch").exception(
                "Skipping invalid next-meeting candidate event_uid=%s title=%s",
                candidate.uid,
                candidate.title,
            )
            continue
        state_store.save_session_plan(
            _plan_state_from_manifest(state_store, candidate, manifest, manifest_path, now)
        )
        return candidate, SessionPlanResult(
            ok=True,
            status="planned",
            event_uid=candidate.uid,
            series_id=eligibility.series.series_id if eligibility.series else None,
            session_id=str(manifest["session_id"]),
            manifest_path=str(manifest_path),
            session_dir=str(manifest["paths"]["session_dir"]),
            note_path=str(manifest["paths"]["note_path"]),
        )
    return None, None


def refresh_active_next_meeting_manifests(
    settings: AppSettings,
    events: list[MeetingEvent],
    *,
    now: datetime,
    state_store: StateStore,
) -> list[Path]:
    """Refresh next-meeting pointers for meetings that are currently in progress."""
    logger = logging.getLogger("briefing.watch")
    series_configs = load_series_configs(settings)
    events_by_uid = {event.uid: event for event in events}
    updated_paths: list[Path] = []

    for plan in state_store.list_session_plans():
        if plan.status not in {"planned", "launched"}:
            continue
        current_event = events_by_uid.get(plan.event_uid)
        if current_event is None or not _event_is_active(current_event, now):
            continue
        manifest_path = Path(plan.manifest_path)
        if not manifest_path.exists():
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            next_event, next_result = _prewrite_next_manifest(
                settings,
                current_event,
                events,
                series_configs,
                now,
                state_store,
            )
            next_manifest_path = next_result.manifest_path if next_result else None
            next_meeting = _next_meeting(next_event, next_manifest_path)
            if manifest.get("next_meeting") == next_meeting:
                continue
            manifest["next_meeting"] = next_meeting
            manifest["created_at"] = now.isoformat()
            _validate_manifest_payload(manifest, manifest_path)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            logger.exception(
                "Failed to refresh active next_meeting event_uid=%s manifest=%s",
                plan.event_uid,
                manifest_path,
            )
            continue

        updated_paths.append(manifest_path)
        logger.info("Refreshed active next_meeting event_uid=%s manifest=%s", plan.event_uid, manifest_path)
    return updated_paths


def _plan_state_from_manifest(
    store: StateStore,
    event: MeetingEvent,
    manifest: dict[str, Any],
    manifest_path: Path,
    now: datetime,
) -> SessionPlanState:
    return SessionPlanState(
        occurrence_key=store.occurrence_key(event),
        event_uid=event.uid,
        start_iso=event.start.isoformat(),
        title=event.title,
        session_id=str(manifest["session_id"]),
        manifest_path=str(manifest_path),
        session_dir=str(manifest["paths"]["session_dir"]),
        note_path=str(manifest["paths"]["note_path"]),
        planned_at=now.isoformat(),
    )


def _validate_manifest_payload(payload: dict[str, Any], path: Path) -> None:
    errors = sorted(manifest_validator().iter_errors(payload), key=lambda err: list(err.absolute_path))
    if errors:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
            for err in errors[:5]
        )
        raise PlanningError(f"Generated manifest failed schema validation for {path}: {details}")


def _manifest_path(manifest: dict[str, Any]) -> Path:
    return Path(str(manifest["paths"]["session_dir"])) / "manifest.json"


def _event_is_active(event: MeetingEvent, now: datetime) -> bool:
    if event.start > now:
        return False
    return event.end is None or event.end > now


def _note_path(settings: AppSettings, eligibility: EligibilityResult, title_slug: str) -> Path:
    if eligibility.recording and eligibility.recording.note_dir:
        note_dir = expand_path(eligibility.recording.note_dir, settings.repo_root)
    elif eligibility.one_off:
        note_dir = settings.meeting_intelligence.one_off_note_dir
    else:
        note_dir = settings.paths.meeting_notes_dir
    if eligibility.series:
        return note_dir / build_output_filename(eligibility.event, replace(eligibility.series, note_slug=title_slug))
    return note_dir / f"{eligibility.event.start:%Y-%m-%d-%H%M}-{title_slug}.md"


def _participants(settings: AppSettings, event: MeetingEvent, recording: RecordingConfig) -> dict[str, Any]:
    names = _participant_names(event, recording)
    host_name = recording.host_name or event.organizer_name or settings.meeting_intelligence.default_host_name
    participants: dict[str, Any] = {
        "host_name": host_name,
        "names_are_hints_only": True,
    }
    attendees_expected = recording.attendees_expected or (len(names) if names else None)
    if attendees_expected:
        participants["attendees_expected"] = max(1, attendees_expected)
    if names:
        participants["participant_names"] = names
    return participants


def _participant_names(event: MeetingEvent, recording: RecordingConfig) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for value in recording.participant_names:
        text = str(value).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            names.append(text)
    for value in [event.organizer_name, *(attendee.get("name") for attendee in event.attendees)]:
        text = str(value or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            names.append(text)
    return names


def _mode(settings: AppSettings, recording: RecordingConfig) -> dict[str, str]:
    mode_type = recording.mode or settings.meeting_intelligence.default_mode
    if mode_type not in _VALID_MODES:
        raise PlanningError(f"Unsupported recording mode: {mode_type}")
    audio_strategy = recording.audio_strategy or _default_audio_strategy(mode_type)
    if audio_strategy not in _VALID_AUDIO_STRATEGIES:
        raise PlanningError(f"Unsupported audio strategy: {audio_strategy}")
    return {"type": mode_type, "audio_strategy": audio_strategy}


def _default_audio_strategy(mode_type: str) -> str:
    if mode_type == "online":
        return "mic_plus_system"
    return "room_mic"


def _recording_policy(settings: AppSettings, recording: RecordingConfig) -> dict[str, int | bool]:
    policy = recording.recording_policy
    return {
        "auto_start": _choose(policy.auto_start, settings.meeting_intelligence.auto_start),
        "auto_stop": _choose(policy.auto_stop, settings.meeting_intelligence.auto_stop),
        "default_extension_minutes": _choose(
            policy.default_extension_minutes,
            settings.meeting_intelligence.default_extension_minutes,
        ),
        "max_single_extension_minutes": _choose(
            policy.max_single_extension_minutes,
            settings.meeting_intelligence.max_single_extension_minutes,
        ),
        "pre_end_prompt_minutes": _choose(
            policy.pre_end_prompt_minutes,
            settings.meeting_intelligence.pre_end_prompt_minutes,
        ),
        "no_interaction_grace_minutes": _choose(
            policy.no_interaction_grace_minutes,
            settings.meeting_intelligence.no_interaction_grace_minutes,
        ),
    }


def _transcription(
    settings: AppSettings,
    recording: RecordingConfig,
    participants: dict[str, Any],
) -> dict[str, Any]:
    asr_backend = recording.asr_backend or settings.meeting_intelligence.default_asr_backend
    if asr_backend not in _VALID_ASR_BACKENDS:
        raise PlanningError(f"Unsupported ASR backend: {asr_backend}")
    payload: dict[str, Any] = {
        "asr_backend": asr_backend,
        "diarization_enabled": _choose(
            recording.diarization_enabled,
            settings.meeting_intelligence.default_diarization_enabled,
        ),
        "language": recording.language or settings.meeting_intelligence.default_language,
    }
    hint = recording.speaker_count_hint or participants.get("attendees_expected")
    if not hint and participants.get("participant_names"):
        hint = len(participants["participant_names"])
    if hint:
        payload["speaker_count_hint"] = max(1, int(hint))
    return payload


def _next_meeting(event: MeetingEvent | None, manifest_path: str | None) -> dict[str, Any]:
    if event is None:
        return {"exists": False}
    payload = {
        "exists": True,
        "event_id": event.uid,
        "title": event.title,
        "start_time": event.start.isoformat(),
    }
    if manifest_path:
        payload["manifest_path"] = manifest_path
    return payload


def _timezone_name(value: datetime) -> str:
    tzinfo = value.tzinfo
    key = getattr(tzinfo, "key", None)
    if key:
        return str(key)
    name = value.tzname()
    if name:
        return name
    return time.tzname[0] if time.tzname else "local"


def _reject_naive(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PlanningError(f"{name} must have an explicit timezone offset")


def _invalidate_plan(
    settings: AppSettings,
    store: StateStore,
    plan: SessionPlanState,
    now: datetime,
    reason: str,
) -> SessionPlanState:
    logger = logging.getLogger("briefing.watch")
    manifest_path = Path(plan.manifest_path)
    if manifest_path.exists():
        archive_dir = ensure_directory(settings.repo_root / "archive" / "manifests")
        archive_path = archive_dir / f"{now.strftime('%Y%m%dT%H%M%S')}-{manifest_path.parent.name}-manifest.json"
        shutil.move(str(manifest_path), archive_path)
        logger.info("Archived invalidated manifest %s -> %s", manifest_path, archive_path)
    updated = replace(
        plan,
        status="invalidated",
        invalidated_at=now.isoformat(),
        invalidation_reason=reason,
    )
    store.save_session_plan(updated)
    _clear_next_meeting_references(settings, store, updated, now)
    logger.info("Invalidated manifest plan event_uid=%s reason=%s", plan.event_uid, reason)
    return updated


def _plan_was_within_fetch_window(
    plan: SessionPlanState,
    fetched_start: datetime | None,
    fetched_end: datetime | None,
) -> bool:
    if fetched_start is None or fetched_end is None:
        return True
    planned_start = datetime.fromisoformat(plan.start_iso)
    return fetched_start <= planned_start <= fetched_end


def _clear_next_meeting_references(
    settings: AppSettings,
    store: StateStore,
    invalidated: SessionPlanState,
    now: datetime,
) -> None:
    """Remove stale switch-next pointers to an invalidated manifest."""
    logger = logging.getLogger("briefing.watch")
    invalidated_manifest_path = str(Path(invalidated.manifest_path))
    for candidate in store.list_session_plans():
        if candidate.event_uid == invalidated.event_uid:
            continue
        manifest_path = Path(candidate.manifest_path)
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        next_meeting = manifest.get("next_meeting")
        if not isinstance(next_meeting, dict):
            continue
        points_to_invalidated = (
            next_meeting.get("event_id") == invalidated.event_uid
            or next_meeting.get("manifest_path") == invalidated_manifest_path
        )
        if not points_to_invalidated:
            continue
        manifest["next_meeting"] = {"exists": False}
        manifest["created_at"] = now.isoformat()
        _validate_manifest_payload(manifest, manifest_path)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        logger.info(
            "Cleared stale next_meeting reference event_uid=%s manifest=%s invalidated_event_uid=%s",
            candidate.event_uid,
            manifest_path,
            invalidated.event_uid,
        )


def _rewrite_plan_for_reschedule(
    settings: AppSettings,
    store: StateStore,
    plan: SessionPlanState,
    event: MeetingEvent,
    events: list[MeetingEvent],
    now: datetime,
) -> None:
    logger = logging.getLogger("briefing.watch")
    series_configs = load_series_configs(settings)
    eligibility = resolve_event_eligibility(event, series_configs, settings)
    if not eligibility.eligible or eligibility.recording is None:
        _invalidate_plan(settings, store, plan, now, "event_rescheduled_became_ineligible")
        return

    next_event, next_result = _prewrite_next_manifest(settings, event, events, series_configs, now, store)
    manifest = assemble_manifest(
        settings=settings,
        eligibility=eligibility,
        created_at=now,
        next_event=next_event,
        next_manifest_path=next_result.manifest_path if next_result else None,
    )
    manifest["session_id"] = plan.session_id
    manifest["paths"]["session_dir"] = plan.session_dir
    manifest["paths"]["output_dir"] = str(Path(plan.session_dir) / "outputs")
    manifest_path = Path(plan.manifest_path)
    _validate_manifest_payload(manifest, manifest_path)
    ensure_directory(manifest_path.parent)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    store.save_session_plan(
        replace(
            plan,
            occurrence_key=store.occurrence_key(event),
            start_iso=event.start.isoformat(),
            note_path=str(manifest["paths"]["note_path"]),
            planned_at=now.isoformat(),
        )
    )
    logger.info(
        "Rewrote in-tolerance rescheduled manifest event_uid=%s old_start=%s new_start=%s manifest=%s",
        event.uid,
        plan.start_iso,
        event.start.isoformat(),
        manifest_path,
    )


def _choose(first: Any, second: Any) -> Any:
    return first if first is not None else second
