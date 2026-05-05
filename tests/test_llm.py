from __future__ import annotations

import logging
from pathlib import Path
import subprocess

import pytest

from briefing.llm import (
    ClaudeCLIProvider,
    CodexCLIProvider,
    CopilotCLIProvider,
    GeminiCLIProvider,
    LLMError,
    OpenCodeCLIProvider,
)


@pytest.fixture
def cli_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "briefing.llm.shutil.which",
        lambda command: f"/usr/bin/{command}",
    )


def test_claude_validate_requires_login(
    monkeypatch: pytest.MonkeyPatch,
    cli_on_path: None,
    app_settings,
) -> None:
    provider = ClaudeCLIProvider(app_settings)
    monkeypatch.setattr(
        "briefing.llm.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr="Not logged in"),
    )

    ok, message = provider.validate()

    assert ok is False
    assert "claude auth login" in message


def test_validate_converts_provider_timeout_to_error(cli_on_path: None, app_settings) -> None:
    provider = ClaudeCLIProvider(app_settings)

    def fail_readiness(*_args, **_kwargs):
        raise LLMError("claude timed out after 15s")

    provider._validate_runtime_ready = fail_readiness  # type: ignore[method-assign]

    ok, message = provider.validate()

    assert ok is False
    assert message == "claude timed out after 15s"


def test_claude_generate_adds_auth_hint(cli_on_path: None, app_settings) -> None:
    provider = ClaudeCLIProvider(app_settings)
    provider._run_subprocess = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["claude"],
        1,
        stdout="",
        stderr="Not logged in · Please run /login",
    )

    with pytest.raises(LLMError, match=r"claude auth login"):
        provider.generate("prompt")


def test_claude_builds_command_with_effort(cli_on_path: None, app_settings) -> None:
    app_settings.llm.model = "claude-sonnet-4-6"
    app_settings.llm.effort = "high"

    provider = ClaudeCLIProvider(app_settings)

    assert provider._build_command("prompt") == [
        "claude",
        "--print",
        "--output-format",
        "json",
        "--model",
        "claude-sonnet-4-6",
        "--effort",
        "high",
        "-p",
        "prompt",
    ]


def test_codex_validate_requires_login(
    monkeypatch: pytest.MonkeyPatch,
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "codex"
    app_settings.llm.command = "codex"
    provider = CodexCLIProvider(app_settings)
    monkeypatch.setattr(
        "briefing.llm.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="Not logged in", stderr=""),
    )

    ok, message = provider.validate()

    assert ok is False
    assert "codex login" in message


def test_codex_builds_command_with_effort(cli_on_path: None, app_settings) -> None:
    app_settings.llm.provider = "codex"
    app_settings.llm.command = "codex"
    app_settings.llm.model = "gpt-5.4"
    app_settings.llm.effort = "medium"

    provider = CodexCLIProvider(app_settings)

    assert provider._build_command("prompt") == [
        "codex",
        "exec",
        "-c",
        'model="gpt-5.4"',
        "-c",
        'model_reasoning_effort="medium"',
        "-",
    ]


def test_codex_generate_reads_output_file(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "codex"
    app_settings.llm.command = "codex"
    provider = CodexCLIProvider(app_settings)
    captured: dict[str, object] = {}

    def fake_run(command: list[str], *, input_text: str | None = None, **_kwargs) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["input_text"] = input_text
        output_index = command.index("-o") + 1
        Path(command[output_index]).write_text("Generated summary\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="session banner", stderr="")

    provider._run_subprocess = fake_run  # type: ignore[method-assign]

    response = provider.generate("prompt body")

    assert response.text == "Generated summary"
    assert response.raw == "Generated summary\n"
    assert captured["input_text"] == "prompt body"
    assert "-o" in captured["command"]


def test_gemini_validate_accepts_api_key(
    monkeypatch: pytest.MonkeyPatch,
    cli_on_path: None,
    app_settings,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    app_settings.llm.provider = "gemini"
    app_settings.llm.command = "gemini"

    provider = GeminiCLIProvider(app_settings)
    ok, message = provider.validate()

    assert ok is True
    assert "gemini" in message


def test_gemini_ignores_effort_and_warns_once(
    monkeypatch: pytest.MonkeyPatch,
    cli_on_path: None,
    caplog: pytest.LogCaptureFixture,
    app_settings,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    app_settings.llm.provider = "gemini"
    app_settings.llm.command = "gemini"
    app_settings.llm.effort = "high"

    with caplog.at_level(logging.WARNING):
        provider = GeminiCLIProvider(app_settings)

    assert provider._build_command("prompt") == ["gemini", "-o", "text", "-m", "sonnet", "-p", "prompt"]
    assert [record.message for record in caplog.records] == [
        "[WARNING] Gemini CLI ignores llm.effort; using Gemini defaults."
    ]


def test_gemini_requires_supported_automation_credentials(
    monkeypatch: pytest.MonkeyPatch,
    cli_on_path: None,
    app_settings,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    app_settings.llm.provider = "gemini"
    app_settings.llm.command = "gemini"

    provider = GeminiCLIProvider(app_settings)
    ok, message = provider.validate()

    assert ok is False
    assert "GEMINI_API_KEY" in message


def test_copilot_validate_accepts_token_env_var(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "copilot"
    app_settings.llm.command = "copilot"

    provider = CopilotCLIProvider(app_settings)
    provider._run_readiness_check = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["copilot"],
        0,
        stdout="OK\n",
        stderr="",
    )
    ok, message = provider.validate()

    assert ok is True
    assert "copilot" in message


def test_copilot_builds_command_with_effort(cli_on_path: None, app_settings) -> None:
    app_settings.llm.provider = "copilot"
    app_settings.llm.command = "copilot"
    app_settings.llm.model = "gpt-5.2"
    app_settings.llm.effort = "low"

    provider = CopilotCLIProvider(app_settings)

    assert provider._build_command("prompt") == [
        "copilot",
        "--allow-all-tools",
        "--output-format",
        "text",
        "--silent",
        "--model",
        "gpt-5.2",
        "--effort",
        "low",
        "-p",
        "prompt",
    ]


def test_copilot_requires_login_or_token(
    monkeypatch: pytest.MonkeyPatch,
    cli_on_path: None,
    app_settings,
) -> None:
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    app_settings.llm.provider = "copilot"
    app_settings.llm.command = "copilot"

    provider = CopilotCLIProvider(app_settings)
    provider._run_readiness_check = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["copilot"],
        1,
        stdout="",
        stderr="No authentication information found",
    )
    ok, message = provider.validate()

    assert ok is False
    assert "copilot login" in message


def test_copilot_validate_rejects_generic_github_auth_without_copilot_access(
    monkeypatch: pytest.MonkeyPatch,
    cli_on_path: None,
    app_settings,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "test-token")
    app_settings.llm.provider = "copilot"
    app_settings.llm.command = "copilot"

    provider = CopilotCLIProvider(app_settings)
    provider._run_readiness_check = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["copilot"],
        1,
        stdout="",
        stderr="403 Forbidden",
    )

    ok, message = provider.validate()

    assert ok is False
    assert "Copilot CLI is installed but did not complete a non-interactive readiness check." in message
    assert "Copilot CLI access" in message


def test_opencode_validate_accepts_working_binary(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    app_settings.llm.model = "ollama/llama2"

    provider = OpenCodeCLIProvider(app_settings)

    def fake_readiness(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if command == ["opencode", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="opencode 1.14.35\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"type":"text","part":{"text":"OK"}}\n',
            stderr="",
        )

    provider._run_readiness_check = fake_readiness  # type: ignore[method-assign]
    ok, message = provider.validate()

    assert ok is True
    assert "opencode" in message


def test_opencode_validate_requires_model(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    app_settings.llm.model = ""

    provider = OpenCodeCLIProvider(app_settings)
    ok, message = provider.validate()

    assert ok is False
    assert "provider/model" in message


def test_opencode_validate_requires_provider_model_format(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    app_settings.llm.model = "llama2"

    provider = OpenCodeCLIProvider(app_settings)
    ok, message = provider.validate()

    assert ok is False
    assert "provider/model" in message


def test_opencode_validate_returns_error_on_failure(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    app_settings.llm.model = "ollama/llama2"

    provider = OpenCodeCLIProvider(app_settings)
    provider._run_readiness_check = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["opencode", "--version"],
        1,
        stdout="",
        stderr="opencode: command not found",
    )
    ok, message = provider.validate()

    assert ok is False
    assert "opencode --version" in message


def test_opencode_validate_rejects_json_error_event(
    cli_on_path: None,
    app_settings,
) -> None:
    import json as _json

    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    app_settings.llm.model = "invalid/invalid"

    provider = OpenCodeCLIProvider(app_settings)

    def fake_readiness(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if command == ["opencode", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="opencode 1.14.35\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_json.dumps({
                "type": "error",
                "error": {"data": {"message": "Model not found: invalid/invalid."}},
            }),
            stderr="",
        )

    provider._run_readiness_check = fake_readiness  # type: ignore[method-assign]

    ok, message = provider.validate()

    assert ok is False
    assert "Model not found: invalid/invalid" in message


def test_opencode_builds_command_with_model_and_effort(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    app_settings.llm.model = "ollama/llama3.2"
    app_settings.llm.effort = "medium"

    provider = OpenCodeCLIProvider(app_settings)

    assert provider._build_command("prompt") == [
        "opencode",
        "run",
        "--format",
        "json",
        "--model",
        "ollama/llama3.2",
        "--variant",
        "medium",
        "prompt",
    ]


def test_opencode_builds_command_without_effort(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    app_settings.llm.model = "anthropic/claude-sonnet-4-6"
    app_settings.llm.effort = ""

    provider = OpenCodeCLIProvider(app_settings)

    assert provider._build_command("prompt") == [
        "opencode",
        "run",
        "--format",
        "json",
        "--model",
        "anthropic/claude-sonnet-4-6",
        "prompt",
    ]


def test_opencode_generate_parses_ndjson_text_events(
    cli_on_path: None,
    app_settings,
) -> None:
    import json as _json

    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    provider = OpenCodeCLIProvider(app_settings)

    ndjson_output = "\n".join([
        _json.dumps({"type": "step_start", "timestamp": 1, "sessionID": "s1", "part": {"type": "step-start"}}),
        _json.dumps({"type": "text", "timestamp": 2, "sessionID": "s1", "part": {"type": "text", "text": "Hello, "}}),
        _json.dumps({"type": "text", "timestamp": 3, "sessionID": "s1", "part": {"type": "text", "text": "world!"}}),
        _json.dumps({"type": "step_finish", "timestamp": 4, "sessionID": "s1", "part": {"type": "step-finish"}}),
    ])
    provider._run_subprocess = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["opencode", "run"],
        0,
        stdout=ndjson_output,
        stderr="",
    )

    response = provider.generate("prompt body")

    assert response.text == "Hello, world!"
    assert response.raw == ndjson_output


def test_opencode_generate_raises_on_empty_text_events(
    cli_on_path: None,
    app_settings,
) -> None:
    import json as _json

    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    provider = OpenCodeCLIProvider(app_settings)

    ndjson_output = "\n".join([
        _json.dumps({"type": "step_start", "timestamp": 1, "sessionID": "s1", "part": {}}),
        _json.dumps({"type": "step_finish", "timestamp": 2, "sessionID": "s1", "part": {}}),
    ])
    provider._run_subprocess = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["opencode", "run"],
        0,
        stdout=ndjson_output,
        stderr="",
    )

    with pytest.raises(LLMError, match="empty output"):
        provider.generate("prompt body")


def test_opencode_generate_raises_on_json_error_event(
    cli_on_path: None,
    app_settings,
) -> None:
    import json as _json

    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    provider = OpenCodeCLIProvider(app_settings)

    ndjson_output = _json.dumps({
        "type": "error",
        "error": {
            "name": "UnknownError",
            "data": {"message": "Model not found: invalid/invalid."},
        },
    })
    provider._run_subprocess = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["opencode", "run"],
        0,
        stdout=ndjson_output,
        stderr="",
    )

    with pytest.raises(LLMError, match="Model not found: invalid/invalid"):
        provider.generate("prompt body")


def test_opencode_generate_adds_connection_hint(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    provider = OpenCodeCLIProvider(app_settings)
    provider._run_subprocess = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["opencode", "run"],
        1,
        stdout="",
        stderr="connect: connection refused 127.0.0.1:11434",
    )

    with pytest.raises(LLMError, match=r"port 11434"):
        provider.generate("prompt")


def test_opencode_generate_adds_api_key_hint(
    cli_on_path: None,
    app_settings,
) -> None:
    app_settings.llm.provider = "opencode"
    app_settings.llm.command = "opencode"
    provider = OpenCodeCLIProvider(app_settings)
    provider._run_subprocess = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        ["opencode", "run"],
        1,
        stdout="",
        stderr="Unauthorized: invalid API key",
    )

    with pytest.raises(LLMError, match=r"API key"):
        provider.generate("prompt")
