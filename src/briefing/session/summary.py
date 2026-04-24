"""Post-meeting summary generator (B-16)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..llm import CLIProvider, LLMError
from ..settings import AppSettings
from .prompt import PromptInputs, render_post_meeting_prompt

LOGGER = logging.getLogger(__name__)

POST_MEETING_PROMPT_FILENAME = "post_meeting_summary.md"


class SummaryGenerationError(Exception):
    """Raised when the LLM call fails during post-meeting summarisation."""

    exit_code: int = 6


@dataclass(slots=True)
class Summary:
    """LLM-generated post-meeting summary."""

    text: str
    raw: str


def load_post_meeting_prompt_template(settings: AppSettings) -> str:
    """Load the tracked post-meeting prompt template."""
    path = settings.paths.prompt_dir / POST_MEETING_PROMPT_FILENAME
    if not path.exists():
        raise SummaryGenerationError(
            f"Post-meeting prompt template missing: {path}. "
            f"Run ./scripts/setup.sh or copy user_config/defaults."
        )
    return path.read_text(encoding="utf-8")


def generate_summary(
    settings: AppSettings,
    provider: CLIProvider,
    inputs: PromptInputs,
    *,
    debug_key: str | None = None,
) -> Summary:
    """Render the post-meeting prompt and invoke the configured LLM."""
    template = load_post_meeting_prompt_template(settings)
    prompt = render_post_meeting_prompt(template, inputs)

    if settings.logging.debug_prompts and debug_key:
        _write_debug(settings.paths.debug_dir, f"{debug_key}-post-prompt.txt", prompt)

    try:
        response = provider.generate(prompt)
    except LLMError as exc:
        raise SummaryGenerationError(f"Post-meeting LLM call failed: {exc}") from exc

    if settings.logging.debug_llm_output and debug_key:
        _write_debug(settings.paths.debug_dir, f"{debug_key}-post-llm.txt", response.raw)

    return Summary(text=response.text, raw=response.raw)


def _write_debug(debug_dir: Path, filename: str, content: str) -> None:
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / filename).write_text(content, encoding="utf-8")
    except OSError as exc:
        LOGGER.warning("Failed to write debug artefact %s: %s", filename, exc)
