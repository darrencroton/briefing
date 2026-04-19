from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from briefing.main import _init_series
from briefing.models import MeetingEvent
from briefing.bootstrap import ensure_local_user_config
from briefing.main import cli
from briefing.settings import SettingsError, load_series_configs, load_settings
from briefing.setup import ensure_runtime_directories, prepare_workspace


SETTINGS_TOML = """
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

[llm]
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


def test_ensure_local_user_config_copies_default_settings(tmp_path: Path) -> None:
    defaults_dir = tmp_path / "user_config" / "defaults"
    defaults_dir.mkdir(parents=True, exist_ok=True)
    (defaults_dir / "settings.toml").write_text(SETTINGS_TOML, encoding="utf-8")

    created = ensure_local_user_config(tmp_path)

    assert created == [tmp_path / "user_config" / "settings.toml"]
    assert (tmp_path / "user_config" / "settings.toml").exists()


def test_ensure_runtime_directories_creates_local_workspace_dirs(tmp_path: Path) -> None:
    created = ensure_runtime_directories(tmp_path)

    assert tmp_path / "logs" in created
    assert tmp_path / "state" / "occurrences" in created
    assert tmp_path / "state" / "runs" in created
    assert tmp_path / "tmp" in created
    assert tmp_path / "user_config" / "series" in created


def test_load_settings_requires_bootstrapped_local_settings(tmp_path: Path) -> None:
    defaults_dir = tmp_path / "user_config" / "defaults"
    defaults_dir.mkdir(parents=True, exist_ok=True)
    (defaults_dir / "settings.toml").write_text("[paths]\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match=r"Run \./scripts/setup\.sh"):
        load_settings(tmp_path)


def test_load_settings_reports_actionable_toml_errors(tmp_path: Path) -> None:
    user_config_dir = tmp_path / "user_config"
    user_config_dir.mkdir(parents=True, exist_ok=True)
    (user_config_dir / "settings.toml").write_text(
        SETTINGS_TOML.replace('include_calendar_names = []', "include_calendar_names = [Calendar]"),
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match=r'include_calendar_names = \["Calendar"\]'):
        load_settings(tmp_path)


def test_load_settings_coerces_single_calendar_name_string(tmp_path: Path) -> None:
    user_config_dir = tmp_path / "user_config"
    user_config_dir.mkdir(parents=True, exist_ok=True)
    (user_config_dir / "settings.toml").write_text(
        SETTINGS_TOML.replace('include_calendar_names = []', 'include_calendar_names = "Calendar"'),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)

    assert settings.calendar.include_calendar_names == ["Calendar"]


def test_cli_prints_settings_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["briefing", "validate"])
    monkeypatch.setattr("briefing.main.load_settings", lambda: (_ for _ in ()).throw(SettingsError("bad config")))

    exit_code = cli()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.strip() == "bad config"


def test_prepare_workspace_warns_when_bootstrapped_provider_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    defaults_dir = tmp_path / "user_config" / "defaults"
    defaults_dir.mkdir(parents=True, exist_ok=True)
    (defaults_dir / "settings.toml").write_text(SETTINGS_TOML, encoding="utf-8")

    monkeypatch.setattr(
        "briefing.setup.get_provider",
        lambda settings: SimpleNamespace(validate=lambda: (False, "provider unavailable")),
    )

    summary = prepare_workspace(tmp_path)

    assert summary.created_user_files == (tmp_path / "user_config" / "settings.toml",)
    assert summary.provider_validated is False
    assert summary.provider_warning is not None
    assert "provider unavailable" in summary.provider_warning
    assert summary.llm_provider == "claude"


def test_prepare_workspace_fails_for_existing_local_provider_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_config_dir = tmp_path / "user_config"
    defaults_dir = user_config_dir / "defaults"
    defaults_dir.mkdir(parents=True, exist_ok=True)
    (defaults_dir / "settings.toml").write_text(SETTINGS_TOML, encoding="utf-8")
    user_config_dir.mkdir(parents=True, exist_ok=True)
    (user_config_dir / "settings.toml").write_text(SETTINGS_TOML, encoding="utf-8")

    monkeypatch.setattr(
        "briefing.setup.get_provider",
        lambda settings: SimpleNamespace(validate=lambda: (False, "provider unavailable")),
    )

    with pytest.raises(ValueError, match="LLM provider validation failed for claude: provider unavailable"):
        prepare_workspace(tmp_path)


def test_setup_main_prints_provider_name_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "briefing.setup.prepare_workspace",
        lambda: SimpleNamespace(
            created_user_files=(),
            created_runtime_dirs=(),
            provider_validated=True,
            provider_warning=None,
            llm_provider="copilot",
        ),
    )

    from briefing import setup as setup_module

    exit_code = setup_module.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validated LLM provider prerequisites: copilot" in captured.out


def test_load_series_configs_reads_dm_conversation_ids_block_list(app_settings) -> None:
    series_path = app_settings.paths.series_dir / "slack-series.yaml"
    series_path.write_text(
        """
series_id: slack-series
display_name: Slack Series
note_slug: slack-series
match:
  title_any:
    - Slack Series
sources:
  slack:
    channel_refs:
      - eng-leads
    dm_conversation_ids:
      - D123
      - G456
    required: false
""".strip()
        + "\n",
        encoding="utf-8",
    )

    configs = load_series_configs(app_settings)

    assert configs[0].sources.slack is not None
    assert configs[0].sources.slack.dm_conversation_ids == ["D123", "G456"]


def test_load_series_configs_reads_dm_conversation_ids_inline_list(app_settings) -> None:
    series_path = app_settings.paths.series_dir / "slack-series.yaml"
    series_path.write_text(
        """
series_id: slack-series
display_name: Slack Series
note_slug: slack-series
match:
  title_any: [Slack Series]
sources:
  slack:
    channel_refs: [eng-leads]
    dm_conversation_ids: [D123, G456]
    required: false
""".strip()
        + "\n",
        encoding="utf-8",
    )

    configs = load_series_configs(app_settings)

    assert configs[0].sources.slack is not None
    assert configs[0].sources.slack.dm_conversation_ids == ["D123", "G456"]


def test_init_series_scaffolds_dm_conversation_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    defaults_dir = tmp_path / "user_config" / "defaults"
    defaults_dir.mkdir(parents=True, exist_ok=True)
    (defaults_dir / "settings.toml").write_text(SETTINGS_TOML, encoding="utf-8")
    ensure_local_user_config(tmp_path)
    settings = load_settings(tmp_path)

    event = MeetingEvent(
        uid="event-1",
        title="CAS Strategy Meeting",
        start=SimpleNamespace(isoformat=lambda: "2026-04-13T10:00:00+10:00"),
        end=None,
        calendar_name="Work",
        organizer_email="barry@example.edu",
        attendees=[{"email": "darren@example.edu"}],
    )

    class FakeEventKitClient:
        def __init__(self, _settings):
            pass

        def fetch_events(self, _start, _end):
            return [event]

    monkeypatch.setattr("briefing.main.EventKitClient", FakeEventKitClient)

    exit_code = _init_series(settings, event_uid=None, index=None, force=False)

    assert exit_code == 0
    series_text = (settings.paths.series_dir / "cas-strategy-meeting.yaml").read_text(encoding="utf-8")
    assert "dm_conversation_ids: []" in series_text
