"""Runtime validation checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile

from .calendar import EventKitClient
from .llm import get_provider
from .location_routing import current_machine_names, resolve_local_location_type
from .models import ValidationMessage
from .settings import AppSettings, load_env_file
from .sources.notion_source import NotionClient
from .sources.slack_source import SlackClient
from .utils import expand_path

_MAJOR_ONE = re.compile(r"^1\.[0-9]+$")


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

    _check_sessions_root(settings, messages)
    _check_recording_location_routing(settings, series_configs, messages)

    noted_on_path = shutil.which(settings.meeting_intelligence.noted_command)
    if noted_on_path:
        messages.append(
            ValidationMessage(
                "info",
                "noted_command_ok",
                f"noted command found: {settings.meeting_intelligence.noted_command}",
            )
        )
        _check_noted_version(settings.meeting_intelligence.noted_command, messages)
    else:
        messages.append(
            ValidationMessage(
                "warning",
                "noted_command_missing",
                f"noted command not found on PATH: {settings.meeting_intelligence.noted_command}",
            )
        )

    if not series_configs:
        messages.append(
            ValidationMessage("warning", "no_series_configs", "No meeting series configs were found")
        )
    else:
        messages.append(
            ValidationMessage("info", "series_configs_ok", f"Loaded {len(series_configs)} series config(s)")
        )

    calendar_client = EventKitClient(settings)
    ok, message = calendar_client.validate_access()
    messages.append(ValidationMessage("info" if ok else "error", "eventkit", message))

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

    email_needed = any(config.sources.emails for config in series_configs)
    if email_needed:
        from .sources.email_source import MailAdapter
        adapter = MailAdapter(timeout=settings.email.request_timeout_seconds)
        ok, message = adapter.validate()
        messages.append(ValidationMessage("info" if ok else "error", "email", message))

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


def _check_recording_location_routing(
    settings: AppSettings,
    series_configs,
    messages: list[ValidationMessage],
) -> None:
    """Validate host/location routing when targeted meeting locations are configured."""
    has_default_location = bool(settings.meeting_intelligence.default_location_type)
    untargeted_series = [
        config.series_id
        for config in series_configs
        if not getattr(config.recording, "location_type", None)
    ]
    has_targeted_location = has_default_location or len(untargeted_series) < len(series_configs)
    if (
        settings.meeting_intelligence.location_type_by_host
        and not has_default_location
        and untargeted_series
    ):
        messages.append(
            ValidationMessage(
                "warning",
                "meeting_location_routing_incomplete",
                "Host location routing is configured, but these series have no location_type "
                f"and no default_location_type is set: {', '.join(untargeted_series)}.",
            )
        )
    if not has_targeted_location:
        return

    names = current_machine_names()
    local_location = resolve_local_location_type(
        local_location_type=settings.meeting_intelligence.local_location_type,
        location_type_by_host=settings.meeting_intelligence.location_type_by_host,
        machine_names=names,
    )
    if local_location:
        messages.append(
            ValidationMessage(
                "info",
                "recording_location_ok",
                f"Meeting location for this machine is {local_location!r} "
                f"(machine names: {', '.join(names) or 'unknown'}).",
            )
        )
    else:
        messages.append(
            ValidationMessage(
                "error",
                "recording_location_unresolved",
                "Meeting location routing is configured, but this machine did not match "
                "local_location_type or any location_type_by_host entry.",
            )
        )


def _check_sessions_root(settings: AppSettings, messages: list[ValidationMessage]) -> None:
    """Verify sessions_root exists and is writable; report if not yet created."""
    sessions_root = settings.meeting_intelligence.sessions_root
    if not sessions_root.exists():
        messages.append(
            ValidationMessage(
                "info",
                "sessions_root_missing",
                f"sessions_root does not exist yet (will be created on first use): {sessions_root}",
            )
        )
        return
    try:
        with tempfile.NamedTemporaryFile(dir=sessions_root, prefix=".validate-", delete=True):
            pass
        messages.append(
            ValidationMessage("info", "sessions_root_writable", f"sessions_root is writable: {sessions_root}")
        )
    except OSError as exc:
        messages.append(
            ValidationMessage(
                "error",
                "sessions_root_not_writable",
                f"sessions_root is not writable: {sessions_root} ({exc})",
            )
        )


def _check_noted_version(noted_command: str, messages: list[ValidationMessage]) -> None:
    """Run `noted version`, verify it responds, and check schema compatibility."""
    try:
        result = subprocess.run(
            [noted_command, "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        messages.append(
            ValidationMessage("warning", "noted_version_failed", f"`{noted_command} version` timed out")
        )
        return
    except OSError as exc:
        messages.append(
            ValidationMessage("warning", "noted_version_failed", f"`{noted_command} version` failed to run: {exc}")
        )
        return

    if result.returncode != 0:
        messages.append(
            ValidationMessage(
                "warning",
                "noted_version_failed",
                f"`{noted_command} version` exited {result.returncode}",
            )
        )
        return

    try:
        payload = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError) as exc:
        messages.append(
            ValidationMessage("warning", "noted_version_failed", f"`{noted_command} version` output is not JSON: {exc}")
        )
        return

    app_version = payload.get("version", "unknown")
    messages.append(
        ValidationMessage("info", "noted_version_ok", f"noted version: {app_version}")
    )

    raw_manifest_v = payload.get("manifest_schema_version")
    raw_completion_v = payload.get("completion_schema_version")
    manifest_v = str(raw_manifest_v) if raw_manifest_v is not None else None
    completion_v = str(raw_completion_v) if raw_completion_v is not None else None
    if manifest_v and _MAJOR_ONE.match(manifest_v) and completion_v and _MAJOR_ONE.match(completion_v):
        messages.append(
            ValidationMessage(
                "info",
                "noted_schema_compat_ok",
                f"noted schema versions compatible: manifest={manifest_v} completion={completion_v}",
            )
        )
    else:
        for label, version in (("manifest", manifest_v), ("completion", completion_v)):
            if version is None:
                messages.append(
                    ValidationMessage(
                        "error",
                        "noted_schema_compat_error",
                        f"noted {label}_schema_version absent from `noted version` output",
                    )
                )
            elif not _MAJOR_ONE.match(version):
                messages.append(
                    ValidationMessage(
                        "error",
                        "noted_schema_compat_error",
                        f"noted {label}_schema_version {version!r} is not compatible with briefing (expects 1.x)",
                    )
                )
