"""Long-running planning/watch loop for launching noted sessions."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from typing import Callable

from .calendar import EventKitClient
from .models import MeetingEvent
from .planning import (
    invalidate_stale_plans,
    plan_allows_replanning_for_event,
    plan_blocks_replanning,
    plan_event,
    refresh_active_next_meeting_manifests,
)
from .settings import AppSettings
from .state import StateStore


NowProvider = Callable[[], datetime]
SleepFn = Callable[[float], None]


def run_watch(
    settings: AppSettings,
    *,
    once: bool = False,
    dry_run: bool = False,
    now_provider: NowProvider | None = None,
    sleep_fn: SleepFn | None = None,
    calendar: EventKitClient | None = None,
) -> int:
    """Run the long-lived watch loop."""
    logger = logging.getLogger("briefing.watch")
    now_provider = now_provider or (lambda: datetime.now().astimezone())
    sleep_fn = sleep_fn or time.sleep
    calendar = calendar or EventKitClient(settings)
    state_store = StateStore(settings)
    exit_code = 0

    while True:
        exit_code = 0
        now = now_provider()
        try:
            fetch_start = now - timedelta(days=1)
            fetch_end = now + timedelta(minutes=settings.meeting_intelligence.watch_lookahead_minutes)
            events = _fetch_watch_events(calendar, fetch_start, fetch_end)
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


def _fetch_watch_events(
    calendar: EventKitClient,
    fetch_start: datetime,
    fetch_end: datetime,
) -> list[MeetingEvent]:
    return calendar.fetch_events(fetch_start, fetch_end)


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
    if event.start <= now:
        return
    pre_roll_at = event.start - timedelta(seconds=settings.meeting_intelligence.pre_roll_seconds)
    if now < pre_roll_at:
        return

    existing_plan = state_store.load_session_plan_for_event(event)
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
        return

    command = [settings.meeting_intelligence.noted_command, "start", "--manifest", result.manifest_path]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    updated = replace(
        plan,
        status="launched" if completed.returncode == 0 else "launch_failed",
        launched_at=now.isoformat(),
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
