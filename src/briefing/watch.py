"""Long-running planning/watch loop for launching noted sessions."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .calendar import EventKitClient
from .models import MeetingEvent, SessionPlanState
from .planning import (
    invalidate_stale_plans,
    invalidate_recording_paused_plans,
    plan_allows_replanning_for_event,
    plan_blocks_replanning,
    plan_event,
    refresh_active_next_meeting_manifests,
)
from .retention import run_retention_sweep_best_effort
from .bootstrap import local_settings_path
from .settings import AppSettings, SettingsError, load_settings
from .state import StateStore


NowProvider = Callable[[], datetime]
SleepFn = Callable[[float], None]
SettingsLoader = Callable[[AppSettings], AppSettings]


def run_watch(
    settings: AppSettings,
    *,
    once: bool = False,
    dry_run: bool = False,
    now_provider: NowProvider | None = None,
    sleep_fn: SleepFn | None = None,
    calendar: EventKitClient | None = None,
    settings_loader: SettingsLoader | None = None,
) -> int:
    """Run the long-lived watch loop."""
    logger = logging.getLogger("briefing.watch")
    now_provider = now_provider or (lambda: datetime.now().astimezone())
    sleep_fn = sleep_fn or time.sleep
    settings_loader = settings_loader or _reload_settings_for_watch
    exit_code = 0

    # Reuse one EventKitClient (and its EKEventStore) for the lifetime of the watcher.
    # macOS refuses with EKCADErrorDomain 1021 ("too many EKEventStore instances") if a
    # long-running process keeps allocating new stores; per-cycle freshness is handled by
    # refresh_before_fetch=True, which calls store.reset() before each fetch.
    owns_calendar = calendar is None
    calendar_client = calendar or EventKitClient(settings, refresh_before_fetch=True)

    while True:
        exit_code = 0
        now = now_provider()
        try:
            settings = settings_loader(settings)
        except (FileNotFoundError, SettingsError, OSError) as exc:
            logger.exception("briefing watch settings reload failed: %s", exc)
            exit_code = 1
            if once:
                break
            sleep_fn(settings.meeting_intelligence.watch_poll_seconds)
            continue
        if owns_calendar:
            # Propagate reloaded settings without rebuilding the EventKit store.
            calendar_client.settings = settings

        try:
            state_store = StateStore(settings)
            run_retention_sweep_best_effort(settings, dry_run=dry_run)
            fetch_start = now - timedelta(days=1)
            fetch_end = now + timedelta(minutes=settings.meeting_intelligence.watch_lookahead_minutes)
            events = _fetch_watch_events(calendar_client, fetch_start, fetch_end)
            invalidated = invalidate_stale_plans(
                settings,
                events,
                now=now,
                state_store=state_store,
                fetched_start=fetch_start,
                fetched_end=fetch_end,
            )
            if invalidated:
                logger.info("Invalidation sweep archived %d stale plan(s)", len(invalidated))
            if _noted_scheduled_recording_paused():
                paused = invalidate_recording_paused_plans(
                    settings,
                    now=now,
                    state_store=state_store,
                )
                logger.info(
                    "Scheduled recording disabled; skipped noted launch planning%s",
                    f" and archived {len(paused)} unlaunched plan(s)" if paused else "",
                )
                if once:
                    break
                sleep_fn(settings.meeting_intelligence.watch_poll_seconds)
                continue
            refreshed = refresh_active_next_meeting_manifests(
                settings,
                events,
                now=now,
                state_store=state_store,
            )
            if refreshed:
                logger.info("Refreshed %d active next-meeting manifest(s)", len(refreshed))
            for event in sorted(events, key=lambda item: item.start):
                try:
                    _plan_and_maybe_launch(settings, state_store, event, events, now, dry_run=dry_run)
                except Exception as exc:
                    logger.exception(
                        "briefing watch event failed event_uid=%s title=%s: %s",
                        event.uid,
                        event.title,
                        exc,
                    )
                    exit_code = 1
        except Exception as exc:
            logger.exception("briefing watch cycle failed: %s", exc)
            exit_code = 1
            if once:
                break
        if once:
            break
        sleep_fn(settings.meeting_intelligence.watch_poll_seconds)
    return exit_code


def _reload_settings_for_watch(settings: AppSettings) -> AppSettings:
    """Reload the mutable local settings file for one watch poll.

    Tests and direct library callers often pass synthetic settings without a
    bootstrapped user_config/settings.toml. In that case, keep the supplied
    object. Normal CLI startup has already required this file to exist.
    """
    if not local_settings_path(settings.repo_root).exists():
        return settings
    return load_settings(settings.repo_root)


def _fetch_watch_events(
    calendar: EventKitClient,
    fetch_start: datetime,
    fetch_end: datetime,
) -> list[MeetingEvent]:
    return calendar.fetch_events(fetch_start, fetch_end)


def _noted_scheduled_recording_paused() -> bool:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "noted"
        / "scheduled-recordings.disabled"
    ).exists()


def _plan_and_maybe_launch(
    settings: AppSettings,
    state_store: StateStore,
    event: MeetingEvent,
    events: list[MeetingEvent],
    now: datetime,
    *,
    dry_run: bool,
) -> None:
    logger = logging.getLogger("briefing.watch")
    existing_plan = state_store.load_session_plan_for_event(event)

    # Retry sessions that were blocked by a concurrently running session. This check runs before
    # the pre-roll guard so retries continue while the event window is open, even after event.start.
    if existing_plan is not None and existing_plan.status == "launch_blocked":
        _retry_blocked_launch(settings, state_store, event, existing_plan, now, dry_run=dry_run)
        return

    if event.start <= now:
        return
    pre_roll_at = event.start - timedelta(seconds=settings.meeting_intelligence.pre_roll_seconds)
    if now < pre_roll_at:
        return

    if (
        existing_plan
        and plan_blocks_replanning(existing_plan)
        and not plan_allows_replanning_for_event(existing_plan, event)
    ):
        logger.info(
            "Skipping launch for event_uid=%s: existing plan status=%s launched_at=%s",
            event.uid,
            existing_plan.status,
            existing_plan.launched_at,
        )
        return

    result = plan_event(settings, event, events=events, now=now, state_store=state_store)
    logger.info("Session plan result: %s", result.to_json_line())
    if result.skip_reason == "recording_location_unknown":
        logger.warning(
            "Recording skipped: location routing is configured but this machine is not mapped. "
            "Run `briefing validate` to diagnose. event_uid=%s title=%r",
            event.uid,
            event.title,
        )
    if result.status != "planned" or not result.session_id or not result.manifest_path:
        return

    plan = state_store.load_session_plan_for_event(event)
    if plan is None or plan.launched_at:
        return

    if dry_run:
        logger.info(
            "Dry-run launch skipped command=%s args=%s session_dir=%s",
            settings.meeting_intelligence.noted_command,
            ["start", "--manifest", result.manifest_path],
            result.session_dir,
        )
        logger.info(
            "boundary=%s %s",
            "noted_start_dry_run",
            json.dumps(
                {
                    "event_uid": event.uid,
                    "session_id": result.session_id,
                    "manifest_path": result.manifest_path,
                    "session_dir": result.session_dir,
                    "command": settings.meeting_intelligence.noted_command,
                    "args": ["start", "--manifest", result.manifest_path],
                    "dry_run": True,
                },
                sort_keys=True,
            ),
        )
        return

    command = [settings.meeting_intelligence.noted_command, "start", "--manifest", result.manifest_path]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    launch_status = _launch_status_from_noted_start(completed, expected_session_id=result.session_id)
    updated = replace(
        plan,
        status=launch_status,
        launched_at=now.isoformat() if launch_status == "launched" else plan.launched_at,
        launch_exit_code=completed.returncode,
    )
    state_store.save_session_plan(updated)
    logger.info(
        "noted start completed: %s",
        json.dumps(
            {
                "command": command[0],
                "args": command[1:],
                "exit_code": completed.returncode,
                "session_dir": result.session_dir,
                "manifest_path": result.manifest_path,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "plan": asdict(updated),
            },
            sort_keys=True,
        ),
    )
    logger.info(
        "boundary=%s %s",
        "noted_start",
        json.dumps(
            {
                "event_uid": event.uid,
                "session_id": result.session_id,
                "manifest_path": result.manifest_path,
                "session_dir": result.session_dir,
                "command": command[0],
                "args": command[1:],
                "exit_code": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "plan_status": updated.status,
            },
            sort_keys=True,
        ),
    )


def _retry_blocked_launch(
    settings: AppSettings,
    state_store: StateStore,
    event: MeetingEvent,
    plan: SessionPlanState,
    now: datetime,
    *,
    dry_run: bool,
) -> None:
    logger = logging.getLogger("briefing.watch")
    if event.end is not None and event.end <= now:
        completion_path = _write_missed_launch_completion(plan, now)
        updated = replace(
            plan,
            status="invalidated",
            invalidated_at=now.isoformat(),
            invalidation_reason="launch_blocked_window_closed",
        )
        state_store.save_session_plan(updated)
        logger.warning(
            "launch_blocked: event window closed without starting session_id=%s completion=%s",
            plan.session_id,
            completion_path,
        )
        return
    if dry_run:
        logger.info(
            "Dry-run: would retry blocked launch session_id=%s manifest_path=%s",
            plan.session_id,
            plan.manifest_path,
        )
        return
    command = [settings.meeting_intelligence.noted_command, "start", "--manifest", plan.manifest_path]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    launch_status = _launch_status_from_noted_start(completed, expected_session_id=plan.session_id)
    if launch_status == "launch_blocked":
        logger.info(
            "noted start still blocked: session_id=%s exit_code=%d stdout=%r",
            plan.session_id,
            completed.returncode,
            completed.stdout.strip(),
        )
        return
    updated = replace(
        plan,
        status=launch_status,
        launched_at=now.isoformat() if launch_status == "launched" else plan.launched_at,
        launch_exit_code=completed.returncode,
    )
    state_store.save_session_plan(updated)
    logger.info(
        "noted start (retry) completed: %s",
        json.dumps(
            {
                "session_id": plan.session_id,
                "exit_code": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "plan_status": updated.status,
            },
            sort_keys=True,
        ),
    )


def _launch_status_from_noted_start(
    completed: subprocess.CompletedProcess[str],
    *,
    expected_session_id: str,
) -> str:
    if completed.returncode == 0:
        return "launched"
    if completed.returncode != 5:
        return "launch_failed"
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return "launch_failed"
    if not isinstance(payload, dict) or payload.get("error") != "session_already_running":
        return "launch_failed"
    # running_session_id is the new field; fall back to session_id for older noted builds
    running_id = payload.get("running_session_id") or payload.get("session_id")
    if running_id == expected_session_id:
        return "launched"
    return "launch_blocked"


def _write_missed_launch_completion(plan: SessionPlanState, now: datetime) -> Path:
    output_dir = Path(plan.session_dir) / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    completion_path = output_dir / "completion.json"
    payload = {
        "schema_version": "1.0",
        "session_id": plan.session_id,
        "manifest_schema_version": _manifest_schema_version(plan),
        "terminal_status": "failed",
        "stop_reason": "startup_failure",
        "audio_capture_ok": False,
        "transcript_ok": False,
        "diarization_ok": False,
        "warnings": [],
        "errors": ["launch_blocked_window_closed"],
        "completed_at": now.isoformat(),
    }
    completion_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return completion_path


def _manifest_schema_version(plan: SessionPlanState) -> str:
    try:
        manifest = json.loads(Path(plan.manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "2.0"
    version = manifest.get("schema_version") if isinstance(manifest, dict) else None
    return str(version) if version is not None else "2.0"
