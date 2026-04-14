# Briefing

`briefing` creates clean, contextual meeting briefings in Obsidian. It watches Apple Calendar for upcoming configured meetings, gathers context from a small set of source adapters, asks an LLM to write a concise pre-meeting briefing, and saves the final Markdown note into an Obsidian vault or another Markdown notes workspace.

The design goal is not “clever automation”. The goal is boring reliability: local-first, explicit configuration, deterministic note paths, managed refreshes, and clear validation for anything that can break.

## Final Vision

The finished system is intended to behave like this:

1. A `launchd` job runs `briefing run` every 15 minutes on the host Mac.
2. `briefing` queries Apple Calendar through `icalPal` for meetings starting soon.
3. Only explicitly configured meeting series are eligible.
4. The matched series configuration defines which context sources to gather.
5. Source adapters run in parallel and return labeled source blocks.
6. The LLM produces only the `Pre-Meeting Summary` content.
7. `briefing` writes or refreshes a managed Markdown note in the configured notes directory.
8. That note is then available wherever the notes workspace is accessed or synced.

The long-term user experience is “set and forget”:

- stable enough to run unattended
- explicit enough to debug quickly
- simple enough to maintain without a large automation stack
- local enough that calendar access and orchestration stay on the Mac
- portable enough that the output remains useful beyond one sync or device setup

## Current v1 Implementation

The repository currently implements the core v1 system:

- Python `3.13+` application managed with `uv`
- first-run bootstrap via `./scripts/setup.sh`
- CLI commands: `briefing run`, `briefing validate`, `briefing init-series`
- Apple Calendar ingestion via `icalPal`
- explicit meeting-series matching from `user_config/series/*.yaml`
- occurrence state keyed by `event_uid + start_timestamp`
- deterministic note filenames on first creation
- managed refresh of only the pre-meeting summary block
- automatic lockout once `Meeting Notes` or `Actions` have been edited
- source adapters for previous note, Slack, Notion, and local files
- Claude CLI provider abstraction with `sonnet` as the safe default model alias
- machine-readable run diagnostics under `state/runs/`
- `launchd` plist render/install helpers
- pytest coverage for the highest-risk workflow pieces

## Architecture

The intended runtime flow is:

```text
launchd
  -> briefing run
    -> icalPal
    -> match configured series
    -> collect sources in parallel
    -> build tracked prompt
    -> claude --print
    -> write or refresh note in configured notes workspace
    -> record state and diagnostics
```

### Core design choices

- Configured-only coverage: no note is generated for unconfigured meetings.
- Stable series matching: a series is matched by explicit rules, not only by the event title.
- Stable occurrence identity: state is stored by calendar UID plus start timestamp, so title changes do not orphan notes.
- Managed refresh only: automation updates only the generated summary block.
- User edits win: once notes or actions are touched, automation stops rewriting that occurrence.
- Required-vs-optional sources: required source failures block note generation; optional source failures are logged and omitted.

## Repository Layout

```text
src/briefing/             application code
tests/                    unit and workflow tests
user_config/defaults/     tracked defaults copied into local config on setup
user_config/examples/     tracked example config files
user_config/settings.toml local global settings (bootstrapped, ignored by git)
user_config/series/       local series YAML files (ignored by git)
user_config/prompts/      tracked prompt templates
user_config/templates/    tracked Markdown note templates
scripts/setup.sh          first-run local bootstrap
scripts/launchd/          LaunchAgent template and helper scripts
state/                    runtime state and diagnostics
logs/                     runtime logs
archive/                  untracked reference material and scratch assets
```

## Configuration

### Global settings

[`user_config/settings.toml`](user_config/settings.toml) is the local source of truth for:

- vault and note paths
- calendar lead window
- source execution limits
- output markers and placeholders
- LLM provider settings
- Slack, Notion, and file source defaults
- logging behavior

The default settings target a common Obsidian-on-macOS layout, but the output path can be changed to any local or synced Markdown folder.

The tracked bootstrap copy lives at [`user_config/defaults/settings.toml`](user_config/defaults/settings.toml) and is copied into place by `./scripts/setup.sh` when `user_config/settings.toml` is missing.

### Meeting series

Each YAML file in [`user_config/series`](user_config/series) defines one meeting series with:

- `series_id`
- `display_name`
- `note_slug`
- explicit `match` rules
- configured source adapters

Supported match groups:

- `title_any`
- `attendee_emails_any`
- `organizer_emails_any`
- `calendar_names_any`

All populated match groups must match for the series to be selected.

## Sources

Implemented in v1:

- `previous_note`: latest earlier note in the same series
- `slack`: configured channels and direct messages via Slack user token
- `notion`: page/block extraction through the Notion API
- `file`: local or synced files addressed by path

Planned next source additions:

- Google Docs / Google Drive documents
- additional local structured sources where plain file reads are not enough
- other work knowledge stores if they can meet the same stability bar

## Secrets

The default env-file path is `~/.env.briefing`.

Supported variables today:

- `SLACK_USER_TOKEN`
- `NOTION_TOKEN`

## Quickstart

New users should start with the full setup guide: [`docs/setup-and-configuration-walkthrough.md`](docs/setup-and-configuration-walkthrough.md). It explains the install flow, what `init-series` does, how series matching works, and the most common first-run problems.

1. Run setup:

   ```bash
   ./scripts/setup.sh
   ```

   This installs dependencies, creates the working directories, and bootstraps your local config in `user_config/`.
   The bootstrapped default provider is `claude_cli`. If you change the `[llm]` settings, rerun `./scripts/setup.sh` to validate the configured provider prerequisites.

2. Edit [`user_config/settings.toml`](user_config/settings.toml).
3. Review the example series under [`user_config/examples/series`](user_config/examples/series), then create local meeting series files under [`user_config/series`](user_config/series), or bootstrap one with `uv run briefing init-series`.
4. Create `~/.env.briefing` with the required secrets.
5. Run validation:

   ```bash
   uv run briefing validate
   ```

6. Run manually:

   ```bash
   uv run briefing run
   ```

7. Install automation only after manual validation succeeds. See [`scripts/launchd/README.md`](scripts/launchd/README.md).

## Output Portability

The reference workflow is Obsidian, but `briefing` writes plain Markdown files and keeps the orchestration local. That means the notes can also fit other Markdown-based workflows as long as the configured output folder and note template match the target environment.

## Validation Expectations

`briefing validate` is expected to surface environmental blockers before automation is installed. In practice that usually means:

- `icalPal` missing or blocked by macOS Full Disk Access
- `claude` missing or not authenticated for non-interactive use
- missing Slack or Notion tokens
- broken local file paths in series configs
- missing prompt or note templates

## Notes for macOS Operation

- `icalPal` requires access to the local Calendar database.
- On current macOS releases that often means granting Full Disk Access to the terminal or app running `briefing`.
- `claude` must already be authenticated before `launchd` automation is installed.
- `launchd` uses the local Mac timezone.
- The Mac must be awake for scheduled runs to happen on time.

## Planned Additions Beyond v1

The codebase is intentionally structured so these can be added without redesigning the core workflow:

- BetterTouchTool manual trigger and “note ready” HUD notification
- Google Docs source adapter
- richer series-bootstrap and config-validation UX
- additional LLM providers behind the same provider interface
- more source-specific summarisation/truncation policies where needed
- optional diagnostics and observability improvements for unattended operation

These are part of the target system, but they are not being claimed as implemented unless they appear in the v1 section above.
