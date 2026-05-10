from __future__ import annotations

import logging
from pathlib import Path
import subprocess

import pytest
import requests

from briefing.llm import (
    ClaudeCLIProvider,
    CodexCLIProvider,
    CopilotCLIProvider,
    GeminiCLIProvider,
    LLMError,
    OpenAICompatibleAPIProvider,
)


@pytest.fixture
def cli_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "briefing.llm.shutil.which",
        lambda command: f"/usr/bin/{command}",
    )


# ---------------------------------------------------------------------------
# Fake helpers for OpenAI-compatible API tests
# ---------------------------------------------------------------------------

class FakeModelsResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeOpenAIClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.chat = FakeChat()


class FakeChat:
    def __init__(self) -> None:
        self.completions = FakeCompletions()


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        message = type("Message", (), {"content": "model output"})
        choice = type("Choice", (), {"message": message, "finish_reason": "stop"})
        return type("Response", (), {"choices": [choice]})()


# ---------------------------------------------------------------------------
# Claude CLI provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Codex CLI provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Gemini CLI provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Copilot CLI provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# OpenAI-compatible API provider
# ---------------------------------------------------------------------------

def _make_api_provider(
    app_settings,
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_url: str = "http://127.0.0.1:1234/v1",
    model: str = "local-model",
    api_key_env: str = "",
) -> tuple[OpenAICompatibleAPIProvider, list[FakeOpenAIClient]]:
    clients: list[FakeOpenAIClient] = []

    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        client = FakeOpenAIClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    app_settings.llm.provider = "openai-compatible"
    app_settings.llm.base_url = base_url
    app_settings.llm.model = model
    app_settings.llm.api_key_env = api_key_env
    return OpenAICompatibleAPIProvider(app_settings), clients


def test_openai_compatible_validate_returns_true_when_endpoint_reachable(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    provider, _ = _make_api_provider(app_settings, monkeypatch, model="local-model")
    monkeypatch.setattr(
        "briefing.llm.requests.get",
        lambda *args, **kwargs: FakeModelsResponse({"data": [{"id": "local-model"}]}),
    )

    ok, message = provider.validate()

    assert ok is True
    assert "openai-compatible" in message
    assert "127.0.0.1:1234" in message


def test_openai_compatible_validate_fails_when_endpoint_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    provider, _ = _make_api_provider(app_settings, monkeypatch)

    def fail_get(*args, **kwargs):
        raise requests.ConnectionError("Connection refused")

    monkeypatch.setattr("briefing.llm.requests.get", fail_get)

    ok, message = provider.validate()

    assert ok is False
    assert "not reachable" in message


def test_openai_compatible_validate_strips_trailing_slash_and_forms_correct_url(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    monkeypatch.setenv("LOCAL_LLM_KEY", "test-key")
    # base_url has a trailing slash — _setup() must strip it
    provider, _ = _make_api_provider(
        app_settings, monkeypatch,
        base_url="http://127.0.0.1:1234/v1/",
        api_key_env="LOCAL_LLM_KEY",
    )
    captured: dict[str, object] = {}

    def fake_get(url: str, headers: dict, timeout: float) -> FakeModelsResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeModelsResponse({"data": [{"id": "local-model"}]})

    monkeypatch.setattr("briefing.llm.requests.get", fake_get)

    provider.validate()

    assert captured == {
        "url": "http://127.0.0.1:1234/v1/models",
        "headers": {"Authorization": "Bearer test-key"},
        "timeout": 15.0,
    }


def test_openai_compatible_generate_sends_correct_request(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    app_settings.llm.temperature = 0.15
    app_settings.llm.max_output_tokens = 4096
    provider, clients = _make_api_provider(app_settings, monkeypatch)

    response = provider.generate("the full prompt")

    assert response.text == "model output"
    assert clients[0].chat.completions.calls == [
        {
            "model": "local-model",
            "messages": [{"role": "user", "content": "the full prompt"}],
            "temperature": 0.15,
            "max_tokens": 4096,
        }
    ]


def test_openai_compatible_generate_keeps_response_metadata_in_raw(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    class FakeResponseWithDump:
        choices = [
            type(
                "Choice",
                (),
                {
                    "message": type("Message", (), {"content": "model output"}),
                    "finish_reason": "stop",
                },
            )()
        ]

        def model_dump_json(self, *, indent: int) -> str:
            assert indent == 2
            return '{"id":"chatcmpl-local","usage":{"completion_tokens":12}}'

    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        client = FakeOpenAIClient(**kwargs)
        client.chat.completions.create = lambda **kw: FakeResponseWithDump()
        return client

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    app_settings.llm.provider = "openai-compatible"
    app_settings.llm.base_url = "http://127.0.0.1:1234/v1"
    app_settings.llm.model = "local-model"
    app_settings.llm.api_key_env = ""

    provider = OpenAICompatibleAPIProvider(app_settings)

    response = provider.generate("prompt")

    assert response.text == "model output"
    assert "chatcmpl-local" in response.raw
    assert "completion_tokens" in response.raw


def test_openai_compatible_strips_auth_header_when_no_api_key_configured(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    import httpx

    captured_http_client: list[object] = []

    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        captured_http_client.append(kwargs.get("http_client"))
        return FakeOpenAIClient(**{k: v for k, v in kwargs.items() if k != "http_client"})

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    app_settings.llm.provider = "openai-compatible"
    app_settings.llm.base_url = "http://127.0.0.1:1234/v1"
    app_settings.llm.model = "local-model"
    app_settings.llm.api_key_env = ""

    OpenAICompatibleAPIProvider(app_settings)

    http_client = captured_http_client[0]
    assert isinstance(http_client, httpx.Client)
    # Verify the event hook strips any Authorization header the SDK injects
    fake_req = httpx.Request(
        "POST", "http://127.0.0.1:1234/v1/chat/completions",
        headers={"authorization": "Bearer not-needed", "content-type": "application/json"},
    )
    for hook in http_client.event_hooks["request"]:
        hook(fake_req)
    assert "authorization" not in dict(fake_req.headers)
    assert "content-type" in dict(fake_req.headers)


def test_openai_compatible_authenticated_client_uses_api_key_without_http_client_override(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    monkeypatch.setenv("MY_LLM_KEY", "real-api-key")
    all_kwargs: list[dict[str, object]] = []

    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        all_kwargs.append(dict(kwargs))
        return FakeOpenAIClient(**{k: v for k, v in kwargs.items() if k != "http_client"})

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    app_settings.llm.provider = "openai-compatible"
    app_settings.llm.base_url = "http://127.0.0.1:1234/v1"
    app_settings.llm.model = "local-model"
    app_settings.llm.api_key_env = "MY_LLM_KEY"

    OpenAICompatibleAPIProvider(app_settings)

    assert all_kwargs[0]["api_key"] == "real-api-key"
    assert "http_client" not in all_kwargs[0]


def test_openai_compatible_generate_raises_on_empty_output(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        client = FakeOpenAIClient(**kwargs)
        message = type("Message", (), {"content": ""})
        choice = type("Choice", (), {"message": message, "finish_reason": "stop"})
        client.chat.completions.create = lambda **kw: type("Response", (), {"choices": [choice]})()
        return client

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    app_settings.llm.provider = "openai-compatible"
    app_settings.llm.base_url = "http://127.0.0.1:1234/v1"
    app_settings.llm.model = "local-model"
    app_settings.llm.api_key_env = ""

    provider = OpenAICompatibleAPIProvider(app_settings)

    with pytest.raises(LLMError, match="empty output"):
        provider.generate("prompt")


def test_openai_compatible_generate_wraps_sdk_errors(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    provider, clients = _make_api_provider(app_settings, monkeypatch)
    provider._openai_error = RuntimeError
    clients[0].chat.completions.create = lambda **kw: (_ for _ in ()).throw(
        RuntimeError("connection refused")
    )

    with pytest.raises(LLMError, match="request failed: connection refused"):
        provider.generate("prompt")


def test_openai_compatible_generate_raises_on_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        client = FakeOpenAIClient(**kwargs)
        client.chat.completions.create = lambda **kw: type("Response", (), {"choices": []})()
        return client

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    app_settings.llm.provider = "openai-compatible"
    app_settings.llm.base_url = "http://127.0.0.1:1234/v1"
    app_settings.llm.model = "local-model"
    app_settings.llm.api_key_env = ""

    provider = OpenAICompatibleAPIProvider(app_settings)

    with pytest.raises(LLMError, match="malformed response"):
        provider.generate("prompt")


def test_openai_compatible_generate_raises_on_truncation(
    monkeypatch: pytest.MonkeyPatch,
    app_settings,
) -> None:
    def fake_openai(**kwargs: object) -> FakeOpenAIClient:
        client = FakeOpenAIClient(**kwargs)
        message = type("Message", (), {"content": "truncated"})
        choice = type("Choice", (), {"message": message, "finish_reason": "length"})
        client.chat.completions.create = lambda **kw: type("Response", (), {"choices": [choice]})()
        return client

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    app_settings.llm.provider = "openai-compatible"
    app_settings.llm.base_url = "http://127.0.0.1:1234/v1"
    app_settings.llm.model = "local-model"
    app_settings.llm.api_key_env = ""
    app_settings.llm.max_output_tokens = 512

    provider = OpenAICompatibleAPIProvider(app_settings)

    with pytest.raises(LLMError, match=r"finish_reason=length.*512"):
        provider.generate("prompt")
