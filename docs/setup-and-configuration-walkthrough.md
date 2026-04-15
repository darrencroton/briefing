# Setup And Configuration Walkthrough

This guide is for a new user setting up `briefing` for the first time on macOS.

It explains:

- what `briefing` actually does
- what each CLI command is for
- how to get a minimal working setup
- how to configure meeting series and source adapters
- what the most common first-run problems look like

Use this guide as the onboarding path.

For source-specific step-by-step setup, use the dedicated guides under [`docs/source-guides/`](source-guides/README.md):

- [`slack-source-setup.md`](source-guides/slack-source-setup.md)
- [`notion-source-setup.md`](source-guides/notion-source-setup.md)
- [`file-source-setup.md`](source-guides/file-source-setup.md)
- [`previous-note-source.md`](source-guides/previous-note-source.md)

## What `briefing` does

`briefing` watches Apple Calendar for meetings starting soon, matches only the meeting series you have explicitly configured, gathers context from a small set of sources, asks an LLM to draft a pre-meeting summary, and writes the result into a Markdown note.

Today, the core workflow is:

1. Read upcoming events from Apple Calendar through `icalPal`.
2. Match each event against YAML files in `user_config/series/`.
3. Collect context from:
   - the previous note in the same series
   - optional Slack sources
   - optional Notion pages
   - optional local files
4. Ask the configured LLM provider to generate bullet points for the `Briefing`.
5. Create or refresh the meeting note in your configured notes folder.

Important behavior:

- `briefing` does nothing for meetings that are not explicitly configured.
- It updates only the managed summary block.
- It does not overwrite user-entered content in `Meeting Notes`.
- If a required source fails, note generation stops for that meeting.

Current source adapters:

- `previous_note`
- `slack`
- `notion`
- `file`

Practical recommendation:

- get calendar plus `previous_note` working first
- add only one extra source at a time after the base flow is working

## What the commands do

The current CLI surface is intentionally small:

- `uv run briefing validate`
  Checks local paths, `icalPal`, the LLM provider, required tokens for configured sources, and configured file paths.
- `uv run briefing init-series`
  Bootstraps a new series YAML file from one upcoming calendar event.
- `uv run briefing run`
  Runs the real briefing workflow for meetings starting in the configured lead window.

## Minimal first working setup

This is the fastest path to a working local install.

### 1. Run setup

```bash
./scripts/setup.sh
```

This does four things:

- installs dependencies
- bootstraps `user_config/settings.toml` from tracked defaults if it is missing
- creates the local runtime directories used by the app
- validates the configured LLM provider when possible

Tracked defaults and examples live under:

- `user_config/defaults/`
- `user_config/examples/`

Your local private working config lives under:

- `user_config/settings.toml`
- `user_config/series/`

The local files are intentionally git-ignored.

The bootstrapped default provider is `claude_cli` using the `claude` command.
If you change the `[llm]` settings, rerun `./scripts/setup.sh` to validate the configured provider prerequisites.

### 2. Edit `user_config/settings.toml`

Start with these fields:

- `paths.vault_root`
  The root folder of your Markdown notes workspace. The default assumes an Obsidian vault in iCloud.
- `paths.meeting_notes_dir`
  A path relative to `vault_root` where meeting notes should be written.
- `calendar.icalpal_path`
  Usually `icalPal` if it is on your `PATH`.
- `llm.command`
  Usually `claude`.

The default `series_dir` is already correct for the repo:

- `paths.series_dir = "user_config/series"`

### 3. Make sure macOS access is available

`briefing` relies on `icalPal` being able to read the local Apple Calendar database.

Common requirement on macOS:

- give Full Disk Access to the terminal app or launcher you are using to run `uv`

If this is missing, `uv run briefing validate` will report an `icalPal` error.

### 4. Create `~/.env.briefing` if needed

You only need tokens for the sources you actually configure.

Supported variables today:

- `SLACK_USER_TOKEN`
- `NOTION_TOKEN`

If you are starting with calendar plus previous-note only, you can leave Slack and Notion out entirely.

### 5. Run validation

```bash
uv run briefing validate
```

For a minimal setup, the important checks are:

- vault root exists
- prompt and note templates exist
- at least one series config exists or you intend to create one next
- `icalPal` works
- Claude CLI is installed and authenticated

### 6. Create your first series config

You can inspect the tracked example first:

- `user_config/examples/series/example-team-weekly.yaml`

```bash
uv run briefing init-series
```

This command often surprises new users. It does not automatically create a file if several upcoming events are found.

Its behavior is:

- if there are no upcoming events in the init window, it prints that and exits
- if there is exactly one event, it creates a series file from it
- if there are multiple events, it lists them and exits

When multiple events are listed, rerun with one of:

```bash
uv run briefing init-series --index 3
```

or:

```bash
uv run briefing init-series --event-uid "EVENT-UID-HERE"
```

If successful, it writes a YAML file into `user_config/series/` named from a slug of the meeting title, for example `cas-strategy-meeting.yaml`.

### 7. Review and refine the generated series YAML

`init-series` gives you a starting point, not a finished config.

Check:

- `series_id`
- `display_name`
- `note_slug`
- `match` rules
- `sources`

In practice, the most important thing is making the match rules stable enough to survive minor event-title variation.

### 8. Run manually

```bash
uv run briefing run
```

This only processes meetings that are within the configured lead window:

- `calendar.window_min_minutes`
- `calendar.window_max_minutes`

By default, that means meetings starting between 15 and 45 minutes from now.

If nothing happens, that usually means:

- no event is starting in that window
- the event did not match any configured series
- the note was already locked
- a required source failed

## How `init-series` works

`init-series` reads events from now through:

- `calendar.lookback_days_for_init`

The name is slightly misleading. In the current code this is used as the number of days ahead to search when bootstrapping a series.

When it writes a file, the generated config contains:

- `title_any` with the selected event title
- `attendee_emails_any` from detected attendees
- `organizer_emails_any` from the organizer, if present
- `calendar_names_any` from the calendar name, if present
- empty `slack`, `notion`, and `files` source blocks

Common workflow:

1. run `uv run briefing init-series`
2. choose an event with `--index`
3. open the new YAML file
4. tighten or expand the match rules
5. add the source adapters you need

## Global settings reference

The main config file is [`user_config/settings.toml`](../user_config/settings.toml).

If it does not exist yet, run `./scripts/setup.sh` to create it from [`user_config/defaults/settings.toml`](../user_config/defaults/settings.toml).

### `[paths]`

- `vault_root`
  Root folder of your notes workspace.
- `meeting_notes_dir`
  Relative folder inside `vault_root` where notes are written.
- `log_dir`
  Local logs directory.
- `state_dir`
  Local runtime state and diagnostics directory.
- `prompt_dir`
  Tracked prompt template directory.
- `template_dir`
  Tracked note template directory.
- `series_dir`
  Directory containing meeting-series YAML files.
- `debug_dir`
  Optional debug output directory.
- `env_file`
  Environment file for tokens and secrets.

### `[calendar]`

- `include_all_day`
  Whether all-day events should be considered.
- `window_min_minutes`
  Earliest lead time for `briefing run`.
- `window_max_minutes`
  Latest lead time for `briefing run`.
- `include_calendar_names`
  Optional allow-list of calendar names.
- `exclude_calendar_names`
  Optional block-list of calendar names.
- `icalpal_path`
  Path or command name for `icalPal`.
- `lookback_days_for_init`
  How far ahead `init-series` searches for candidate events.

For list settings in `settings.toml`, use TOML arrays with quoted strings:

```toml
include_calendar_names = ["Work", "School Admin"]
exclude_calendar_names = ["Personal", "Birthdays"]
```

Practical syntax notes:

- use double-quoted strings
- names with spaces stay inside the quotes
- for calendar names, copy the names exactly as they appear in Calendar.app
- use `[]` for an empty list

Typical use cases:

- keep `include_calendar_names` empty to search all calendars
- use `exclude_calendar_names` to ignore personal or noisy calendars
- narrow `window_min_minutes` and `window_max_minutes` if you want runs closer to start time

### `[execution]`

- `max_parallel_sources`
  Maximum number of sources collected in parallel.
- `source_timeout_seconds`
  Timeout applied when collecting each source job.

### `[output]`

- `meeting_notes_placeholder`

This drives the managed note behavior. In normal use, you usually leave it alone.

`briefing` only refreshes the `## Briefing` section. It treats edits to `Meeting Notes` as a lock signal and stops rewriting that occurrence.

### `[llm]`

- `provider`
  Currently only `claude_cli` is supported.
- `command`
  Claude CLI executable name or path.
- `model`
  Model name passed to Claude CLI.
- `effort`
  Optional Claude effort value.
- `timeout_seconds`
  Timeout for one LLM call.
- `retry_attempts`
  Present in settings, but not currently used by the provider implementation.
- `temperature`
  Present in settings, but not currently used by the provider implementation.
- `max_output_tokens`
  Present in settings, but not currently used by the provider implementation.
- `prompt_template`
  Prompt template filename under `user_config/prompts/`.
- `note_template`
  Note template filename under `user_config/templates/`.

Practical point:

- if `provider` is anything other than `claude_cli`, validation or runtime will fail because only that provider exists today

### `[slack]`

- `history_days`
  Default lookback window for Slack history.
- `request_timeout_seconds`
  API timeout.
- `max_messages`
  Maximum messages to inspect.
- `page_size`
  Slack API page size.
- `max_characters`
  Default text cap before truncation.

For the full user setup flow, see [`source-guides/slack-source-setup.md`](source-guides/slack-source-setup.md).

### `[notion]`

- `version`
  Notion API version header.
- `request_timeout_seconds`
  API timeout.
- `max_characters`
  Default text cap before truncation.

For the full user setup flow, see [`source-guides/notion-source-setup.md`](source-guides/notion-source-setup.md).

### `[files]`

- `max_characters`
  Default cap for local file source content.

For the full user setup flow, see [`source-guides/file-source-setup.md`](source-guides/file-source-setup.md).

### `[logging]`

- `level`
  Logging level.
- `history_file`
  Historical log filename.
- `last_run_file`
  Latest run log filename.
- `debug_prompts`
  Whether to write rendered prompts to `debug_dir`.
- `debug_llm_output`
  Whether to write raw LLM output to `debug_dir`.

## Series config reference

Each YAML file in `user_config/series/` defines one meeting series.

That directory is local and git-ignored. For a tracked example, see [`user_config/examples/series/example-team-weekly.yaml`](../user_config/examples/series/example-team-weekly.yaml).

Required top-level fields:

- `series_id`
- `display_name`
- `note_slug`
- `match`

YAML list syntax uses one item per line:

```yaml
match:
  title_any:
    - CAS Strategy Meeting
    - CAS Strategy
```

### Match rules

Supported groups:

- `title_any`
- `attendee_emails_any`
- `organizer_emails_any`
- `calendar_names_any`

Matching rule:

- every populated group must match
- inside one group, any listed value can match

Practical syntax notes:

- `title_any` is forgiving about case and punctuation
- `attendee_emails_any` and `organizer_emails_any` should be written as plain email strings
- `calendar_names_any` should use the calendar name; matching is case-insensitive in the app, but write the real name for clarity

Practical examples:

- use `title_any` for stable meeting names or a few known variants
- use `attendee_emails_any` when the recurring participants are a stronger signal than the title
- use `calendar_names_any` to distinguish work vs personal calendars
- combine groups when you want fewer false matches

Good first principle:

- prefer the fewest rules that still make the series match reliably

### Source blocks

#### `slack`

Fields:

- `channel_refs`
- `dm_user_ids`
- `required`
- `history_days`
- `max_characters`

Example:

```yaml
slack:
  channel_refs:
    - eng-leads
  dm_user_ids:
    - U0123ABC456
```

Use this when pre-meeting context often lives in a channel or DM thread.

For the step-by-step setup flow, including tokens, scopes, and how to choose identifiers, see [`source-guides/slack-source-setup.md`](source-guides/slack-source-setup.md).

#### `notion`

Each entry supports:

- `label`
- `page_id`
- `required`
- `max_characters`

Example:

```yaml
notion:
  - label: Weekly agenda
    page_id: abc123def456
    required: false
```

Use this when a recurring meeting relies on one or more standing Notion pages.

For the full setup flow, including integration creation, page sharing, and page IDs, see [`source-guides/notion-source-setup.md`](source-guides/notion-source-setup.md).

#### `files`

Each entry supports:

- `label`
- `path`
- `required`
- `max_characters`

Example:

```yaml
files:
  - label: Project tracker
    path: ~/Documents/project-tracker.md
    required: false
```

Use this for local Markdown, synced docs exported to files, or other stable local references.

For the step-by-step setup flow, including path selection and validation expectations, see [`source-guides/file-source-setup.md`](source-guides/file-source-setup.md).

### Implicit previous-note source

You do not configure this manually.

`briefing` always tries to include the latest earlier note from the same series as `previous_note`. This is often the most useful source once the workflow has been running for a while.

For guidance on making this source effective, see [`source-guides/previous-note-source.md`](source-guides/previous-note-source.md).

## Choosing sources

Choose sources based on where the real pre-meeting context already lives.

- start with `previous_note`
  This is often enough once the workflow has run more than once.
- add `slack`
  When important context lives in one channel or one DM thread.
- add `notion`
  When one or two standing Notion pages drive the meeting.
- add `files`
  When the relevant context already exists as stable Markdown or text files.

Good default:

- add one new source at a time
- leave new sources as optional until they are proven stable

## Common setup patterns

### Minimal local-only setup

Good for first-time validation.

- configure calendar access
- configure Claude CLI
- create one series
- leave Slack and Notion unused
- run manually before touching `launchd`

### One-on-one or manager check-in

Usually:

- match on attendee email and maybe organizer email
- add one or two local files
- optionally add a DM in Slack

### Team weekly meeting

Usually:

- match on title plus calendar name
- add a team Slack channel
- add a project tracker file
- optionally add a standing Notion page

### Project or steering meeting

Usually:

- avoid title-only matching if the title is too generic
- combine title with attendee or organizer rules
- use required file or Notion sources only if the meeting should fail loudly without them

## What “working” looks like

A healthy first setup usually looks like this:

1. `uv run briefing validate` reports `icalPal` and `llm_provider` as OK.
2. You create one series file under `user_config/series/`.
3. `uv run briefing run` sees an event in the configured time window.
4. That event matches exactly one series.
5. A note is created under your configured `meeting_notes_dir`.

The output filename format is:

```text
YYYY-MM-DD-HHMM-note-slug.md
```

## Common first-run problems

### `init-series` lists many events and writes nothing

Expected behavior when more than one upcoming event is found. Rerun with `--index` or `--event-uid`.

### `validate` says `icalPal` failed

Usually one of:

- `icalPal` is not installed or not on your `PATH`
- the app running `uv` lacks Full Disk Access
- the selected calendars are inaccessible

### `validate` says the LLM provider failed

Usually one of:

- `claude` is not installed
- `claude auth status --text` fails because authentication is missing
- `settings.toml` names a provider other than `claude_cli`

### `run` does nothing

Usually one of:

- no meeting starts between `window_min_minutes` and `window_max_minutes`
- no series matched the event
- more than one series matched the event
- the note was already locked because `Meeting Notes` were edited
- the meeting had already started

### A series exists but never matches

Review the YAML match groups. The most common issue is over-constraining the series with too many fields that are not stable across occurrences.

### A note was created once but no longer refreshes

This is usually intentional. If `Meeting Notes` differs from its placeholder, `briefing` treats the occurrence as user-owned and stops rewriting it.

## Before enabling automation

Do this manually first:

```bash
uv run briefing validate
uv run briefing run
```

Only after that should you set up `launchd`. See [`scripts/launchd/README.md`](../scripts/launchd/README.md).

## Suggested first-time workflow

If you want the shortest path to confidence, use this order:

1. Set `vault_root` and `meeting_notes_dir`.
2. Confirm `icalPal` and Claude CLI work with `uv run briefing validate`.
3. Create one series with `uv run briefing init-series --index N`.
4. Simplify that series so it matches reliably.
5. Run `uv run briefing run` close to a real upcoming meeting.
6. Inspect the written note.
7. Add Slack, Notion, or file sources only after the local-only flow works, using the guides under [`source-guides/`](source-guides/README.md).
8. Install `launchd` automation last.
