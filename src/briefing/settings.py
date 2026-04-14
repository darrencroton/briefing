"""Settings and config loading."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
import re
from textwrap import dedent
from typing import Any

import yaml

from .bootstrap import default_settings_path, local_settings_path
from .models import (
    FileSourceConfig,
    MatchRules,
    NotionSourceConfig,
    SeriesConfig,
    SeriesSources,
    SlackSourceConfig,
)
from .utils import expand_path, slugify


class SettingsError(ValueError):
    """Raised when the local settings file is invalid."""


@dataclass(slots=True)
class PathsSettings:
    vault_root: Path
    meeting_notes_dir: Path
    log_dir: Path
    state_dir: Path
    prompt_dir: Path
    template_dir: Path
    series_dir: Path
    debug_dir: Path
    env_file: Path


@dataclass(slots=True)
class CalendarSettings:
    include_all_day: bool
    window_min_minutes: int
    window_max_minutes: int
    include_calendar_names: list[str]
    exclude_calendar_names: list[str]
    icalpal_path: str
    lookback_days_for_init: int


@dataclass(slots=True)
class ExecutionSettings:
    max_parallel_sources: int
    source_timeout_seconds: int


@dataclass(slots=True)
class OutputSettings:
    meeting_notes_placeholder: str
    actions_placeholder: str


@dataclass(slots=True)
class LLMSettings:
    provider: str
    command: str
    model: str
    effort: str
    timeout_seconds: int
    retry_attempts: int
    temperature: float
    max_output_tokens: int
    prompt_template: str
    note_template: str


@dataclass(slots=True)
class SlackSettings:
    history_days: int
    request_timeout_seconds: int
    max_messages: int
    page_size: int
    max_characters: int


@dataclass(slots=True)
class NotionSettings:
    version: str
    request_timeout_seconds: int
    max_characters: int


@dataclass(slots=True)
class FilesSettings:
    max_characters: int


@dataclass(slots=True)
class LoggingSettings:
    level: str
    history_file: str
    last_run_file: str
    debug_prompts: bool
    debug_llm_output: bool


@dataclass(slots=True)
class AppSettings:
    repo_root: Path
    paths: PathsSettings
    calendar: CalendarSettings
    execution: ExecutionSettings
    output: OutputSettings
    llm: LLMSettings
    slack: SlackSettings
    notion: NotionSettings
    files: FilesSettings
    logging: LoggingSettings


def load_settings(repo_root: Path | None = None) -> AppSettings:
    """Load the main settings file."""
    if repo_root is None:
        repo_root = Path.cwd()
    settings_path = local_settings_path(repo_root)
    if not settings_path.exists():
        raise FileNotFoundError(
            f"Missing local settings file: {settings_path}. "
            f"Run ./scripts/setup.sh to bootstrap it from {default_settings_path(repo_root)}."
        )
    raw_text = settings_path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(_format_toml_decode_error(settings_path, raw_text, exc)) from exc

    try:
        paths = data["paths"]
        calendar = dict(data["calendar"])
        calendar["include_calendar_names"] = _coerce_string_list(
            calendar.get("include_calendar_names"), "calendar", "include_calendar_names"
        )
        calendar["exclude_calendar_names"] = _coerce_string_list(
            calendar.get("exclude_calendar_names"), "calendar", "exclude_calendar_names"
        )
        return AppSettings(
            repo_root=repo_root,
            paths=PathsSettings(
                vault_root=expand_path(paths["vault_root"], repo_root),
                meeting_notes_dir=expand_path(
                    str(Path(paths["vault_root"]) / paths["meeting_notes_dir"]), repo_root
                ),
                log_dir=expand_path(paths["log_dir"], repo_root),
                state_dir=expand_path(paths["state_dir"], repo_root),
                prompt_dir=expand_path(paths["prompt_dir"], repo_root),
                template_dir=expand_path(paths["template_dir"], repo_root),
                series_dir=expand_path(paths["series_dir"], repo_root),
                debug_dir=expand_path(paths["debug_dir"], repo_root),
                env_file=expand_path(paths["env_file"], repo_root),
            ),
            calendar=CalendarSettings(**calendar),
            execution=ExecutionSettings(**data["execution"]),
            output=OutputSettings(**data["output"]),
            llm=LLMSettings(**data["llm"]),
            slack=SlackSettings(**data["slack"]),
            notion=NotionSettings(**data["notion"]),
            files=FilesSettings(**data["files"]),
            logging=LoggingSettings(**data["logging"]),
        )
    except KeyError as exc:
        raise SettingsError(
            f"Invalid settings file: {settings_path}\nMissing required setting: {exc.args[0]}"
        ) from exc
    except TypeError as exc:
        raise SettingsError(
            f"Invalid settings file: {settings_path}\nA settings section has the wrong shape: {exc}"
        ) from exc


def load_series_configs(settings: AppSettings) -> list[SeriesConfig]:
    """Load all series config files."""
    configs: list[SeriesConfig] = []
    for path in sorted(settings.paths.series_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not raw:
            continue
        match = raw.get("match") or {}
        sources_raw = raw.get("sources") or {}
        configs.append(
            SeriesConfig(
                path=path,
                series_id=str(raw["series_id"]),
                display_name=str(raw["display_name"]),
                note_slug=slugify(str(raw["note_slug"])),
                match=MatchRules(
                    title_any=[str(item) for item in match.get("title_any", [])],
                    attendee_emails_any=[
                        str(item).lower() for item in match.get("attendee_emails_any", [])
                    ],
                    organizer_emails_any=[
                        str(item).lower()
                        for item in match.get("organizer_emails_any", [])
                    ],
                    calendar_names_any=[
                        str(item).lower() for item in match.get("calendar_names_any", [])
                    ],
                ),
                sources=SeriesSources(
                    slack=_parse_slack_source(sources_raw.get("slack")),
                    notion=[
                        NotionSourceConfig(
                            label=str(item["label"]),
                            page_id=str(item["page_id"]),
                            required=bool(item.get("required", False)),
                            max_characters=_optional_int(item.get("max_characters")),
                        )
                        for item in sources_raw.get("notion", [])
                    ],
                    files=[
                        FileSourceConfig(
                            label=str(item["label"]),
                            path=str(item["path"]),
                            required=bool(item.get("required", False)),
                            max_characters=_optional_int(item.get("max_characters")),
                        )
                        for item in sources_raw.get("files", [])
                    ],
                ),
                overrides=dict(raw.get("overrides") or {}),
            )
        )
    return configs


def load_env_file(env_path: Path) -> dict[str, str]:
    """Read a simple KEY=VALUE env file."""
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _parse_slack_source(raw: Any) -> SlackSourceConfig | None:
    if not raw:
        return None
    return SlackSourceConfig(
        channel_refs=[str(item) for item in raw.get("channel_refs", [])],
        dm_user_ids=[str(item) for item in raw.get("dm_user_ids", [])],
        required=bool(raw.get("required", False)),
        history_days=_optional_int(raw.get("history_days")),
        max_characters=_optional_int(raw.get("max_characters")),
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _coerce_string_list(value: Any, section: str, key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise SettingsError(
                    f"Invalid settings value: [{section}] {key} must contain only strings."
                )
            text = item.strip()
            if text:
                items.append(text)
        return items
    raise SettingsError(
        f"Invalid settings value: [{section}] {key} must be a string or a list of strings."
    )


def _format_toml_decode_error(
    settings_path: Path, raw_text: str, exc: tomllib.TOMLDecodeError
) -> str:
    line_number, column_number = _extract_toml_error_location(exc)
    location = ""
    if line_number is not None and column_number is not None:
        location = f" (line {line_number}, column {column_number})"

    message_lines = [
        f"Invalid TOML in settings file: {settings_path}{location}",
        str(exc),
    ]

    if line_number is None:
        return "\n".join(message_lines)

    lines = raw_text.splitlines()
    if not 1 <= line_number <= len(lines):
        return "\n".join(message_lines)

    line = lines[line_number - 1]
    message_lines.extend(
        [
            "",
            f"{line_number:>4} | {line}",
            f"     | {' ' * max((column_number or 1) - 1, 0)}^",
        ]
    )
    hint = _toml_hint_for_line(line)
    if hint:
        message_lines.extend(["", f"Hint: {hint}"])
    return "\n".join(message_lines)


def _extract_toml_error_location(exc: tomllib.TOMLDecodeError) -> tuple[int | None, int | None]:
    line_number = getattr(exc, "lineno", None)
    column_number = getattr(exc, "colno", None)
    if line_number is not None and column_number is not None:
        return line_number, column_number

    match = re.search(r"at line (\d+), column (\d+)", str(exc))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _toml_hint_for_line(line: str) -> str | None:
    if "=" not in line:
        return None
    _, raw_value = line.split("=", 1)
    value = raw_value.strip()
    if value.startswith("[") and value.endswith("]") and '"' not in value and "'" not in value:
        return dedent(
            """\
            TOML strings inside arrays must be quoted, for example:
            include_calendar_names = ["Calendar"]"""
        ).replace("\n", " ")
    return None
