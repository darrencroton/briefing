# Briefing

You have a recurring meeting in ten minutes. Over the past week you've traded Slack messages with the person, there are open items from last time, and a couple of Notion pages have been updated. You could spend the next ten minutes skimming all of that — or you could open your meeting note and find a short, focused summary already waiting for you.

`briefing` does that. It reads your Apple Calendar, and for each meeting series you configure, it pulls recent context from the sources you actually use — Slack channels and DMs, Notion pages, local files, Apple Mail, and the previous meeting note — sends it to an LLM, and writes a concise pre-meeting briefing into a Markdown note. The note lands in Obsidian (or any Markdown workspace you point it at), ready to glance at before you walk in.

You choose which meetings get briefings and which sources feed each one. A short YAML file per meeting series is all it takes. Everything runs locally on your Mac, on a schedule or on demand.

### What a briefing looks like

Each meeting note gets a `## Briefing` section with a handful of bullets — typically 3 to 6 — that capture what actually matters for *this* meeting with *this* person: open actions, recent discussion threads you were part of, decisions pending, schedule changes. Each bullet ends with a compact source/date tag so you can see where the point came from. No filler, no channel-wide noise, no generic summaries.

The rest of the note is yours. `briefing` only manages the briefing block; everything from `## Meeting Notes` onward is preserved and carried forward as previous-note context for the next briefing. You can start drafting notes before the meeting and keep editing them while `briefing` continues to refresh the `## Briefing` block up until the meeting start time.

### How it works

When `briefing` runs (manually or via `launchd`), it:

1. reads upcoming events from Apple Calendar
2. matches them against your configured meeting series
3. collects context from each series' configured sources
4. sends the context to an LLM CLI (`claude`, `codex`, `copilot`, or `gemini`)
5. writes or refreshes the briefing block in the meeting note until the meeting starts

If a note already exists at the expected path, `briefing` will adopt it by injecting the managed `## Briefing`, `## Meeting Notes`, and frontmatter metadata it needs when that can be done safely. It does not rewrite user content outside the managed briefing block.

Only meetings you have explicitly configured are processed. If a required source fails, that meeting's briefing is skipped rather than generated with incomplete context.

## Current Capabilities

- Python `3.13+` application managed with `uv`
- CLI commands: `briefing run`, `briefing validate`, `briefing init-series`
- Apple Calendar ingestion via EventKit
- Explicit series configuration under `user_config/series/*.yaml`
- Sources: `previous_note`, `slack`, `notion`, `file`, `email`
- Supported LLM CLIs: `claude`, `codex`, `copilot`, `gemini`
- Local state and diagnostics under `state/`
- `launchd` helper scripts for unattended macOS runs

## Quickstart

### Requirements

- macOS (EventKit requires Apple Calendar access)
- Python `3.13+`
- `uv` on `PATH`
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
- `[calendar]`: lead window and calendar filter settings
- `[execution]`: source concurrency and source timeout
- `[output]`: note placeholder behavior
- `[llm]`: provider, optional command override, model, and optional effort
- `[slack]`, `[notion]`, `[files]`, `[email]`: source defaults
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
- EventKit calendar access
- selected LLM provider readiness
- configured Slack and Notion auth
- configured file source paths
- Apple Mail automation access for configured email sources

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
- `email`: Apple Mail messages filtered by account, mailbox, address, or subject

Source-specific guides:

- [`docs/source-guides/previous-note-source.md`](docs/source-guides/previous-note-source.md)
- [`docs/source-guides/slack-source-setup.md`](docs/source-guides/slack-source-setup.md)
- [`docs/source-guides/notion-source-setup.md`](docs/source-guides/notion-source-setup.md)
- [`docs/source-guides/file-source-setup.md`](docs/source-guides/file-source-setup.md)
- [`docs/source-guides/email-source-setup.md`](docs/source-guides/email-source-setup.md)

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
state/                    runtime state and diagnostics (older entries are pruned automatically)
logs/                     runtime logs
archive/                  untracked retained local material
```

## Documentation

- [`docs/README.md`](docs/README.md): documentation map
- [`docs/setup-and-configuration-walkthrough.md`](docs/setup-and-configuration-walkthrough.md): onboarding and config walkthrough
- [`docs/source-guides/README.md`](docs/source-guides/README.md): source setup guides
- [`scripts/launchd/README.md`](scripts/launchd/README.md): automation setup

## Operational Notes

- On first run, macOS will prompt for Calendar access. Grant it when prompted, or enable it in System Settings > Privacy & Security > Calendars.
- The selected LLM CLI must already be authenticated before installing `launchd`.
- `launchd` runs in the local Mac timezone.
- The Mac must be awake for scheduled runs to happen on time.
