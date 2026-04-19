from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from briefing.models import MatchRules, SeriesConfig, SeriesSources
from briefing.settings import (
    AppSettings,
    CalendarSettings,
    EmailSettings,
    ExecutionSettings,
    FilesSettings,
    LLMSettings,
    LoggingSettings,
    NotionSettings,
    OutputSettings,
    PathsSettings,
    SlackSettings,
)


@pytest.fixture
def app_settings(tmp_path: Path) -> AppSettings:
    vault_root = tmp_path / "vault"
    meeting_notes_dir = vault_root / "Work" / "Resources" / "Meeting Notes"
    prompt_dir = tmp_path / "prompts"
    template_dir = tmp_path / "templates"
    series_dir = tmp_path / "series"
    for path in (meeting_notes_dir, prompt_dir, template_dir, series_dir, tmp_path / "logs", tmp_path / "state"):
        path.mkdir(parents=True, exist_ok=True)

    (prompt_dir / "pre_meeting_summary.md").write_text(
        "Meeting:\n{{MEETING_CONTEXT}}\n\nSources:\n{{SOURCE_BLOCKS}}\n",
        encoding="utf-8",
    )
    (template_dir / "meeting_note.md").write_text(
        "{{FRONTMATTER}}\n# {{HEADING}}\n[[{{DATE_LINK}}]] | [[{{SERIES_LINK}}]]\n\n---\n{{BRIEFING_BLOCK}}\n\n---\n## Meeting Notes\n\n{{MEETING_NOTES_PLACEHOLDER}}\n",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env.briefing"
    env_file.write_text("", encoding="utf-8")

    return AppSettings(
        repo_root=tmp_path,
        paths=PathsSettings(
            vault_root=vault_root,
            meeting_notes_dir=meeting_notes_dir,
            log_dir=tmp_path / "logs",
            state_dir=tmp_path / "state",
            prompt_dir=prompt_dir,
            template_dir=template_dir,
            series_dir=series_dir,
            debug_dir=tmp_path / "tmp",
            env_file=env_file,
        ),
        calendar=CalendarSettings(
            include_all_day=False,
            window_min_minutes=15,
            window_max_minutes=45,
            include_calendar_names=[],
            exclude_calendar_names=[],
            lookback_days_for_init=14,
        ),
        execution=ExecutionSettings(max_parallel_sources=4, source_timeout_seconds=5),
        output=OutputSettings(
            meeting_notes_placeholder="- ",
        ),
        llm=LLMSettings(
            provider="claude",
            command="claude",
            model="sonnet",
            effort="",
            timeout_seconds=30,
            retry_attempts=1,
            temperature=0.2,
            max_output_tokens=4096,
            prompt_template="pre_meeting_summary.md",
            note_template="meeting_note.md",
        ),
        slack=SlackSettings(
            history_days=7,
            request_timeout_seconds=5,
            max_messages=50,
            page_size=20,
            max_characters=20000,
        ),
        notion=NotionSettings(
            version="2022-06-28",
            request_timeout_seconds=5,
            max_characters=20000,
        ),
        files=FilesSettings(max_characters=20000),
        email=EmailSettings(
            history_days=7,
            max_messages=20,
            max_characters=20000,
            request_timeout_seconds=5,
        ),
        logging=LoggingSettings(
            level="INFO",
            history_file="history.log",
            last_run_file="last-run.log",
            debug_prompts=False,
            debug_llm_output=False,
        ),
    )


@pytest.fixture
def series_config(app_settings: AppSettings) -> SeriesConfig:
    return SeriesConfig(
        path=app_settings.paths.series_dir / "cas-strategy.yaml",
        series_id="cas-strategy",
        display_name="CAS Strategy Meeting",
        note_slug="cas-strategy-meeting",
        match=MatchRules(title_any=["CAS Strategy Meeting"]),
        sources=SeriesSources(),
        overrides={},
    )
