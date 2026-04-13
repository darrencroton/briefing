"""LLM provider abstraction."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .settings import AppSettings


class LLMError(RuntimeError):
    """Raised when LLM execution fails."""


@dataclass(slots=True)
class LLMResponse:
    """Structured provider output."""

    text: str
    raw: str


class ClaudeCLIProvider:
    """Claude Code `--print` provider."""

    def __init__(self, settings: AppSettings):
        self.settings = settings

    def validate(self) -> tuple[bool, str]:
        """Check the provider binary and auth state."""
        version = subprocess.run(
            [self.settings.llm.command, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if version.returncode != 0:
            return False, version.stderr.strip() or version.stdout.strip()
        auth = subprocess.run(
            [self.settings.llm.command, "auth", "status", "--text"],
            capture_output=True,
            text=True,
            check=False,
        )
        if auth.returncode != 0:
            return False, auth.stderr.strip() or auth.stdout.strip()
        return True, auth.stdout.strip() or version.stdout.strip()

    def generate(self, prompt: str) -> LLMResponse:
        """Generate text from a prompt."""
        command = [self.settings.llm.command, "--print", "--output-format", "json"]
        if self.settings.llm.model:
            command.extend(["--model", self.settings.llm.model])
        if self.settings.llm.effort:
            command.extend(["--effort", self.settings.llm.effort])
        completed = subprocess.run(
            command + [prompt],
            capture_output=True,
            text=True,
            timeout=self.settings.llm.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise LLMError(completed.stderr.strip() or completed.stdout.strip())
        try:
            payload = json.loads(completed.stdout)
            text = str(payload.get("result") or payload.get("content") or "").strip()
        except json.JSONDecodeError:
            text = completed.stdout.strip()
        if not text:
            raise LLMError("Claude CLI returned empty output")
        return LLMResponse(text=text, raw=completed.stdout)


def get_provider(settings: AppSettings) -> ClaudeCLIProvider:
    """Return the configured provider implementation."""
    if settings.llm.provider != "claude_cli":
        raise LLMError(f"Unsupported provider: {settings.llm.provider}")
    return ClaudeCLIProvider(settings)

