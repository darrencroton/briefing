# Setup And Configuration Walkthrough

This guide is the main onboarding path for `briefing`.

It covers:

- what the tool does
- how to get a minimal working setup
- how to choose and validate an LLM CLI
- how `init-series` works
- how Meeting Intelligence planning and `noted` recording handoff works
- what to check when validation or runs fail

Use the source-specific guides under [`source-guides/`](source-guides/README.md) after the base local flow is working.

## What `briefing` does

`briefing` watches Apple Calendar for meetings starting soon, matches configured meeting series or explicit one-off `noted config` markers, gathers context from configured sources, asks a configured LLM provider to draft the pre-meeting summary, and writes the result into a Markdown note.

The runtime flow is:

1. query Apple Calendar through EventKit
2. match each upcoming event against `user_config/series/*.yaml`
3. collect sources for the matched series
4. render the prompt template
5. invoke the configured LLM CLI
6. write or refresh the managed `Briefing` block
7. save occurrence state and run diagnostics

The Meeting Intelligence recording flow adds:

1. `briefing session-plan --event-id <id>` writes a contract-valid `manifest.json`
2. `briefing watch` polls upcoming events, refreshes pre-written next manifests, and invokes `noted start --manifest <path>` at pre-roll
3. `briefing session-ingest --session-dir <path>` reads `completion.json` and writes the managed `Meeting Summary` section
4. `briefing session-reprocess --session-dir <path>` reruns summary generation from an existing completed session

Important behavior:

- meetings without a matching series or explicit `noted config` marker are skipped
- matching uses explicit rules, not title-only heuristics
- only managed blocks are refreshed
- user-owned note content is preserved across rewrites
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

The bootstrapped default provider is `copilot` with `model = "claude-sonnet-4.6"` and `effort = "high"`. If you choose another provider, rerun setup after updating `[llm]`. For `openai-compatible`, ensure the inference server is running before running setup.

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

For recording handoff, review `[meeting_intelligence]`. The defaults write session manifests under `sessions/`, call `noted`, and launch 90 seconds before the scheduled start. `noted` is configured separately in `~/Library/Application Support/noted/settings.toml`.

For ad hoc recordings started from the `noted` menubar, `noted` needs to find a `briefing` command when it runs the completion handoff. The simplest local setup is:

```bash
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/.venv/bin/briefing" "$HOME/.local/bin/briefing"
which briefing
```

Alternatively, set `briefing_command` in `~/Library/Application Support/noted/settings.toml` to the absolute path of this repo's `.venv/bin/briefing`.

If `briefing watch` runs on more than one Mac, configure `location_type` routing before enabling unattended launch. Set the normal target location with `default_location_type`, then set this Mac's location with `local_location_type` or with the host-name mapping shown later in this guide.

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

By default this processes meetings starting between 10 and 45 minutes from now.

To dry-run the long-lived recorder planner without launching `noted`:

```bash
uv run briefing watch --once --dry-run
```

To inspect a completed `noted` session before writing the managed summary section:

```bash
uv run briefing session-ingest --session-dir /path/to/noted/session --dry-run
```

When ready, run the same command without `--dry-run`. In normal operation this handoff is automatic: after `outputs/completion.json` is written, `noted` invokes `briefing session-ingest --session-dir <session_dir>` and stores stdout/stderr under the session `logs/` directory.

To rerun summary generation from the same transcript:

```bash
uv run briefing session-reprocess --session-dir /path/to/noted/session --dry-run
uv run briefing session-reprocess --session-dir /path/to/noted/session
```

## LLM provider setup

`briefing` supports these provider values in `[llm]`:

CLI providers (invoke a locally installed binary):

- `claude`
- `codex`
- `copilot`
- `gemini`

API provider (calls a local or self-hosted OpenAI-compatible server directly):

- `openai-compatible`

`command` is optional for CLI providers. If it is blank or omitted, `briefing` uses the default executable name.

`effort` may be blank, `low`, `medium`, or `high` for CLI providers. It is not used for `openai-compatible`.

Legacy `claude_cli` is still accepted and normalised to `claude`.

### Common provider setups

- `claude`
  Run `claude auth login`.
- `codex`
  Run `codex login`, or `printenv OPENAI_API_KEY | codex login --with-api-key`.
- `copilot`
  Run `copilot login`, or set `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN`.
- `gemini`
  Set `GEMINI_API_KEY`, or configure Vertex AI credentials with `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION`.
- `openai-compatible`
  Start your local inference server (LM Studio, llama.cpp `llama-server`, vLLM, LocalAI, or any service exposing `/v1/chat/completions`). Set `base_url` to its `/v1` endpoint and `model` to the model name the server expects. For authenticated endpoints, set `api_key_env` to the name of the environment variable that holds the API key; leave it blank for unauthenticated local servers.

For scheduled automation, the chosen provider must already work without an interactive prompt. Gemini support is for API-key or Vertex-style automation credentials, not interactive Google OAuth. `openai-compatible` requires the inference server to be running before `briefing validate` or any run.

### `openai-compatible` model names

Set `model` to the exact name the server expects, which is usually the model filename or alias it was loaded with. Examples:

| Server | Example model value |
|--------|-------------------|
| LM Studio | `lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF` |
| llama.cpp | `llama-3.1-8b-instruct` |
| vLLM | `meta-llama/Meta-Llama-3.1-8B-Instruct` |
| Ollama (OpenAI compat) | `llama3.1:8b` |

### Example `[llm]` blocks

Copilot (CLI):

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

LM Studio or llama.cpp (OpenAI-compatible API):

```toml
[llm]
provider = "openai-compatible"
command = ""
model = "your-loaded-model-name"
effort = ""
base_url = "http://127.0.0.1:1234/v1"
api_key_env = ""
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

### Recording metadata

Configured series are eligible for `briefing watch` recording by default. Add `recording.record: false` to opt out, or add field-level defaults:

```yaml
recording:
  record: true
  location_type: office
  mode: online
  participants:
    host_name: Casey
    attendees_expected: 4
  transcription:
    language: en-AU
    asr_backend: whisperkit
    diarization_enabled: true
```

Calendar notes can override these fields for one occurrence with a case-insensitive marker:

```text
noted config:
location_type: home
mode: hybrid
participants:
  host_name: Riley
recording_policy:
  default_extension_minutes: 15
```

Use `record: false` under the marker to skip recording for one otherwise matched occurrence. Events with a `noted config` marker are also eligible as one-off recordings even without a series file.

Use `location_type` under the marker to move one occurrence to a different Mac. For example, if the series normally records in the office but this instance is from home, set `location_type: home` in the calendar notes.

`mode` controls the capture layout:

| Mode | Audio files |
|------|-------------|
| `in_person` | `audio/raw_room.wav` |
| `online` | `audio/raw_mic.wav`, `audio/raw_system.wav` |
| `hybrid` | `audio/raw_mic.wav`, `audio/raw_system.wav` |

For a Zoom meeting shifted from office to home, override both fields when needed:

```text
noted config:
location_type: home
mode: online
```

## Planning and watch commands

Write one manifest by event id:

```bash
uv run briefing session-plan --event-id "EVENT-UID-HERE"
```

The command prints one JSON line containing `status`, `manifest_path`, `session_dir`, `note_path`, and `skip_reason` when skipped.

Run the watcher:

```bash
uv run briefing watch
```

`briefing watch` persists plan state under `state/session-plans/`, writes manifests under `[meeting_intelligence].sessions_root`, and archives invalidated unlaunched manifests under `archive/manifests/` rather than deleting them.

For shared multi-Mac settings, prefer a host-name map so the same `settings.toml` can resolve differently on each Mac. The resolved location gates both pre-meeting briefing generation and scheduled recording:

```toml
[meeting_intelligence]
default_location_type = "office"

[meeting_intelligence.location_type_by_host]
"Office-Mac" = "office"
"Home-Mac" = "home"
```

`briefing` checks macOS `HostName`, `LocalHostName`, `ComputerName`, then Python host-name fallbacks. `uv run briefing validate` reports the resolved local meeting location when routing is configured, and warns if host routing is configured but any series has no target `location_type` and no `default_location_type` fallback.

## Global settings reference

### `[paths]`

- `vault_root`: root folder of your notes workspace
- `meeting_notes_dir`: folder inside `vault_root` where notes are written
- `log_dir`: local logs directory
- `state_dir`: local runtime state and diagnostics directory; old run diagnostics and stale occurrence state are pruned automatically
- `prompt_dir`: tracked prompt template directory
- `template_dir`: tracked note template directory
- `series_dir`: local series YAML directory
- `debug_dir`: local debug output directory
- `env_file`: env file loaded for source tokens

### `[meeting_intelligence]`

- `sessions_root`: local root for planned noted session directories and manifests
- `noted_command`: executable used for `noted start --manifest`
- `pre_roll_seconds`: launch lead time; must be between 60 and 180 seconds
- `raw_audio_retention_days`: completed-session raw audio retention window; default 7 days from `completion.json.completed_at`, after which raw audio is moved to macOS Trash
- `reschedule_tolerance_seconds`: in-tolerance calendar movement rewrites a plan; larger movement invalidates it
- `watch_poll_seconds`: delay between `briefing watch` polling cycles
- `watch_lookahead_minutes`: calendar lookahead for watch planning
- `default_location_type`: optional default target location for recorded meetings, such as `office`; leave unset to disable multi-Mac routing by default
- `local_location_type`: optional direct location label for this Mac, such as `home`; if unset, `briefing` checks `location_type_by_host`
- `location_type_by_host`: optional table mapping macOS `HostName`, `LocalHostName`, or `ComputerName` values to location labels
- `default_host_name`, `default_language`, `default_asr_backend`, `default_diarization_enabled`, `default_mode`: manifest defaults
- `one_off_note_dir`: optional note directory for one-off `noted config` events; defaults to `paths.meeting_notes_dir`
- `auto_start`, `auto_stop`, `default_extension_minutes`, `max_single_extension_minutes`, `pre_end_prompt_minutes`, `no_interaction_grace_minutes`: default recording policy fields

Inspect raw audio due for retention cleanup before allowing a sweep to move files:

```bash
uv run briefing retention-sweep --dry-run
```

`briefing watch` and successful `session-ingest` runs also perform best-effort retention sweeps. Only raw audio files in completed sessions are moved; transcripts, summaries, logs, manifests, and `completion.json` stay in the session directory. Running `briefing watch --dry-run` also puts retention in dry-run mode, so files are reported but not moved.

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

- `meeting_notes_placeholder`: placeholder inserted at the start of the user-owned note area under `Meeting Notes`

### `[llm]`

- `provider`: `claude`, `codex`, `copilot`, `gemini`, or `openai-compatible`
- `command`: optional executable override (CLI providers only)
- `model`: provider-specific model name; for `openai-compatible` this is the exact name the server expects
- `effort`: blank, `low`, `medium`, or `high`; not used for `openai-compatible`
- `timeout_seconds`: timeout for one LLM call; readiness checks use a 15-second cap
- `retry_attempts`: retained in config but not used by the current provider implementation
- `temperature`: sampling temperature
- `max_output_tokens`: maximum tokens in the LLM response
- `prompt_template`: prompt template filename under `user_config/prompts/`
- `note_template`: note template filename under `user_config/templates/`
- `base_url`: required for `openai-compatible`; the `/v1` base URL of the inference server
- `api_key_env`: optional for `openai-compatible`; name of the environment variable holding the API key
- `briefing` does not apply a separate global prompt truncation step after source collection; source-specific `max_characters` settings are the real input budget

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

### `[email]`

- `history_days`
- `request_timeout_seconds`
- `max_messages`
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
- OpenCode is configured with a local model but the inference server (Ollama or LM Studio) is not running

### `run` does nothing

Usually one of:

- no meeting starts between `window_min_minutes` and `window_max_minutes`
- no series matched the event
- more than one series matched the event
- the meeting had already started
- an existing note at the managed path had malformed frontmatter or an unrecoverable section layout

### A series exists but never matches

Review the YAML match groups. The most common issue is over-constraining the series with fields that are not stable across occurrences.

### A note was created once but no longer refreshes

`briefing` keeps refreshing only the managed `## Briefing` block until the meeting start time. If refresh stops earlier than that, the usual causes are:

- the meeting start time has already passed
- the note structure is malformed in a way `briefing` cannot reconcile safely
- a required source or LLM step is failing for that occurrence

## Recommended rollout order

1. Set `vault_root` and `meeting_notes_dir`.
2. Confirm calendar access and one LLM CLI work with `uv run briefing validate`.
3. Create one series with `uv run briefing init-series --index N`.
4. Simplify that series until it matches reliably.
5. Run `uv run briefing run` close to a real meeting.
6. Inspect the written note.
7. Add Slack, Notion, or file sources one at a time using the source guides.
8. Install `launchd` only after the manual path works cleanly.
