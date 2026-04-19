from __future__ import annotations

from pathlib import Path

import pytest

from briefing.settings import SettingsError, load_settings


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
max_characters = 10000
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
