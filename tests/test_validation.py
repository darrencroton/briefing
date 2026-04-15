from __future__ import annotations

from types import SimpleNamespace

from briefing.models import ValidationMessage
from briefing.validation import validate_environment


def test_validate_environment_reports_provider_failure(monkeypatch, app_settings) -> None:
    monkeypatch.setattr(
        "briefing.validation.IcalPalClient",
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
        "briefing.validation.IcalPalClient",
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
