"""Bootstrap helpers for local user configuration."""

from __future__ import annotations

from pathlib import Path
import shutil


USER_CONFIG_DIRNAME = "user_config"
DEFAULTS_DIRNAME = "defaults"
LOCAL_CONFIG_RELATIVE_PATHS = (
    Path("settings.toml"),
)


def default_project_root() -> Path:
    """Return the repository root for the installed package."""
    return Path(__file__).resolve().parents[2]


def user_config_dir(project_root: Path | None = None) -> Path:
    """Return the user-config root directory."""
    root = (project_root or default_project_root()).resolve()
    return root / USER_CONFIG_DIRNAME


def user_config_defaults_dir(project_root: Path | None = None) -> Path:
    """Return the tracked defaults directory."""
    return user_config_dir(project_root) / DEFAULTS_DIRNAME


def default_settings_path(project_root: Path | None = None) -> Path:
    """Return the tracked default settings file path."""
    return user_config_defaults_dir(project_root) / "settings.toml"


def local_settings_path(project_root: Path | None = None) -> Path:
    """Return the mutable local settings file path."""
    return user_config_dir(project_root) / "settings.toml"


def ensure_local_user_config(project_root: Path | None = None) -> list[Path]:
    """Copy tracked defaults into local user config paths when missing."""
    root = (project_root or default_project_root()).resolve()
    config_dir = user_config_dir(root)
    defaults_dir = user_config_defaults_dir(root)
    config_dir.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    for relative_path in LOCAL_CONFIG_RELATIVE_PATHS:
        source = defaults_dir / relative_path
        target = config_dir / relative_path
        if not source.exists():
            raise FileNotFoundError(f"Missing tracked user-config default: {source}")
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        created.append(target)
    return created
