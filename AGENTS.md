# AGENTS.md

Project-specific instructions for coding agents working in this repository.

## Purpose

`briefing` is a local-first meeting briefing system for macOS. It must remain simple, robust, explicit, and predictable. Favor operational reliability over cleverness.

The primary target is Obsidian, but public-facing docs and defaults should avoid assuming one personal device, machine name, username, or sync workflow unless that assumption is truly required by the code.

## Technical Baseline

- Use Python `3.13+`.
- Use `uv` for environment and command execution.
- Keep the main application in `src/briefing/`.
- Keep shell usage small and purposeful: `launchd` helpers, external CLI calls, and setup scripts are fine; core orchestration belongs in Python.
- Supported LLM CLIs are `claude`, `codex`, `copilot`, and `gemini`.
- CLI providers must be validated for non-interactive automation use; Gemini support is only for API-key or Vertex-style automation credentials, not interactive Google OAuth.

## Product Constraints

- Process only explicitly configured meeting series.
- Match series with explicit rules, not title-only heuristics.
- Keep occurrence state stable across event title changes.
- Refresh only the managed pre-meeting summary block.
- Never overwrite user-entered `Meeting Notes` or `Actions`.
- Treat required source failures as blocking.
- Prefer local-first operation and minimal moving parts.
- Keep output as portable Markdown wherever practical, even when the default workflow is Obsidian-first.
- For the email source, prefer the most recent matched messages and preserve meaningful new content rather than quoted reply-chain noise.

## Repo Conventions

- Run `./scripts/setup.sh` before first use to bootstrap local config from tracked defaults.
- `user_config/settings.toml` is the local mutable global config and should stay untracked.
- `user_config/series/*.yaml` is the local source of truth for meeting-series configuration and should stay untracked.
- `user_config/defaults/` contains tracked bootstrap defaults.
- `user_config/examples/` contains tracked example config files that are not loaded as live user config.
- `user_config/prompts/` and `user_config/templates/` contain tracked prompt and note templates; do not hardcode large prompt bodies in Python when a tracked file is more appropriate.
- `archive/` is for retained local reference material and must stay untracked.
- `.claude/` is local agent state/config and must stay untracked.
- Do not commit personal absolute paths or machine-specific naming when a generic default will work.

## Documentation Expectations

- Keep `README.md` high-level and treat it as the entry point.
- Keep `docs/setup-and-configuration-walkthrough.md` as the main onboarding guide.
- Keep source-specific setup instructions under `docs/source-guides/`.
- Prefer cross-references over repeating the same step-by-step instructions in multiple docs.

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
