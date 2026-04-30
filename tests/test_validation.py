from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from briefing.models import ValidationMessage
from briefing.validation import (
    _check_noted_version,
    _check_recording_location_routing,
    _check_sessions_root,
    validate_environment,
)


def test_validate_environment_reports_provider_failure(monkeypatch, app_settings) -> None:
    monkeypatch.setattr(
        "briefing.validation.EventKitClient",
        lambda settings: SimpleNamespace(validate_access=lambda: (True, "ical ok")),
    )
    monkeypatch.setattr(
        "briefing.validation.get_provider",
        lambda settings: SimpleNamespace(validate=lambda: (False, "provider unavailable")),
    )

    messages = validate_environment(app_settings, [])

    assert ValidationMessage("error", "llm_provider", "provider unavailable") in messages


def test_validate_environment_reports_provider_success(monkeypatch, app_settings) -> None:
    monkeypatch.setattr(
        "briefing.validation.EventKitClient",
        lambda settings: SimpleNamespace(validate_access=lambda: (True, "ical ok")),
    )
    monkeypatch.setattr(
        "briefing.validation.get_provider",
        lambda settings: SimpleNamespace(validate=lambda: (True, "Validated CLI provider 'claude' via 'claude'.")),
    )

    messages = validate_environment(app_settings, [])

    assert ValidationMessage(
        "info",
        "llm_provider",
        "Validated CLI provider 'claude' via 'claude'.",
    ) in messages


def test_recording_location_routing_reports_resolved_machine(monkeypatch, app_settings, series_config) -> None:
    app_settings.meeting_intelligence.default_location_type = "office"
    app_settings.meeting_intelligence.location_type_by_host = {"Office-Mac": "office"}
    monkeypatch.setattr("briefing.validation.current_machine_names", lambda: ("Office-Mac", "Office-Mac.local"))
    messages: list[ValidationMessage] = []

    _check_recording_location_routing(app_settings, [series_config], messages)

    assert any(message.code == "recording_location_ok" for message in messages)


def test_recording_location_routing_errors_when_targeted_but_unresolved(
    monkeypatch, app_settings, series_config
) -> None:
    app_settings.meeting_intelligence.default_location_type = "office"
    monkeypatch.setattr("briefing.validation.current_machine_names", lambda: ("Unknown-Mac",))
    messages: list[ValidationMessage] = []

    _check_recording_location_routing(app_settings, [series_config], messages)

    assert ValidationMessage(
        "error",
        "recording_location_unresolved",
        "Recording location routing is configured, but this machine did not match "
        "local_location_type or any location_type_by_host entry.",
    ) in messages


# ---------------------------------------------------------------------------
# sessions_root writability check
# ---------------------------------------------------------------------------


def test_sessions_root_writable_confirms_existing_dir(tmp_path: Path, app_settings) -> None:
    app_settings.meeting_intelligence.sessions_root.mkdir(parents=True, exist_ok=True)
    messages: list[ValidationMessage] = []
    _check_sessions_root(app_settings, messages)
    codes = {m.code for m in messages}
    assert "sessions_root_writable" in codes
    assert "sessions_root_not_writable" not in codes
    assert "sessions_root_missing" not in codes


def test_sessions_root_missing_emits_info_not_error(tmp_path: Path, app_settings) -> None:
    # Validate must not create directories — it should report the absence informatively.
    assert not app_settings.meeting_intelligence.sessions_root.exists()
    messages: list[ValidationMessage] = []
    _check_sessions_root(app_settings, messages)
    assert not app_settings.meeting_intelligence.sessions_root.exists(), (
        "validate must not create sessions_root"
    )
    codes = {m.code for m in messages}
    assert "sessions_root_missing" in codes
    assert "sessions_root_writable" not in codes
    info = [m for m in messages if m.code == "sessions_root_missing"]
    assert info[0].level == "info"


def test_sessions_root_not_writable_emits_error(tmp_path: Path, app_settings, monkeypatch) -> None:
    import tempfile
    messages: list[ValidationMessage] = []

    def fail_tempfile(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", fail_tempfile)
    app_settings.meeting_intelligence.sessions_root.mkdir(parents=True, exist_ok=True)
    _check_sessions_root(app_settings, messages)
    codes = {m.code for m in messages}
    assert "sessions_root_not_writable" in codes


# ---------------------------------------------------------------------------
# noted version / schema compatibility checks
# ---------------------------------------------------------------------------


def _make_version_output(manifest_v: str = "1.0", completion_v: str = "1.0") -> str:
    return json.dumps({
        "ok": True,
        "version": "0.3.0",
        "manifest_schema_version": manifest_v,
        "completion_schema_version": completion_v,
    })


def test_noted_version_ok_emits_version_and_compat(monkeypatch) -> None:
    def mock_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=_make_version_output())

    monkeypatch.setattr(subprocess, "run", mock_run)
    messages: list[ValidationMessage] = []
    _check_noted_version("noted", messages)
    codes = {m.code for m in messages}
    assert "noted_version_ok" in codes
    assert "noted_schema_compat_ok" in codes
    assert "noted_schema_compat_error" not in codes
    assert "noted_version_failed" not in codes


def test_noted_version_schema_compat_error_on_major_mismatch(monkeypatch) -> None:
    def mock_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=_make_version_output(manifest_v="2.0"))

    monkeypatch.setattr(subprocess, "run", mock_run)
    messages: list[ValidationMessage] = []
    _check_noted_version("noted", messages)
    codes = {m.code for m in messages}
    assert "noted_schema_compat_error" in codes
    assert "noted_schema_compat_ok" not in codes
    errors = [m for m in messages if m.code == "noted_schema_compat_error"]
    assert any("manifest" in m.message for m in errors)


def test_noted_version_failed_on_nonzero_exit(monkeypatch) -> None:
    def mock_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)
    messages: list[ValidationMessage] = []
    _check_noted_version("noted", messages)
    codes = {m.code for m in messages}
    assert "noted_version_failed" in codes
    assert "noted_version_ok" not in codes


def test_noted_version_failed_on_timeout(monkeypatch) -> None:
    def mock_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=5)

    monkeypatch.setattr(subprocess, "run", mock_run)
    messages: list[ValidationMessage] = []
    _check_noted_version("noted", messages)
    codes = {m.code for m in messages}
    assert "noted_version_failed" in codes


def test_noted_version_failed_on_bad_json(monkeypatch) -> None:
    def mock_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="not json")

    monkeypatch.setattr(subprocess, "run", mock_run)
    messages: list[ValidationMessage] = []
    _check_noted_version("noted", messages)
    codes = {m.code for m in messages}
    assert "noted_version_failed" in codes


def test_noted_version_schema_compat_error_on_absent_field(monkeypatch) -> None:
    """Missing schema version fields should emit a clear 'absent' error, not an empty-string error."""
    def mock_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "version": "0.3.0"}))

    monkeypatch.setattr(subprocess, "run", mock_run)
    messages: list[ValidationMessage] = []
    _check_noted_version("noted", messages)
    codes = {m.code for m in messages}
    assert "noted_schema_compat_error" in codes
    errors = [m for m in messages if m.code == "noted_schema_compat_error"]
    assert all("absent" in m.message for m in errors)
