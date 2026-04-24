"""Workspace bootstrap helpers for first-run setup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from .bootstrap import default_project_root, ensure_local_user_config
from .llm import get_provider
from .settings import load_settings


_RUNTIME_DIRECTORIES = (
    Path("logs"),
    Path("sessions"),
    Path("state/occurrences"),
    Path("state/session-plans"),
    Path("state/runs"),
    Path("tmp"),
    Path("user_config/series"),
)


@dataclass(frozen=True, slots=True)
class SetupSummary:
    """Outcome of preparing a local briefing workspace."""

    created_user_files: tuple[Path, ...]
    created_runtime_dirs: tuple[Path, ...]
    provider_validated: bool
    provider_warning: str | None
    llm_provider: str


def ensure_runtime_directories(project_root: Path | None = None) -> tuple[Path, ...]:
    """Create local runtime directories under the project root."""
    root = (project_root or default_project_root()).resolve()
    created: list[Path] = []
    for relative_path in _RUNTIME_DIRECTORIES:
        target = root / relative_path
        if not target.exists():
            created.append(target)
        target.mkdir(parents=True, exist_ok=True)
    return tuple(created)


def prepare_workspace(project_root: Path | None = None) -> SetupSummary:
    """Bootstrap local config files and runtime directories."""
    root = (project_root or default_project_root()).resolve()
    created_runtime_dirs = ensure_runtime_directories(root)
    created_user_files = tuple(ensure_local_user_config(root))
    settings = load_settings(root)
    provider = get_provider(settings)
    ok, message = provider.validate()
    if not ok:
        if created_user_files:
            return SetupSummary(
                created_user_files=created_user_files,
                created_runtime_dirs=created_runtime_dirs,
                provider_validated=False,
                provider_warning=(
                    f"LLM provider validation failed for {settings.llm.provider}: {message}\n"
                    "Setup bootstrapped the default local configuration, so this check was not treated as fatal.\n"
                    "Edit user_config/settings.toml if needed, then rerun ./scripts/setup.sh or run `uv run briefing validate`."
                ),
                llm_provider=settings.llm.provider,
            )
        raise ValueError(f"LLM provider validation failed for {settings.llm.provider}: {message}")
    return SetupSummary(
        created_user_files=created_user_files,
        created_runtime_dirs=created_runtime_dirs,
        provider_validated=True,
        provider_warning=None,
        llm_provider=settings.llm.provider,
    )


def main() -> int:
    """Run the setup bootstrap CLI."""
    try:
        summary = prepare_workspace()
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1

    for path in summary.created_user_files:
        print(f"Bootstrapped local config: {path}")
    for path in summary.created_runtime_dirs:
        print(f"Created runtime directory: {path}")
    if summary.provider_validated:
        print(f"Validated LLM provider prerequisites: {summary.llm_provider}")
    elif summary.provider_warning:
        print(summary.provider_warning, file=sys.stderr)

    print("Setup complete. Edit user_config/settings.toml, then run `uv run briefing validate`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
