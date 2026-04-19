"""Local file source adapter."""

from __future__ import annotations

from pathlib import Path

from .types import SourceContext
from ..models import FileSourceConfig, SourceResult
from ..utils import expand_path, shorten_text


def collect_file_source(context: SourceContext, config: FileSourceConfig) -> SourceResult:
    """Read an arbitrary local file."""
    path = expand_path(config.path, context.settings.repo_root)
    if not path.exists():
        return SourceResult(
            source_type="file",
            label=config.label,
            content="",
            required=config.required,
            status="error",
            error=f"File not found: {path}",
            metadata={"path": str(path)},
        )
    content = path.read_text(encoding="utf-8")
    limited, truncated = shorten_text(
        content,
        config.max_characters or context.settings.files.max_characters,
    )
    return SourceResult(
        source_type="file",
        label=config.label,
        content=limited,
        required=config.required,
        status="ok",
        truncated=truncated,
        metadata={"path": str(path), "empty": not bool(limited.strip())},
    )
