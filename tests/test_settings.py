from __future__ import annotations

from pathlib import Path

import pytest

from briefing.settings import SettingsError, load_env_file, load_series_configs, load_settings


SETTINGS_HEADER = """
[paths]
vault_root = "~/Vault"
meeting_notes_dir = "Meetings"
log_dir = "logs"
state_dir = "state"
prompt_dir = "user_config/prompts"
template_dir = "user_config/templates"
series_dir = "user_config/series"
debug_dir = "tmp"
env_file = "~/.env.briefing"

[meeting_intelligence]
sessions_root = "sessions"
noted_command = "noted"
pre_roll_seconds = 90
raw_audio_retention_days = 7
reschedule_tolerance_seconds = 300
watch_poll_seconds = 30
watch_lookahead_minutes = 180
default_host_name = "Meeting host"
default_language = "en-AU"
default_asr_backend = "whisperkit"
default_diarization_enabled = true
default_mode = "in_person"
auto_start = true
auto_stop = true
default_extension_minutes = 10
max_single_extension_minutes = 15
pre_end_prompt_minutes = 5
no_interaction_grace_minutes = 5

[calendar]
include_all_day = false
window_min_minutes = 15
window_max_minutes = 45
include_calendar_names = []
exclude_calendar_names = []
lookback_days_for_init = 14

[execution]
max_parallel_sources = 4
source_timeout_seconds = 120

[output]
meeting_notes_placeholder = "- "

[slack]
history_days = 7
request_timeout_seconds = 30
max_messages = 500
page_size = 200
max_characters = 20000

[notion]
version = "2022-06-28"
request_timeout_seconds = 30
max_characters = 20000

[files]
max_characters = 20000

[email]
history_days = 7
max_messages = 20
max_characters = 20000
request_timeout_seconds = 30

[logging]
level = "INFO"
history_file = "history.log"
last_run_file = "last-run.log"
debug_prompts = false
debug_llm_output = false
""".strip()


def _write_settings(tmp_path: Path, llm_block: str) -> None:
    user_config_dir = tmp_path / "user_config"
    user_config_dir.mkdir(parents=True, exist_ok=True)
    (user_config_dir / "settings.toml").write_text(
        f"{SETTINGS_HEADER}\n\n[llm]\n{llm_block.strip()}\n",
        encoding="utf-8",
    )


def test_load_env_file_accepts_export_prefix(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "export LOCAL_LLM_API_KEY='local-key'",
                'PLAIN_KEY="plain-value"',
            ]
        ),
        encoding="utf-8",
    )

    assert load_env_file(env_file) == {
        "LOCAL_LLM_API_KEY": "local-key",
        "PLAIN_KEY": "plain-value",
    }


def test_load_settings_parses_supported_provider_values(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "copilot"
command = "copilot"
model = "gpt-5.2"
effort = "high"
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    settings = load_settings(tmp_path)

    assert settings.llm.provider == "copilot"
    assert settings.llm.command == "copilot"
    assert settings.llm.effort == "high"


def test_load_settings_normalizes_legacy_claude_provider(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "claude_cli"
command = "claude"
model = "sonnet"
effort = ""
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    settings = load_settings(tmp_path)

    assert settings.llm.provider == "claude"


def test_load_settings_rejects_invalid_provider(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "openai"
command = "openai"
model = ""
effort = ""
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    with pytest.raises(SettingsError, match=r"\[llm\]\.provider"):
        load_settings(tmp_path)


def test_load_settings_parses_openai_compatible_provider(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "openai-compatible"
command = ""
model = "local-model"
effort = ""
base_url = "http://127.0.0.1:1234/v1"
api_key_env = "LOCAL_LLM_KEY"
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    settings = load_settings(tmp_path)

    assert settings.llm.provider == "openai-compatible"
    assert settings.llm.base_url == "http://127.0.0.1:1234/v1"
    assert settings.llm.api_key_env == "LOCAL_LLM_KEY"
    assert settings.llm.command == ""


def test_load_settings_rejects_openai_compatible_without_base_url(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "openai-compatible"
model = "local-model"
effort = ""
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    with pytest.raises(SettingsError, match=r"base_url"):
        load_settings(tmp_path)


def test_load_settings_base_url_and_api_key_env_default_to_none_for_cli_providers(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "claude"
command = "claude"
model = "sonnet"
effort = ""
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    settings = load_settings(tmp_path)

    assert settings.llm.base_url is None
    assert settings.llm.api_key_env is None


def test_load_settings_rejects_invalid_effort(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "claude"
command = "claude"
model = "sonnet"
effort = "xhigh"
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    with pytest.raises(SettingsError, match=r"\[llm\]\.effort"):
        load_settings(tmp_path)



def test_load_settings_uses_default_command_when_blank(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "codex"
command = "   "
model = "gpt-5.4"
effort = "medium"
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    settings = load_settings(tmp_path)

    assert settings.llm.command == "codex"


def test_load_settings_parses_meeting_intelligence_defaults(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
provider = "codex"
command = ""
model = "gpt-5.4"
effort = "medium"
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
""",
    )

    settings = load_settings(tmp_path)

    assert settings.meeting_intelligence.sessions_root == tmp_path / "sessions"
    assert settings.meeting_intelligence.pre_roll_seconds == 90
    assert settings.meeting_intelligence.raw_audio_retention_days == 7
    assert settings.meeting_intelligence.one_off_note_dir == settings.paths.meeting_notes_dir
    assert settings.meeting_intelligence.default_location_type is None
    assert settings.meeting_intelligence.local_location_type is None
    assert settings.meeting_intelligence.location_type_by_host == {}


@pytest.mark.parametrize("value", ["0", "-1", '"soon"', "1.5", "true"])
def test_load_settings_rejects_invalid_raw_audio_retention_days(
    tmp_path: Path,
    value: str,
) -> None:
    text = SETTINGS_HEADER.replace("raw_audio_retention_days = 7", f"raw_audio_retention_days = {value}")
    (tmp_path / "user_config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "user_config" / "settings.toml").write_text(
        f"{text}\n\n[llm]\n"
        "provider = \"codex\"\n"
        "command = \"\"\n"
        "model = \"gpt-5.4\"\n"
        "effort = \"medium\"\n"
        "timeout_seconds = 600\n"
        "retry_attempts = 3\n"
        "temperature = 0.2\n"
        "max_output_tokens = 4096\n"
        "prompt_template = \"pre_meeting_summary.md\"\n"
        "note_template = \"meeting_note.md\"\n",
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match=r"raw_audio_retention_days"):
        load_settings(tmp_path)


def test_load_settings_raw_audio_retention_days_defaults_to_7_when_absent(
    tmp_path: Path,
) -> None:
    text = SETTINGS_HEADER.replace("\nraw_audio_retention_days = 7", "")
    (tmp_path / "user_config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "user_config" / "settings.toml").write_text(
        f"{text}\n\n[llm]\n"
        "provider = \"codex\"\n"
        "command = \"\"\n"
        "model = \"gpt-5.4\"\n"
        "effort = \"medium\"\n"
        "timeout_seconds = 600\n"
        "retry_attempts = 3\n"
        "temperature = 0.2\n"
        "max_output_tokens = 4096\n"
        "prompt_template = \"pre_meeting_summary.md\"\n"
        "note_template = \"meeting_note.md\"\n",
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)

    assert settings.meeting_intelligence.raw_audio_retention_days == 7


def test_load_settings_parses_recording_location_routing(tmp_path: Path) -> None:
    text = SETTINGS_HEADER.replace(
        "watch_lookahead_minutes = 180",
        'watch_lookahead_minutes = 180\n'
        'default_location_type = "Office"\n'
        'local_location_type = ""',
    ).replace(
        "\n[calendar]",
        '\n[meeting_intelligence.location_type_by_host]\n'
        '"Office-Mac" = "office"\n'
        '"Home-Mac" = "Home Office"\n\n'
        '[calendar]',
    )
    (tmp_path / "user_config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "user_config" / "settings.toml").write_text(
        f"{text}\n\n[llm]\n"
        "provider = \"codex\"\n"
        "command = \"\"\n"
        "model = \"gpt-5.4\"\n"
        "effort = \"medium\"\n"
        "timeout_seconds = 600\n"
        "retry_attempts = 3\n"
        "temperature = 0.2\n"
        "max_output_tokens = 4096\n"
        "prompt_template = \"pre_meeting_summary.md\"\n"
        "note_template = \"meeting_note.md\"\n",
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)

    assert settings.meeting_intelligence.default_location_type == "office"
    assert settings.meeting_intelligence.local_location_type is None
    assert settings.meeting_intelligence.location_type_by_host == {
        "Office-Mac": "office",
        "Home-Mac": "home_office",
    }


def test_load_settings_rejects_out_of_bounds_pre_roll(tmp_path: Path) -> None:
    user_config_dir = tmp_path / "user_config"
    user_config_dir.mkdir(parents=True, exist_ok=True)
    text = SETTINGS_HEADER.replace("pre_roll_seconds = 90", "pre_roll_seconds = 30")
    (user_config_dir / "settings.toml").write_text(
        f"{text}\n\n[llm]\n"
        "provider = \"codex\"\n"
        "command = \"\"\n"
        "model = \"gpt-5.4\"\n"
        "effort = \"medium\"\n"
        "timeout_seconds = 600\n"
        "retry_attempts = 3\n"
        "temperature = 0.2\n"
        "max_output_tokens = 4096\n"
        "prompt_template = \"pre_meeting_summary.md\"\n"
        "note_template = \"meeting_note.md\"\n",
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match="pre_roll_seconds"):
        load_settings(tmp_path)


def test_load_settings_rejects_invalid_meeting_intelligence_boolean_string(tmp_path: Path) -> None:
    user_config_dir = tmp_path / "user_config"
    user_config_dir.mkdir(parents=True, exist_ok=True)
    text = SETTINGS_HEADER.replace("auto_start = true", 'auto_start = "flase"')
    (user_config_dir / "settings.toml").write_text(
        f"{text}\n\n[llm]\n"
        "provider = \"codex\"\n"
        "command = \"\"\n"
        "model = \"gpt-5.4\"\n"
        "effort = \"medium\"\n"
        "timeout_seconds = 600\n"
        "retry_attempts = 3\n"
        "temperature = 0.2\n"
        "max_output_tokens = 4096\n"
        "prompt_template = \"pre_meeting_summary.md\"\n"
        "note_template = \"meeting_note.md\"\n",
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match="auto_start"):
        load_settings(tmp_path)


def test_load_series_configs_rejects_invalid_recording_boolean_string(app_settings) -> None:
    (app_settings.paths.series_dir / "bad.yaml").write_text(
        """
series_id: bad
display_name: Bad
note_slug: bad
match:
  title_any:
    - Bad
recording:
  record: flase
""",
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match="boolean"):
        load_series_configs(app_settings)


def test_load_series_configs_rejects_removed_audio_strategy(app_settings) -> None:
    (app_settings.paths.series_dir / "bad.yaml").write_text(
        """
series_id: bad
display_name: Bad
note_slug: bad
match:
  title_any:
    - Bad
recording:
  mode: online
  audio_strategy: mic_plus_system
""",
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match="audio_strategy has been removed"):
        load_series_configs(app_settings)


def _write_mi_settings(tmp_path: Path, overrides: dict) -> None:
    """Write a minimal settings file with meeting_intelligence overrides applied."""
    header = SETTINGS_HEADER
    for key, value in overrides.items():
        old = f"{key} = {_default_mi_value(key)}"
        new = f"{key} = {value}"
        header = header.replace(old, new)
    (tmp_path / "user_config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "user_config" / "settings.toml").write_text(
        f"{header}\n\n[llm]\n"
        "provider = \"codex\"\n"
        "command = \"\"\n"
        "model = \"gpt-5.4\"\n"
        "effort = \"medium\"\n"
        "timeout_seconds = 600\n"
        "retry_attempts = 3\n"
        "temperature = 0.2\n"
        "max_output_tokens = 4096\n"
        "prompt_template = \"pre_meeting_summary.md\"\n"
        "note_template = \"meeting_note.md\"\n",
        encoding="utf-8",
    )


def _default_mi_value(key: str) -> str:
    defaults = {
        "watch_poll_seconds": "30",
        "reschedule_tolerance_seconds": "300",
        "watch_lookahead_minutes": "180",
        "default_extension_minutes": "10",
        "max_single_extension_minutes": "15",
        "pre_end_prompt_minutes": "5",
        "no_interaction_grace_minutes": "5",
    }
    return defaults[key]


@pytest.mark.parametrize(
    "key, bad_value, match_text",
    [
        ("watch_poll_seconds", "0", "watch_poll_seconds"),
        ("watch_poll_seconds", "4", "watch_poll_seconds"),
        ("reschedule_tolerance_seconds", "-1", "reschedule_tolerance_seconds"),
        ("watch_lookahead_minutes", "0", "watch_lookahead_minutes"),
        ("default_extension_minutes", "-1", "default_extension_minutes"),
        ("max_single_extension_minutes", "-1", "max_single_extension_minutes"),
        ("pre_end_prompt_minutes", "-1", "pre_end_prompt_minutes"),
        ("no_interaction_grace_minutes", "-1", "no_interaction_grace_minutes"),
    ],
)
def test_load_settings_rejects_out_of_bounds_integer_settings(
    tmp_path: Path, key: str, bad_value: str, match_text: str
) -> None:
    _write_mi_settings(tmp_path, {key: bad_value})
    with pytest.raises(SettingsError, match=match_text):
        load_settings(tmp_path)
