"""Main orchestration runtime."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .calendar import IcalPalClient
from .llm import LLMError, get_provider
from .matching import match_series
from .models import MeetingEvent, OccurrenceState, SeriesConfig
from .notes import note_is_locked, refresh_note, render_note
from .prompts import render_summary_prompt
from .settings import AppSettings, load_env_file, load_series_configs
from .sources import collect_sources
from .state import StateStore
from .utils import ensure_directory, sha256_text


def run_briefing(
    settings: AppSettings,
    now: datetime | None = None,
    dry_run: bool = False,
) -> int:
    """Run the scheduled briefing workflow once."""
    logger = logging.getLogger("briefing.run")
    now = now or datetime.now().astimezone()
    ensure_directory(settings.paths.meeting_notes_dir)
    ensure_directory(settings.paths.debug_dir)
    series_configs = load_series_configs(settings)
    env = load_env_file(settings.paths.env_file)
    state_store = StateStore(settings)
    calendar = IcalPalClient(settings)
    provider = get_provider(settings)

    try:
        events = calendar.fetch_upcoming(now)
    except Exception as exc:
        logger.exception("Failed to query calendar: %s", exc)
        state_store.write_run_diagnostic(
            {
                "status": "error",
                "error": str(exc),
                "now": now.isoformat(),
            },
            now,
        )
        return 1

    diagnostics: list[dict[str, object]] = []
    exit_code = 0
    for event in sorted(events, key=lambda item: item.start):
        diagnostic = process_event(
            settings=settings,
            event=event,
            series_configs=series_configs,
            env=env,
            state_store=state_store,
            provider=provider,
            now=now,
            dry_run=dry_run,
        )
        diagnostics.append(diagnostic)
        if diagnostic["status"] == "error":
            exit_code = 1

    state_store.write_run_diagnostic(
        {
            "status": "completed" if exit_code == 0 else "error",
            "now": now.isoformat(),
            "events_seen": [event.uid for event in events],
            "results": diagnostics,
        },
        now,
    )
    return exit_code


def process_event(
    *,
    settings: AppSettings,
    event: MeetingEvent,
    series_configs: list[SeriesConfig],
    env: dict[str, str],
    state_store: StateStore,
    provider,
    now: datetime,
    dry_run: bool,
) -> dict[str, object]:
    """Process one meeting occurrence."""
    logger = logging.getLogger(f"briefing.event.{event.uid}")
    matches = match_series(event, series_configs)
    if not matches:
        logger.info("Skipping %s: no configured series match", event.title)
        return {
            "event_uid": event.uid,
            "title": event.title,
            "status": "skipped",
            "reason": "no_series_match",
        }
    if len(matches) > 1:
        logger.error("Multiple series matched %s: %s", event.title, [match.series_id for match in matches])
        return {
            "event_uid": event.uid,
            "title": event.title,
            "status": "error",
            "reason": "multiple_series_matches",
            "series_ids": [match.series_id for match in matches],
        }

    series = matches[0]
    occurrence_key = state_store.occurrence_key(event)
    state = state_store.load_occurrence(occurrence_key) or OccurrenceState(
        occurrence_key=occurrence_key,
        series_id=series.series_id,
        event_uid=event.uid,
        start_iso=event.start.isoformat(),
        output_path=str(settings.paths.meeting_notes_dir / build_output_filename(event, series)),
    )
    output_path = Path(state.output_path)
    existed_before = output_path.exists()

    if state.locked:
        logger.info("Skipping %s: occurrence already locked (%s)", event.title, state.lock_reason)
        return {
            "event_uid": event.uid,
            "series_id": series.series_id,
            "status": "skipped",
            "reason": state.lock_reason or "locked",
            "output_path": str(output_path),
        }

    if now >= event.start:
        state.locked = True
        state.lock_reason = "meeting_started"
        state.last_status = "skipped"
        state_store.save_occurrence(state)
        logger.info("Skipping %s: meeting already started", event.title)
        return {
            "event_uid": event.uid,
            "series_id": series.series_id,
            "status": "skipped",
            "reason": "meeting_started",
            "output_path": str(output_path),
        }

    if output_path.exists():
        locked, reason = note_is_locked(settings, output_path.read_text(encoding="utf-8"))
        if locked:
            state.locked = True
            state.lock_reason = reason
            state.last_status = "locked"
            state_store.save_occurrence(state)
            logger.info("Skipping %s: note locked because %s", event.title, reason)
            return {
                "event_uid": event.uid,
                "series_id": series.series_id,
                "status": "skipped",
                "reason": reason,
                "output_path": str(output_path),
            }

    sources = collect_sources(settings, event, series, logger, env)
    blocking_errors = [source for source in sources if source.status == "error" and source.required]
    if blocking_errors:
        state.last_status = "error"
        state.last_error = "; ".join(filter(None, (source.error for source in blocking_errors)))
        state_store.save_occurrence(state)
        logger.error("Required sources failed for %s: %s", event.title, state.last_error)
        return {
            "event_uid": event.uid,
            "series_id": series.series_id,
            "status": "error",
            "reason": "required_source_failed",
            "source_results": [asdict(source) for source in sources],
        }

    usable_sources = [source for source in sources if source.status == "ok"]
    prompt_template = settings.paths.prompt_dir / settings.llm.prompt_template
    note_template = settings.paths.template_dir / settings.llm.note_template
    prompt = render_summary_prompt(
        prompt_template.read_text(encoding="utf-8"),
        event,
        usable_sources,
        now,
    )
    if settings.logging.debug_prompts:
        debug_prompt_path = settings.paths.debug_dir / f"{occurrence_key}-prompt.txt"
        debug_prompt_path.write_text(prompt, encoding="utf-8")

    try:
        llm_response = provider.generate(prompt)
    except LLMError as exc:
        state.last_status = "error"
        state.last_error = str(exc)
        state_store.save_occurrence(state)
        logger.error("LLM generation failed for %s: %s", event.title, exc)
        return {
            "event_uid": event.uid,
            "series_id": series.series_id,
            "status": "error",
            "reason": "llm_generation_failed",
            "error": str(exc),
            "source_results": [asdict(source) for source in sources],
        }

    if settings.logging.debug_llm_output:
        debug_output_path = settings.paths.debug_dir / f"{occurrence_key}-llm-output.txt"
        debug_output_path.write_text(llm_response.raw, encoding="utf-8")

    summary_hash = sha256_text(llm_response.text)
    source_hashes = {source.label: sha256_text(source.content) for source in usable_sources}
    if output_path.exists() and state.summary_hash == summary_hash and state.source_hashes == source_hashes:
        state.last_status = "unchanged"
        state.last_generated_at = now.isoformat()
        state_store.save_occurrence(state)
        logger.info("Skipping write for %s: summary unchanged", event.title)
        return {
            "event_uid": event.uid,
            "series_id": series.series_id,
            "status": "unchanged",
            "output_path": str(output_path),
        }

    note_text = render_or_refresh_note(
        settings=settings,
        event=event,
        series=series,
        output_path=output_path,
        summary_bullets=llm_response.text,
        now=now,
    )
    if not dry_run:
        output_path.write_text(note_text, encoding="utf-8")

    state.last_status = "written"
    state.last_error = None
    state.source_hashes = source_hashes
    state.summary_hash = summary_hash
    state.last_generated_at = now.isoformat()
    state.output_path = str(output_path)
    state_store.save_occurrence(state)

    logger.info("%s note for %s -> %s", "Refreshed" if existed_before else "Created", event.title, output_path)
    return {
        "event_uid": event.uid,
        "series_id": series.series_id,
        "status": "written",
        "output_path": str(output_path),
        "dry_run": dry_run,
        "source_results": [asdict(source) for source in sources],
    }


def render_or_refresh_note(
    *,
    settings: AppSettings,
    event: MeetingEvent,
    series: SeriesConfig,
    output_path: Path,
    summary_bullets: str,
    now: datetime,
) -> str:
    """Create or refresh a note in managed mode."""
    template = (settings.paths.template_dir / settings.llm.note_template).read_text(encoding="utf-8")
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        return refresh_note(settings, existing, summary_bullets)
    return render_note(settings, template, event, series, summary_bullets, now)


def build_output_filename(event: MeetingEvent, series: SeriesConfig) -> str:
    """Build the first-write note filename."""
    return f"{event.start:%Y-%m-%d-%H%M}-{series.note_slug}.md"
