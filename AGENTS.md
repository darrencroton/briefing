# AGENTS.md

Project-specific instructions for coding agents working in this repository.

## Purpose

`briefing` is a local-first meeting briefing system for macOS. It must remain simple, robust, explicit, and predictable. Favor operational reliability over cleverness.

## Technical Baseline

- Use Python `3.13+`.
- Use `uv` for environment and command execution.
- Keep the main application in `src/briefing/`.
- Keep shell usage small and purposeful: `launchd` helpers, external CLI calls, and setup scripts are fine; core orchestration belongs in Python.

## Product Constraints

- Process only explicitly configured meeting series.
- Match series with explicit rules, not title-only heuristics.
- Keep occurrence state stable across event title changes.
- Refresh only the managed pre-meeting summary block.
- Never overwrite user-entered `Meeting Notes` or `Actions`.
- Treat required source failures as blocking.
- Prefer local-first operation and minimal moving parts.

## Repo Conventions

- `user_config/settings.toml` is the primary global config.
- `user_config/series/*.yaml` is the source of truth for meeting-series configuration.
- `user_config/prompts/` and `user_config/templates/` contain tracked prompt and note templates; do not hardcode large prompt bodies in Python when a tracked file is more appropriate.
- `archive/` is for retained local reference material and must stay untracked.
- `.claude/` is local agent state/config and must stay untracked.

## Engineering Rules

- Keep the CLI surface small and coherent.
- Prefer deterministic note paths and state transitions.
- Add tests for any workflow-sensitive behavior change.
- Do not weaken validation to hide environment problems.
- Surface setup/runtime failures clearly in `validate` or run diagnostics.
- Preserve KISS and DRY. If an abstraction does not clearly improve maintainability or reliability, do not add it.

## Before Committing

- Run the relevant tests.
- Review the diff for accidental local-only files.
- Stage files explicitly.
- Write commit messages that explain why each changed file matters.
