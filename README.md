# Briefing

`briefing` is a local-first macOS tool that prepares Markdown meeting briefings from Apple Calendar and a small set of explicitly configured context sources. It is designed for dependable unattended use: configured meetings only, deterministic note paths, managed refreshes, clear validation, and no silent fallback behavior.

The default target is Obsidian, but the output is plain Markdown and the notes directory can point at any local or synced Markdown workspace.

## What It Does

On each run, `briefing`:

1. reads upcoming events from Apple Calendar through `icalPal`
2. matches events against explicit YAML meeting-series rules in `user_config/series/`
3. collects context from the configured sources for that series
4. sends a prompt to the configured LLM CLI
5. writes or refreshes the managed `Briefing` block in the meeting note
6. records occurrence state and run diagnostics locally

Core behavior:

- Only explicitly configured meeting series are processed.
- Series matching uses explicit rules, not title-only heuristics.
- Occurrence identity stays stable across event title changes.
- Only the managed pre-meeting summary block is refreshed.
- User-entered `Meeting Notes` or `Actions` are never overwritten.
- Required source failures block note generation for that meeting.

## Current Capabilities

- Python `3.13+` application managed with `uv`
- CLI commands: `briefing run`, `briefing validate`, `briefing init-series`
- Apple Calendar ingestion via `icalPal`
- Explicit series configuration under `user_config/series/*.yaml`
- Sources: `previous_note`, `slack`, `notion`, `file`
- Supported LLM CLIs: `claude`, `codex`, `copilot`, `gemini`
- Local state and diagnostics under `state/`
- `launchd` helper scripts for unattended macOS runs

## Quickstart

### Requirements

- Python `3.13+`
- `uv` on `PATH`
- `icalPal` available on `PATH` or configured by absolute path
- One supported LLM CLI authenticated for non-interactive use

Supported LLM CLIs:

- `claude`
- `codex`
- `copilot`
- `gemini`

### 1. Run setup

```bash
./scripts/setup.sh
```

This installs dependencies, creates the local runtime directories, bootstraps `user_config/settings.toml` if needed, and validates the configured LLM provider when possible.

The bootstrapped default provider is `copilot` with `model = "claude-sonnet-4.6"` and `effort = "high"`. If you want a different provider, edit `user_config/settings.toml` and rerun `./scripts/setup.sh`.

### 2. Edit `user_config/settings.toml`

The main settings file controls:

- `[paths]`: notes location, runtime directories, templates, and env file
- `[calendar]`: lead window and `icalPal` settings
- `[execution]`: source concurrency and source timeout
- `[output]`: note placeholder behavior
- `[llm]`: provider, optional command override, model, and optional effort
- `[slack]`, `[notion]`, `[files]`: source defaults
- `[logging]`: log paths and debug toggles

Common LLM setups:

- `provider = "claude"`: run `claude auth login`
- `provider = "codex"`: run `codex login`, or `printenv OPENAI_API_KEY | codex login --with-api-key`
- `provider = "copilot"`: run `copilot login`, or set `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN`
- `provider = "gemini"`: set `GEMINI_API_KEY`, or configure Vertex AI credentials with `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION`

For scheduled automation, the selected provider must already work non-interactively. Gemini support is intended for API-key or Vertex-backed automation credentials, not interactive Google OAuth.

### 3. Add secrets only for the sources you use

The default env file is `~/.env.briefing`.

Supported source secrets:

- `SLACK_USER_TOKEN`
- `NOTION_TOKEN`

### 4. Validate the environment

```bash
uv run briefing validate
```

This checks:

- local paths and templates
- series configuration presence
- `icalPal` access
- selected LLM provider readiness
- configured Slack and Notion auth
- configured file source paths

### 5. Create your first series config

Inspect the tracked example:

- [`user_config/examples/series/example-team-weekly.yaml`](user_config/examples/series/example-team-weekly.yaml)

Then bootstrap a real series:

```bash
uv run briefing init-series
```

If multiple candidate events are found, rerun with `--index` or `--event-uid`.

### 6. Run once manually

```bash
uv run briefing run
```

Only after validation and a successful manual run should you install automation with the guides under [`scripts/launchd/README.md`](scripts/launchd/README.md).

## LLM Configuration

The `[llm]` section is CLI-only. `briefing` does not support API-mode providers.

Canonical provider values:

- `claude`
- `codex`
- `copilot`
- `gemini`

Notes:

- `command` is an optional executable override. If blank, `briefing` uses the provider default command name.
- `effort` supports `low`, `medium`, `high`, or blank.
- Existing local configs that still use `claude_cli` are normalized to `claude`.

Example:

```toml
[llm]
provider = "copilot"
command = ""
model = "claude-sonnet-4.6"
effort = "high"
timeout_seconds = 600
retry_attempts = 3
temperature = 0.2
max_output_tokens = 4096
prompt_template = "pre_meeting_summary.md"
note_template = "meeting_note.md"
```

## Source Model

Available source adapters:

- `previous_note`: the latest earlier note in the same meeting series
- `slack`: selected channels or DM conversations
- `notion`: selected standing pages
- `file`: local or synced text files

Source-specific guides:

- [`docs/source-guides/previous-note-source.md`](docs/source-guides/previous-note-source.md)
- [`docs/source-guides/slack-source-setup.md`](docs/source-guides/slack-source-setup.md)
- [`docs/source-guides/notion-source-setup.md`](docs/source-guides/notion-source-setup.md)
- [`docs/source-guides/file-source-setup.md`](docs/source-guides/file-source-setup.md)

## Repository Layout

```text
src/briefing/             application code
tests/                    unit and workflow tests
user_config/defaults/     tracked bootstrap defaults
user_config/examples/     tracked example series config
user_config/prompts/      tracked prompt templates
user_config/templates/    tracked note templates
user_config/settings.toml local mutable config (git-ignored)
user_config/series/       local series config (git-ignored)
scripts/setup.sh          first-run bootstrap
scripts/launchd/          LaunchAgent helpers
state/                    runtime state and diagnostics
logs/                     runtime logs
archive/                  untracked retained local material
```

## Documentation

- [`docs/README.md`](docs/README.md): documentation map
- [`docs/setup-and-configuration-walkthrough.md`](docs/setup-and-configuration-walkthrough.md): onboarding and config walkthrough
- [`docs/source-guides/README.md`](docs/source-guides/README.md): source setup guides
- [`scripts/launchd/README.md`](scripts/launchd/README.md): automation setup

## Operational Notes

- `icalPal` often needs Full Disk Access on macOS.
- The selected LLM CLI must already be authenticated before installing `launchd`.
- `launchd` runs in the local Mac timezone.
- The Mac must be awake for scheduled runs to happen on time.
