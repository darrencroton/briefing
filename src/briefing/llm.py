"""LLM provider abstraction for supported CLI tools."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from .settings import AppSettings


LOGGER = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when LLM execution fails."""


@dataclass(slots=True)
class LLMResponse:
    """Structured provider output."""

    text: str
    raw: str


class CLIProvider:
    """Base class for supported CLI-based providers."""

    cli_command = ""
    prompt_flag = ""
    extra_flags: tuple[str, ...] = ()
    model_flag = "--model"
    effort_flag = ""
    env_blocklist: tuple[str, ...] = ()
    readiness_timeout_seconds = 15

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.command = settings.llm.command
        self._setup()

    def _setup(self) -> None:
        """Perform provider-specific one-time setup."""

    def validate(self) -> tuple[bool, str]:
        """Check whether the provider can run in the current environment."""
        if not shutil.which(self.command):
            return False, f"Required CLI binary '{self.command}' was not found on PATH."
        try:
            error = self._validate_runtime_ready()
        except LLMError as exc:
            return False, str(exc)
        if error:
            return False, error
        return True, f"Validated CLI provider '{self.settings.llm.provider}' via '{self.command}'."

    def _validate_runtime_ready(self) -> str | None:
        """Return an error message when the provider is not automation-ready."""
        return None

    def _provider_label(self) -> str:
        return self.settings.llm.provider

    def _append_model_args(self, command: list[str]) -> None:
        if self.settings.llm.model and self.model_flag:
            command.extend([self.model_flag, self.settings.llm.model])

    def _append_effort_args(self, command: list[str]) -> None:
        if self.settings.llm.effort and self.effort_flag:
            command.extend([self.effort_flag, self.settings.llm.effort])

    def _append_prompt_args(self, command: list[str], prompt: str) -> None:
        if self.prompt_flag:
            command.extend([self.prompt_flag, prompt])
        else:
            command.append(prompt)

    def _build_command(self, prompt: str) -> list[str]:
        command = [self.command, *self.extra_flags]
        self._append_model_args(command)
        self._append_effort_args(command)
        self._append_prompt_args(command, prompt)
        return command

    def _build_run_environment(self, *, apply_env_blocklist: bool = True) -> dict[str, str]:
        env = os.environ.copy()
        if apply_env_blocklist:
            for key in self.env_blocklist:
                env.pop(key, None)
        return env

    def _run_subprocess(
        self,
        command: list[str],
        *,
        input_text: str | None = None,
        timeout_seconds: int | None = None,
        apply_env_blocklist: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        timeout = timeout_seconds or self.settings.llm.timeout_seconds
        try:
            return subprocess.run(
                command,
                input=input_text,
                capture_output=True,
                env=self._build_run_environment(apply_env_blocklist=apply_env_blocklist),
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"{self.command} timed out after {timeout}s") from exc

    def _run_readiness_check(
        self,
        command: list[str],
        *,
        input_text: str | None = None,
        apply_env_blocklist: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_subprocess(
            command,
            input_text=input_text,
            timeout_seconds=self.readiness_timeout_seconds,
            apply_env_blocklist=apply_env_blocklist,
        )

    @staticmethod
    def _error_output(result: subprocess.CompletedProcess[str]) -> str:
        text = result.stderr.strip() or result.stdout.strip()
        return text[:500] if text else "(no output)"

    def _error_hint(self, error_output: str) -> str | None:
        return None

    def _format_command_failure(self, result: subprocess.CompletedProcess[str]) -> str:
        error_output = self._error_output(result)
        hint = self._error_hint(error_output)
        if hint:
            return f"{self.command} exited with code {result.returncode}: {error_output} {hint}"
        return f"{self.command} exited with code {result.returncode}: {error_output}"

    def _parse_output(self, completed: subprocess.CompletedProcess[str]) -> str:
        output = completed.stdout.strip()
        if not output:
            raise LLMError(f"{self.command} returned empty output")
        return output

    def generate(self, prompt: str) -> LLMResponse:
        """Generate text from a prompt."""
        command = self._build_command(prompt)
        completed = self._run_subprocess(command)
        if completed.returncode != 0:
            raise LLMError(self._format_command_failure(completed))
        text = self._parse_output(completed)
        return LLMResponse(text=text, raw=completed.stdout)


class ClaudeCLIProvider(CLIProvider):
    """Claude Code provider."""

    cli_command = "claude"
    prompt_flag = "-p"
    extra_flags = ("--print", "--output-format", "json")
    model_flag = "--model"
    effort_flag = "--effort"
    env_blocklist = ("ANTHROPIC_API_KEY",)

    def _validate_runtime_ready(self) -> str | None:
        result = self._run_readiness_check([self.command, "auth", "status", "--text"])
        if result.returncode == 0:
            return None
        return (
            "Claude CLI is installed but not authenticated. "
            "Run `claude auth login` before using `briefing`. "
            "For long-lived non-interactive auth, `claude setup-token` may also work if your Claude plan supports it."
        )

    def _error_hint(self, error_output: str) -> str | None:
        lowered = error_output.lower()
        if "not logged in" in lowered or "/login" in lowered or "auth status" in lowered:
            return "Run `claude auth login` before using `briefing`."
        return None

    def _parse_output(self, completed: subprocess.CompletedProcess[str]) -> str:
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return super()._parse_output(completed)

        text = payload.get("result") or payload.get("content") or ""
        if isinstance(text, list):
            text = "\n".join(str(item) for item in text)
        text = str(text).strip()
        if not text:
            raise LLMError("claude returned empty output")
        return text


class CodexCLIProvider(CLIProvider):
    """OpenAI Codex CLI provider."""

    cli_command = "codex"
    extra_flags = ("exec",)
    model_flag = ""
    env_blocklist = ("OPENAI_API_KEY",)

    def _validate_runtime_ready(self) -> str | None:
        result = self._run_readiness_check([self.command, "login", "status"])
        if result.returncode == 0:
            return None
        return (
            "Codex CLI is installed but not authenticated. "
            "Run `codex login`, or save an API-key login with "
            "`printenv OPENAI_API_KEY | codex login --with-api-key`, before using `briefing`."
        )

    def _append_model_args(self, command: list[str]) -> None:
        if self.settings.llm.model:
            command.extend(["-c", f'model="{self.settings.llm.model}"'])

    def _append_effort_args(self, command: list[str]) -> None:
        if self.settings.llm.effort:
            command.extend(["-c", f'model_reasoning_effort="{self.settings.llm.effort}"'])

    def _append_prompt_args(self, command: list[str], prompt: str) -> None:
        command.append("-")

    def _error_hint(self, error_output: str) -> str | None:
        lowered = error_output.lower()
        if "not logged in" in lowered or "login" in lowered or "chatgpt" in lowered:
            return "Run `codex login` before using `briefing`."
        return None

    def generate(self, prompt: str) -> LLMResponse:
        command = self._build_command(prompt)
        output_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
                output_path = Path(handle.name)
            command.extend(["-o", str(output_path)])
            completed = self._run_subprocess(command, input_text=prompt)
            if completed.returncode != 0:
                raise LLMError(self._format_command_failure(completed))
            raw = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
            text = raw.strip()
            if not text:
                raise LLMError(f"{self.command} returned empty output")
            return LLMResponse(text=text, raw=raw)
        finally:
            if output_path and output_path.exists():
                output_path.unlink()


class GeminiCLIProvider(CLIProvider):
    """Gemini CLI provider."""

    cli_command = "gemini"
    prompt_flag = "-p"
    extra_flags = ("-o", "text")
    model_flag = "-m"
    env_blocklist = ("GOOGLE_API_KEY",)

    def _setup(self) -> None:
        if self.settings.llm.effort:
            LOGGER.warning("[WARNING] Gemini CLI ignores llm.effort; using Gemini defaults.")

    def _validate_runtime_ready(self) -> str | None:
        if os.getenv("GEMINI_API_KEY"):
            return None

        vertex_project = os.getenv("GOOGLE_CLOUD_PROJECT")
        vertex_location = os.getenv("GOOGLE_CLOUD_LOCATION")
        service_account_key = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if (
            service_account_key
            and vertex_project
            and vertex_location
            and Path(service_account_key).expanduser().exists()
        ):
            return None

        if vertex_project and vertex_location and shutil.which("gcloud"):
            result = self._run_readiness_check(
                ["gcloud", "auth", "application-default", "print-access-token"],
                apply_env_blocklist=False,
            )
            if result.returncode == 0:
                return None

        return (
            "Gemini CLI is installed but not configured for third-party automation. "
            "For `briefing`, use `GEMINI_API_KEY`, or Vertex AI credentials "
            "(`GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION`). "
            "Do not rely on Gemini CLI's interactive Google OAuth login for this app."
        )

    def _error_hint(self, error_output: str) -> str | None:
        lowered = error_output.lower()
        if "api key" in lowered or "authentication" in lowered or "google cloud" in lowered:
            return (
                "For `briefing`, configure Gemini CLI with `GEMINI_API_KEY` or Vertex AI credentials "
                "instead of interactive Google OAuth."
            )
        return None


class CopilotCLIProvider(CLIProvider):
    """GitHub Copilot CLI provider."""

    cli_command = "copilot"
    prompt_flag = "-p"
    extra_flags = ("--allow-all-tools", "--output-format", "text", "--silent")
    model_flag = "--model"
    effort_flag = "--effort"

    def _validate_runtime_ready(self) -> str | None:
        command = self._build_command("Reply with OK.")
        result = self._run_readiness_check(command)
        if result.returncode == 0 and result.stdout.strip():
            return None
        return self._format_copilot_readiness_failure(result)

    def _error_hint(self, error_output: str) -> str | None:
        lowered = error_output.lower()
        if "no authentication information found" in lowered or "authentication failed" in lowered:
            return (
                "Run `copilot login`, or set `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN`, "
                "before using `briefing`."
            )
        if "access denied by policy settings" in lowered or "403 forbidden" in lowered:
            return "Check that your GitHub account has Copilot CLI access and that org policy allows it."
        return None

    def _format_copilot_readiness_failure(self, result: subprocess.CompletedProcess[str]) -> str:
        error_output = self._error_output(result)
        hint = self._error_hint(error_output)
        if hint:
            return (
                "Copilot CLI is installed but did not complete a non-interactive readiness check. "
                f"{error_output} {hint}"
            )
        return (
            "Copilot CLI is installed but did not complete a non-interactive readiness check. "
            f"{error_output}"
        )


class OpenCodeCLIProvider(CLIProvider):
    """OpenCode provider for local LLMs and cloud APIs."""

    cli_command = "opencode"
    extra_flags = ("run", "--format", "json")
    model_flag = "--model"
    effort_flag = "--variant"

    def _validate_runtime_ready(self) -> str | None:
        if not self.settings.llm.model:
            return (
                "OpenCode requires [llm].model for predictable automation. "
                "Set it to provider/model format, e.g. ollama/llama2 or openai/gpt-5.2."
            )
        if "/" not in self.settings.llm.model:
            return (
                "OpenCode [llm].model must use provider/model format, "
                f"got {self.settings.llm.model!r}."
            )

        result = self._run_readiness_check([self.command, "--version"])
        if result.returncode != 0:
            return (
                "OpenCode is installed but could not be verified. "
                "Run `opencode --version` to diagnose the issue."
            )

        command = self._build_command("Reply with exactly OK.")
        result = self._run_readiness_check(command)
        if result.returncode != 0:
            return (
                "OpenCode CLI is installed but did not complete a non-interactive readiness check. "
                f"{self._format_command_failure(result)}"
            )
        try:
            self._parse_output(result)
        except LLMError as exc:
            error_output = self._error_output(result)
            hint = self._error_hint(error_output)
            hint_text = f" {hint}" if hint else ""
            return (
                "OpenCode CLI is installed but did not complete a non-interactive readiness check. "
                f"{exc}{hint_text}"
            )
        return None

    def _error_hint(self, error_output: str) -> str | None:
        lowered = error_output.lower()
        if "unauthorized" in lowered or "api key" in lowered or "authentication" in lowered:
            return (
                "Set the appropriate API key environment variable for your provider "
                "(for example ANTHROPIC_API_KEY or OPENAI_API_KEY) before using `briefing`."
            )
        if "connection refused" in lowered or "econnrefused" in lowered or "connect:" in lowered:
            return (
                "Ensure your local LLM server is running: "
                "Ollama on port 11434 or LM Studio on port 1234."
            )
        return None

    def _parse_output(self, completed: subprocess.CompletedProcess[str]) -> str:
        parts: list[str] = []
        errors: list[str] = []
        for line in completed.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "error":
                errors.append(self._format_event_error(event))
                continue
            if event.get("type") == "text":
                text = event.get("part", {}).get("text", "")
                if text:
                    parts.append(text)
        if errors:
            message = "; ".join(errors)
            hint = self._error_hint(message)
            hint_text = f" {hint}" if hint else ""
            raise LLMError(f"opencode returned error: {message}{hint_text}")
        text = "".join(parts).strip()
        if not text:
            raise LLMError("opencode returned empty output")
        return text

    @staticmethod
    def _format_event_error(event: dict[str, object]) -> str:
        error = event.get("error")
        if isinstance(error, dict):
            data = error.get("data")
            if isinstance(data, dict):
                message = data.get("message")
                if message:
                    return str(message)
            message = error.get("message")
            if message:
                return str(message)
            name = error.get("name")
            if name:
                return str(name)
        if error:
            return str(error)
        return "unknown error"


_PROVIDERS = {
    "claude": ClaudeCLIProvider,
    "codex": CodexCLIProvider,
    "copilot": CopilotCLIProvider,
    "gemini": GeminiCLIProvider,
    "opencode": OpenCodeCLIProvider,
}


def get_provider(settings: AppSettings) -> CLIProvider:
    """Return the configured provider implementation."""
    try:
        provider_class = _PROVIDERS[settings.llm.provider]
    except KeyError as exc:
        available = ", ".join(sorted(_PROVIDERS))
        raise LLMError(f"Unsupported provider: {settings.llm.provider}. Available providers: {available}") from exc
    return provider_class(settings)
