# Setup And Configuration Walkthrough

This guide is the main onboarding path for `briefing`.

It covers:

- what the tool does
- how to get a minimal working setup
- how to choose and validate an LLM CLI
- how `init-series` works
- what to check when validation or runs fail

Use the source-specific guides under [`source-guides/`](source-guides/README.md) after the base local flow is working.

## What `briefing` does

`briefing` watches Apple Calendar for meetings starting soon, matches only the meeting series you have explicitly configured, gathers context from the configured sources, asks an LLM CLI to draft the pre-meeting summary, and writes the result into a Markdown note.

The runtime flow is:

1. query Apple Calendar through EventKit
2. match each upcoming event against `user_config/series/*.yaml`
3. collect sources for the matched series
4. render the prompt template
5. invoke the configured LLM CLI
6. write or refresh the managed `Briefing` block
7. save occurrence state and run diagnostics

Important behavior:

- unconfigured meetings are skipped
- matching uses explicit rules, not title-only heuristics
- only the managed summary block is refreshed
- edits in `Meeting Notes` lock that occurrence against further automated rewrites
- required source failures block note generation

## Minimal first working setup

### 1. Run setup

```bash
./scripts/setup.sh
```

Setup:

- installs dependencies
- bootstraps `user_config/settings.toml` from tracked defaults if needed
- creates local runtime directories
- validates the configured LLM provider when possible

The bootstrapped default provider is `copilot` with `model = "claude-sonnet-4.6"` and `effort = "high"`. If you choose another provider, rerun setup after updating `[llm]`.

### 2. Edit `user_config/settings.toml`

Start with these fields:

- `paths.vault_root`
- `paths.meeting_notes_dir`
- `llm.provider`
- `llm.command` if you need an executable override
- `llm.model`

The default `paths.series_dir` is already correct for the repo:

```toml
paths.series_dir = "user_config/series"
```

### 3. Grant Calendar access

`briefing` uses Apple's EventKit framework to read Calendar events. On first run, macOS will prompt for Calendar access. Grant it when prompted, or enable it in System Settings > Privacy & Security > Calendars.

Run `uv run briefing validate` once interactively to trigger the permission prompt before installing `launchd` automation.

### 4. Add secrets only for the sources you use

The default env file is `~/.env.briefing`.

Supported variables:

- `SLACK_USER_TOKEN`
- `NOTION_TOKEN`

If you are starting with calendar plus `previous_note`, you do not need either token yet.

### 5. Run validation

```bash
uv run briefing validate
```

For a minimal setup, validation should confirm:

- vault root exists
- prompt and note templates exist
- EventKit calendar access is granted
- the selected LLM provider is installed and automation-ready

### 6. Create your first series

Inspect the tracked example:

- [`../user_config/examples/series/example-team-weekly.yaml`](../user_config/examples/series/example-team-weekly.yaml)

Then run:

```bash
uv run briefing init-series
```

If multiple candidate events are found, rerun with:

```bash
uv run briefing init-series --index 3
```

or:

```bash
uv run briefing init-series --event-uid "EVENT-UID-HERE"
```

### 7. Run once manually

```bash
uv run briefing run
```

By default this processes meetings starting between 15 and 45 minutes from now.

## LLM provider setup

`briefing` is CLI-only. It supports these provider values in `[llm]`:

- `claude`
- `codex`
- `copilot`
- `gemini`

`command` is optional. If it is blank or omitted, `briefing` uses the default executable name for the provider.

`effort` may be blank, `low`, `medium`, or `high`.

Legacy `claude_cli` is still accepted and normalized to `claude`.

### Common provider setups

- `claude`
  Run `claude auth login`.
- `codex`
  Run `codex login`, or `printenv OPENAI_API_KEY | codex login --with-api-key`.
- `copilot`
  Run `copilot login`, or set `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN`.
- `gemini`
  Set `GEMINI_API_KEY`, or configure Vertex AI credentials with `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION`.

For scheduled automation, the chosen provider must already work without an interactive prompt. Gemini support is for API-key or Vertex-style automation credentials, not interactive Google OAuth.

### Example `[llm]` blocks

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

## `init-series` behavior

`init-series` reads upcoming events from now through `calendar.lookback_days_for_init`.

When it writes a file, the generated YAML includes:

- `title_any` from the selected event title
- `attendee_emails_any` from detected attendees
- `organizer_emails_any` when present
- `calendar_names_any` when present
- empty `slack`, `notion`, and `files` source blocks

`init-series` is a bootstrap tool, not a final configuration writer. Review the generated file and tighten the match rules before relying on it.

## Global settings reference

### `[paths]`

- `vault_root`: root folder of your notes workspace
- `meeting_notes_dir`: folder inside `vault_root` where notes are written
- `log_dir`: local logs directory
- `state_dir`: local runtime state and diagnostics directory
- `prompt_dir`: tracked prompt template directory
- `template_dir`: tracked note template directory
- `series_dir`: local series YAML directory
- `debug_dir`: local debug output directory
- `env_file`: env file loaded for source tokens

### `[calendar]`

- `include_all_day`: include all-day events or not
- `window_min_minutes`: earliest lead time to process
- `window_max_minutes`: latest lead time to process
- `include_calendar_names`: optional allow-list
- `exclude_calendar_names`: optional block-list
- `lookback_days_for_init`: forward search window used by `init-series`

### `[execution]`

- `max_parallel_sources`: maximum sources collected in parallel
- `source_timeout_seconds`: timeout per source job

### `[output]`

- `meeting_notes_placeholder`: placeholder inserted into `Meeting Notes`

### `[llm]`

- `provider`: `claude`, `codex`, `copilot`, or `gemini`
- `command`: optional executable override
- `model`: provider-specific model name
- `effort`: blank, `low`, `medium`, or `high`
- `timeout_seconds`: timeout for one LLM call
- `retry_attempts`: retained in config but not used by the current provider implementation
- `temperature`: retained in config but not used by the current provider implementation
- `max_output_tokens`: retained in config but not used by the current provider implementation
- `prompt_template`: prompt template filename under `user_config/prompts/`
- `note_template`: note template filename under `user_config/templates/`

Gemini ignores `llm.effort` and uses Gemini defaults.

### `[slack]`

- `history_days`
- `request_timeout_seconds`
- `max_messages`
- `page_size`
- `max_characters`

### `[notion]`

- `version`
- `request_timeout_seconds`
- `max_characters`

### `[files]`

- `max_characters`

### `[logging]`

- `level`
- `history_file`
- `last_run_file`
- `debug_prompts`
- `debug_llm_output`

## Validation expectations

`uv run briefing validate` is intended to catch environment blockers before automation is installed.

Typical failures:

- EventKit calendar access is not granted
- the selected LLM CLI is missing
- the selected LLM CLI is installed but not authenticated for unattended use
- required Slack or Notion tokens are missing for configured sources
- configured file sources do not exist

Validation confirms provider readiness, but source-specific runtime issues can still appear later, such as:

- Slack channel references that do not resolve
- Notion pages not shared with the integration
- low-signal or oversized source inputs

## Troubleshooting

### `validate` says EventKit access failed

Usually one of:

- Calendar access was denied or not yet granted
- the process is running in an environment without access to the macOS Calendar store

Open System Settings > Privacy & Security > Calendars and enable access for your terminal app, or run `uv run briefing validate` interactively to trigger the permission prompt.

### `validate` says the LLM provider failed

Usually one of:

- the configured CLI is not installed
- the CLI is not authenticated for unattended use
- `[llm].provider` is invalid
- Gemini is configured only through interactive Google OAuth instead of API-key or Vertex-style automation credentials

### `run` does nothing

Usually one of:

- no meeting starts between `window_min_minutes` and `window_max_minutes`
- no series matched the event
- more than one series matched the event
- the note was already locked because `Meeting Notes` were edited
- the meeting had already started

### A series exists but never matches

Review the YAML match groups. The most common issue is over-constraining the series with fields that are not stable across occurrences.

### A note was created once but no longer refreshes

This is usually intentional. If `Meeting Notes` differs from its placeholder, `briefing` treats the occurrence as user-owned and stops rewriting it.

## Recommended rollout order

1. Set `vault_root` and `meeting_notes_dir`.
2. Confirm calendar access and one LLM CLI work with `uv run briefing validate`.
3. Create one series with `uv run briefing init-series --index N`.
4. Simplify that series until it matches reliably.
5. Run `uv run briefing run` close to a real meeting.
6. Inspect the written note.
7. Add Slack, Notion, or file sources one at a time using the source guides.
8. Install `launchd` only after the manual path works cleanly.
