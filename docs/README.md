# Documentation Guide

Use these docs in this order:

1. [`setup-and-configuration-walkthrough.md`](setup-and-configuration-walkthrough.md)
   Start here for first install, provider setup, first validation, first series config, and the overall mental model.
2. [`source-guides/README.md`](source-guides/README.md)
   Use this once the base install works and you are ready to add Slack, Notion, local files, or rely on the automatic previous-note source.
3. [`../scripts/launchd/README.md`](../scripts/launchd/README.md)
   Use this only after manual validation and a successful manual `run` or watcher dry-run.

## What Lives Where

- `README.md`
  High-level project overview and the main entry point.
- `docs/setup-and-configuration-walkthrough.md`
  End-to-end onboarding and configuration walkthrough.
- `docs/source-guides/`
  Source-specific setup guides with step-by-step instructions.
- `scripts/launchd/README.md`
  Automation setup for both batch `briefing run` and long-running `briefing watch`.

## Fast Path For New Users

1. Run `./scripts/setup.sh`.
2. Edit `user_config/settings.toml`, including the `[llm]` provider selection.
3. Run `uv run briefing validate`.
4. Create one series with `uv run briefing init-series`.
5. Run `uv run briefing run`.
6. Add source-specific configuration using the guides under [`source-guides/`](source-guides/README.md).
7. For recording workflows, run `uv run briefing watch --once --dry-run` and inspect `uv run briefing session-plan --event-id <event-id>`.
8. Install `launchd` only after the manual flow is working.
