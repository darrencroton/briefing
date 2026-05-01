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
from .coerce import optional_int as _optional_int, optional_str as _optional_str, parse_optional_bool
from .location_routing import normalize_location_type
from .models import (
    EmailSourceConfig,
    FileSourceConfig,
    MatchRules,
    NotionSourceConfig,
    RecordingConfig,
    RecordingPolicyConfig,
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
class MeetingIntelligenceSettings:
    sessions_root: Path
    noted_command: str
    pre_roll_seconds: int
    raw_audio_retention_days: int
    reschedule_tolerance_seconds: int
    watch_poll_seconds: int
    watch_lookahead_minutes: int
    default_location_type: str | None
    local_location_type: str | None
    location_type_by_host: dict[str, str]
    default_host_name: str
    default_language: str
    default_asr_backend: str
    default_diarization_enabled: bool
    default_mode: str
    one_off_note_dir: Path
    auto_start: bool
    auto_stop: bool
    default_extension_minutes: int
    max_single_extension_minutes: int
    pre_end_prompt_minutes: int
    no_interaction_grace_minutes: int


@dataclass(slots=True)
class CalendarSettings:
    include_all_day: bool
    window_min_minutes: int
    window_max_minutes: int
    include_calendar_names: list[str]
    exclude_calendar_names: list[str]
    lookback_days_for_init: int


@dataclass(slots=True)
class ExecutionSettings:
    max_parallel_sources: int
    source_timeout_seconds: int


@dataclass(slots=True)
class OutputSettings:
    meeting_notes_placeholder: str


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
class EmailSettings:
    history_days: int
    max_messages: int
    max_characters: int
    request_timeout_seconds: int


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
    meeting_intelligence: MeetingIntelligenceSettings
    calendar: CalendarSettings
    execution: ExecutionSettings
    output: OutputSettings
    llm: LLMSettings
    slack: SlackSettings
    notion: NotionSettings
    files: FilesSettings
    email: EmailSettings
    logging: LoggingSettings


_SUPPORTED_LLM_PROVIDERS = ("claude", "codex", "copilot", "gemini")
_LEGACY_LLM_PROVIDERS = {"claude_cli": "claude"}
_VALID_LLM_EFFORTS = ("low", "medium", "high")
_DEFAULT_LLM_COMMANDS = {
    "claude": "claude",
    "codex": "codex",
    "copilot": "copilot",
    "gemini": "gemini",
}
_VALID_MODE_TYPES = ("in_person", "online", "hybrid")
_VALID_AUDIO_STRATEGIES = ("room_mic", "mic_plus_system")
_VALID_ASR_BACKENDS = ("whisperkit", "fluidaudio-parakeet", "sfspeech")


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
        parsed_paths = PathsSettings(
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
        )
        return AppSettings(
            repo_root=repo_root,
            paths=parsed_paths,
            meeting_intelligence=_parse_meeting_intelligence_settings(
                data.get("meeting_intelligence") or {},
                repo_root,
                parsed_paths.meeting_notes_dir,
            ),
            calendar=CalendarSettings(**calendar),
            execution=ExecutionSettings(**data["execution"]),
            output=OutputSettings(**data["output"]),
            llm=LLMSettings(**_parse_llm_settings(data["llm"])),
            slack=SlackSettings(**data["slack"]),
            notion=NotionSettings(**data["notion"]),
            files=FilesSettings(**data["files"]),
            email=EmailSettings(**data["email"]),
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
                    emails=[
                        EmailSourceConfig(
                            email_addresses=[str(e) for e in item.get("email_addresses", [])],
                            account=item.get("account") or None,
                            mailboxes=[str(m) for m in item.get("mailboxes", [])],
                            subject_regex_any=[str(r) for r in item.get("subject_regex_any", [])],
                            history_days=_optional_int(item.get("history_days")),
                            max_messages=_optional_int(item.get("max_messages")),
                            max_characters=_optional_int(item.get("max_characters")),
                            required=bool(item.get("required", False)),
                        )
                        for item in sources_raw.get("email", [])
                    ],
                ),
                recording=_parse_recording_config(raw.get("recording") or raw.get("meeting_intelligence")),
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
        dm_conversation_ids=[str(item) for item in raw.get("dm_conversation_ids", [])],
        required=bool(raw.get("required", False)),
        history_days=_optional_int(raw.get("history_days")),
        max_characters=_optional_int(raw.get("max_characters")),
    )


def _parse_meeting_intelligence_settings(
    raw: Any,
    repo_root: Path,
    meeting_notes_dir: Path,
) -> MeetingIntelligenceSettings:
    if not isinstance(raw, dict):
        raise SettingsError("Invalid settings file: [meeting_intelligence] must be a table.")

    pre_roll = int(raw.get("pre_roll_seconds", 90))
    if not 60 <= pre_roll <= 180:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].pre_roll_seconds must be between 60 and 180."
        )

    raw_retention_value = raw.get("raw_audio_retention_days", 7)
    if isinstance(raw_retention_value, bool) or not isinstance(raw_retention_value, int):
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].raw_audio_retention_days must be an integer."
        )
    raw_audio_retention_days = raw_retention_value
    if raw_audio_retention_days < 1:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].raw_audio_retention_days must be at least 1."
        )

    default_mode = str(raw.get("default_mode", "in_person")).strip()
    if default_mode not in _VALID_MODE_TYPES:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].default_mode must be one of "
            f"{', '.join(_VALID_MODE_TYPES)}."
        )

    asr_backend = str(raw.get("default_asr_backend", "whisperkit")).strip()
    if asr_backend not in _VALID_ASR_BACKENDS:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].default_asr_backend must be one of "
            f"{', '.join(_VALID_ASR_BACKENDS)}."
        )

    noted_command = str(raw.get("noted_command", "noted")).strip() or "noted"
    one_off_note_dir_raw = raw.get("one_off_note_dir")
    one_off_note_dir = (
        expand_path(str(one_off_note_dir_raw), repo_root)
        if one_off_note_dir_raw
        else meeting_notes_dir
    )

    watch_poll = int(raw.get("watch_poll_seconds", 30))
    if watch_poll < 5:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].watch_poll_seconds must be at least 5."
        )

    reschedule_tolerance = int(raw.get("reschedule_tolerance_seconds", 300))
    if reschedule_tolerance < 0:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].reschedule_tolerance_seconds must be non-negative."
        )

    watch_lookahead = int(raw.get("watch_lookahead_minutes", 180))
    if watch_lookahead < 1:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].watch_lookahead_minutes must be at least 1."
        )

    default_extension = int(raw.get("default_extension_minutes", 10))
    if default_extension < 0:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].default_extension_minutes must be non-negative."
        )

    max_extension = int(raw.get("max_single_extension_minutes", 15))
    if max_extension < 0:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].max_single_extension_minutes must be non-negative."
        )

    pre_end = int(raw.get("pre_end_prompt_minutes", 5))
    if pre_end < 0:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].pre_end_prompt_minutes must be non-negative."
        )

    no_interaction = int(raw.get("no_interaction_grace_minutes", 5))
    if no_interaction < 0:
        raise SettingsError(
            "Invalid settings file: [meeting_intelligence].no_interaction_grace_minutes must be non-negative."
        )

    return MeetingIntelligenceSettings(
        sessions_root=expand_path(str(raw.get("sessions_root", "sessions")), repo_root),
        noted_command=noted_command,
        pre_roll_seconds=pre_roll,
        raw_audio_retention_days=raw_audio_retention_days,
        reschedule_tolerance_seconds=reschedule_tolerance,
        watch_poll_seconds=watch_poll,
        watch_lookahead_minutes=watch_lookahead,
        default_location_type=normalize_location_type(_optional_str(raw.get("default_location_type"))),
        local_location_type=normalize_location_type(_optional_str(raw.get("local_location_type"))),
        location_type_by_host=_parse_location_type_by_host(raw.get("location_type_by_host")),
        default_host_name=str(raw.get("default_host_name", "Meeting host")).strip() or "Meeting host",
        default_language=str(raw.get("default_language", "en-AU")).strip() or "en-AU",
        default_asr_backend=asr_backend,
        default_diarization_enabled=_required_bool(
            raw.get("default_diarization_enabled"),
            True,
            "[meeting_intelligence].default_diarization_enabled",
        ),
        default_mode=default_mode,
        one_off_note_dir=one_off_note_dir,
        auto_start=_required_bool(raw.get("auto_start"), True, "[meeting_intelligence].auto_start"),
        auto_stop=_required_bool(raw.get("auto_stop"), True, "[meeting_intelligence].auto_stop"),
        default_extension_minutes=default_extension,
        max_single_extension_minutes=max_extension,
        pre_end_prompt_minutes=pre_end,
        no_interaction_grace_minutes=no_interaction,
    )


def _parse_recording_config(raw: Any) -> RecordingConfig:
    if not raw:
        return RecordingConfig()
    if not isinstance(raw, dict):
        raise SettingsError("Invalid series config: recording must be a mapping.")

    participants = raw.get("participants") or {}
    if not isinstance(participants, dict):
        raise SettingsError("Invalid series config: recording.participants must be a mapping.")

    transcription = raw.get("transcription") or {}
    if not isinstance(transcription, dict):
        raise SettingsError("Invalid series config: recording.transcription must be a mapping.")

    mode_raw = raw.get("mode")
    mode_type: str | None = None
    audio_strategy: str | None = None
    if isinstance(mode_raw, dict):
        mode_type = _optional_str(mode_raw.get("type"))
        audio_strategy = _optional_str(mode_raw.get("audio_strategy"))
    else:
        mode_type = _optional_str(mode_raw)
        audio_strategy = _optional_str(raw.get("audio_strategy"))

    policy_raw = raw.get("recording_policy") or raw.get("policy") or {}
    if not isinstance(policy_raw, dict):
        raise SettingsError("Invalid series config: recording.recording_policy must be a mapping.")

    return RecordingConfig(
        record=_optional_bool(raw.get("record")),
        location_type=normalize_location_type(_optional_str(raw.get("location_type"))),
        mode=mode_type,
        audio_strategy=audio_strategy,
        host_name=_optional_str(participants.get("host_name", raw.get("host_name"))),
        attendees_expected=_optional_int(participants.get("attendees_expected", raw.get("attendees_expected"))),
        participant_names=[str(item) for item in participants.get("participant_names", raw.get("participant_names", []))],
        names_are_hints_only=True,
        language=_optional_str(transcription.get("language", raw.get("language"))),
        asr_backend=_optional_str(transcription.get("asr_backend", raw.get("asr_backend"))),
        diarization_enabled=_optional_bool(
            transcription.get("diarization_enabled", raw.get("diarization_enabled"))
        ),
        speaker_count_hint=_optional_int(
            transcription.get("speaker_count_hint", raw.get("speaker_count_hint"))
        ),
        note_dir=_optional_str(raw.get("note_dir")),
        note_slug=_optional_str(raw.get("note_slug")),
        recording_policy=RecordingPolicyConfig(
            auto_start=_optional_bool(policy_raw.get("auto_start")),
            auto_stop=_optional_bool(policy_raw.get("auto_stop")),
            default_extension_minutes=_optional_int(policy_raw.get("default_extension_minutes")),
            max_single_extension_minutes=_optional_int(policy_raw.get("max_single_extension_minutes")),
            pre_end_prompt_minutes=_optional_int(policy_raw.get("pre_end_prompt_minutes")),
            no_interaction_grace_minutes=_optional_int(policy_raw.get("no_interaction_grace_minutes")),
        ),
    )


def _parse_location_type_by_host(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SettingsError("Invalid settings file: [meeting_intelligence].location_type_by_host must be a table.")
    parsed: dict[str, str] = {}
    for host, location in raw.items():
        host_text = str(host).strip()
        location_type = normalize_location_type(str(location))
        if not host_text or not location_type:
            raise SettingsError(
                "Invalid settings file: [meeting_intelligence].location_type_by_host entries "
                "must have non-empty host names and location_type values."
            )
        parsed[host_text] = location_type
    return parsed


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return _bool_from_value(value, "series config")


def _required_bool(value: Any, default: bool, context: str) -> bool:
    if value is None:
        return default
    return _bool_from_value(value, context)


def _bool_from_value(value: Any, context: str) -> bool:
    try:
        result = parse_optional_bool(value)
    except ValueError as exc:
        raise SettingsError(f"Invalid {context}: {exc}.") from exc
    if result is None:
        raise SettingsError(f"Invalid {context}: expected a boolean value, got None.")
    return result


def _parse_llm_settings(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SettingsError("Invalid settings file: [llm] must be a table.")

    provider = str(raw.get("provider", "claude")).strip().lower()
    provider = _LEGACY_LLM_PROVIDERS.get(provider, provider)
    if provider not in _SUPPORTED_LLM_PROVIDERS:
        raise SettingsError(
            "Invalid settings file: [llm].provider must be one of "
            f"{', '.join(_SUPPORTED_LLM_PROVIDERS)}."
        )

    raw_command = raw.get("command")
    command = str(raw_command).strip() if raw_command is not None else ""
    if not command:
        command = _DEFAULT_LLM_COMMANDS[provider]

    raw_effort = raw.get("effort")
    effort = str(raw_effort).strip().lower() if raw_effort is not None else ""
    if effort and effort not in _VALID_LLM_EFFORTS:
        raise SettingsError(
            "Invalid settings file: [llm].effort must be blank or one of "
            f"{', '.join(_VALID_LLM_EFFORTS)}."
        )

    parsed = dict(raw)
    parsed["provider"] = provider
    parsed["command"] = command
    parsed["effort"] = effort
    return parsed


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
