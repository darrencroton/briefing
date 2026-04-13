"""Runtime validation checks."""

from __future__ import annotations

from .calendar import IcalPalClient
from .llm import get_provider
from .models import ValidationMessage
from .settings import AppSettings, load_env_file
from .sources.notion_source import NotionClient
from .sources.slack_source import SlackClient
from .utils import expand_path


def validate_environment(settings: AppSettings, series_configs) -> list[ValidationMessage]:
    """Run local and remote validation checks."""
    messages: list[ValidationMessage] = []
    env = load_env_file(settings.paths.env_file)

    if not settings.paths.vault_root.exists():
        messages.append(
            ValidationMessage("error", "vault_root_missing", f"Vault root not found: {settings.paths.vault_root}")
        )
    else:
        messages.append(
            ValidationMessage("info", "vault_root_ok", f"Vault root found: {settings.paths.vault_root}")
        )

    if not settings.paths.prompt_dir.joinpath(settings.llm.prompt_template).exists():
        messages.append(
            ValidationMessage("error", "prompt_missing", "Prompt template is missing")
        )
    if not settings.paths.template_dir.joinpath(settings.llm.note_template).exists():
        messages.append(
            ValidationMessage("error", "note_template_missing", "Note template is missing")
        )

    if not series_configs:
        messages.append(
            ValidationMessage("warning", "no_series_configs", "No meeting series configs were found")
        )
    else:
        messages.append(
            ValidationMessage("info", "series_configs_ok", f"Loaded {len(series_configs)} series config(s)")
        )

    ical_client = IcalPalClient(settings)
    ok, message = ical_client.validate_access()
    messages.append(ValidationMessage("info" if ok else "error", "icalpal", message))

    provider = get_provider(settings)
    ok, message = provider.validate()
    messages.append(ValidationMessage("info" if ok else "error", "llm_provider", message))

    slack_needed = any(config.sources.slack for config in series_configs)
    if slack_needed:
        token = env.get("SLACK_USER_TOKEN")
        if not token:
            messages.append(
                ValidationMessage("error", "slack_token_missing", "SLACK_USER_TOKEN is required by one or more series")
            )
        else:
            client = SlackClient(
                token=token,
                timeout=settings.slack.request_timeout_seconds,
                page_size=settings.slack.page_size,
                max_messages=settings.slack.max_messages,
            )
            ok, message = client.validate()
            messages.append(ValidationMessage("info" if ok else "error", "slack", message))

    notion_needed = any(config.sources.notion for config in series_configs)
    if notion_needed:
        token = env.get("NOTION_TOKEN")
        if not token:
            messages.append(
                ValidationMessage("error", "notion_token_missing", "NOTION_TOKEN is required by one or more series")
            )
        else:
            client = NotionClient(
                token=token,
                version=settings.notion.version,
                timeout=settings.notion.request_timeout_seconds,
            )
            ok, message = client.validate()
            messages.append(ValidationMessage("info" if ok else "error", "notion", message))

    for config in series_configs:
        for file_source in config.sources.files:
            path = expand_path(file_source.path, settings.repo_root)
            if path.exists():
                messages.append(ValidationMessage("info", "file_source_ok", f"{config.series_id}: {path}"))
            else:
                messages.append(
                    ValidationMessage("error", "file_source_missing", f"{config.series_id}: missing file {path}")
                )

    if not settings.paths.env_file.exists():
        messages.append(
            ValidationMessage("warning", "env_file_missing", f"Env file not found: {settings.paths.env_file}")
        )
    else:
        messages.append(
            ValidationMessage("info", "env_file_ok", f"Env file found: {settings.paths.env_file}")
        )

    return messages
