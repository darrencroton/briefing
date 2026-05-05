# Briefing

You have a recurring meeting in ten minutes. Over the past week you've traded Slack messages with the person, there are open items from last time, and a couple of Notion pages have been updated. You could spend the next ten minutes skimming all of that — or you could open your meeting note and find a short, focused summary already waiting for you.

`briefing` does that — and closes the loop after. Before each configured meeting it reads your Apple Calendar, pulls recent context from the sources you actually use — Slack channels and DMs, Notion pages, local files, Apple Mail, and the previous meeting note — and writes a concise pre-meeting briefing into a Markdown note, ready to glance at before you walk in. After the meeting, when paired with [`noted`](../noted/README.md) for recording, it reads the session transcript and writes a post-meeting summary: the decisions made, actions taken, and threads left open. Both land in the same note.

You choose which meetings are configured and which sources feed each one. A short YAML file per meeting series is all it takes. Everything runs locally on your Mac, on a schedule or on demand.

### What a meeting note looks like

Before the meeting, `briefing` writes a `## Briefing` section with a handful of bullets — typically 3 to 6 — capturing what actually matters for *this* meeting: open actions, recent Slack threads, decisions pending, schedule changes. Each bullet ends with a compact source/date tag so you know where it came from. No filler, no channel-wide noise, no generic summaries.

After the meeting, `briefing session-ingest` appends a `## Meeting Summary` section with decisions, action items, and open questions drawn from the transcript. It is generated from what was actually said, not from your notes.

Between them, from `## Meeting Notes` onward, is yours. `briefing` never touches user-owned content. You can start drafting before the meeting and keep editing throughout; `briefing` will refresh only the `## Briefing` block until the meeting starts, then leave it alone.

### How it works

On a normal day, `briefing watch` runs in the background:

1. For each upcoming configured meeting, it collects recent context from your configured sources and calls your LLM. The `## Briefing` block is written and kept current until the meeting starts.
2. About 90 seconds before start time, `briefing watch` also invokes `noted`, which begins recording. A short bell plays.
3. At the end of the meeting, `noted` transcribes and diarizes locally, then invokes `briefing session-ingest`. Within a few minutes, a `## Meeting Summary` section appears at the bottom of your note with key decisions and actions pulled from what was actually said.

The recording component requires `noted`. Without it, `briefing` handles pre-meeting briefings only.

For meetings outside your calendar — or if you just want a briefing on demand — `briefing run` generates one immediately. `noted`'s menubar gives you a manual recording start for unscheduled conversations.

Only meetings you have explicitly configured are processed. If a required source fails, that meeting's briefing is skipped rather than generated with incomplete context.

## Setup

### Requirements

- macOS (EventKit requires Apple Calendar)
- Python 3.13+ and `uv` on `PATH`
- One supported LLM CLI, authenticated for non-interactive use

Supported LLM CLIs: `claude`, `codex`, `copilot`, `gemini`, `opencode`

For recording: `noted` installed and on `PATH` (see the [`noted` repo](../noted/README.md))

### 1. Run setup

```bash
./scripts/setup.sh
```

Installs dependencies, creates runtime directories, and bootstraps `user_config/settings.toml` from defaults.

### 2. Configure settings.toml

Edit `user_config/settings.toml` to set your LLM provider and notes location. The key section:

```toml
[llm]
provider = "copilot"    # or claude, codex, gemini, opencode
model = "claude-sonnet-4.6"
effort = "high"
```

Authenticate your chosen provider before installing automation:

- `claude` → `claude auth login`
- `codex` → `codex login`
- `copilot` → `copilot login` (or set `COPILOT_GITHUB_TOKEN`)
- `gemini` → set `GEMINI_API_KEY` (or configure Vertex AI credentials)
- `opencode` → for local LLMs, start Ollama or LM Studio; for cloud providers, set the relevant API key (e.g. `ANTHROPIC_API_KEY`)

**Note:** The `claude` CLI uses dash-separated model IDs (e.g. `claude-sonnet-4-5`); `copilot` uses dot-separated (e.g. `claude-sonnet-4.6`); `opencode` uses `provider/model` format (e.g. `ollama/llama3.2`).

The full settings reference is in [`docs/setup-and-configuration-walkthrough.md`](docs/setup-and-configuration-walkthrough.md).

### 3. Add source credentials

The default env file is `~/.env.briefing`. Add secrets only for the sources you use:

- `SLACK_USER_TOKEN`
- `NOTION_TOKEN`

### 4. Validate

```bash
uv run briefing validate
```

Checks local paths, calendar access, LLM readiness, source credentials, and `noted` availability. Fix anything it flags before continuing.

### 5. Create your first series

Review the example at [`user_config/examples/series/example-team-weekly.yaml`](user_config/examples/series/example-team-weekly.yaml), then bootstrap a real series:

```bash
uv run briefing init-series
```

Rerun with `--index` or `--event-uid` if multiple candidate events are found.

### 6. Run once manually

```bash
uv run briefing run
```

Confirm a briefing note appears in your notes directory. Only after a successful manual run should you install automation.

### 7. Set up recording

If `noted` is installed and on `PATH`, dry-run one watch cycle to confirm manifests are planned correctly:

```bash
uv run briefing watch --once --dry-run
```

When that looks right, start the watcher:

```bash
uv run briefing watch
```

To inspect the manifest plan for a single event:

```bash
uv run briefing session-plan --event-id "EVENT-UID-HERE"
```

`noted` invokes `briefing session-ingest` automatically after each session. You can also run it manually — for recovery or inspection:

```bash
uv run briefing session-ingest --session-dir /path/to/session
uv run briefing session-ingest --session-dir /path/to/session --dry-run
uv run briefing session-reprocess --session-dir /path/to/session  # rerun from existing transcript
uv run briefing retention-sweep --dry-run                         # inspect raw audio due for Trash
```

Raw audio for completed sessions is retained for `raw_audio_retention_days` days
(default 7) from `completion.json.completed_at`, then moved to macOS Trash.
Transcripts, summaries, logs, manifests, and `completion.json` remain in place.

For ad hoc recordings started from the `noted` menubar, `noted` must also be able to find a `briefing` command. From this repo:

```bash
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/.venv/bin/briefing" "$HOME/.local/bin/briefing"
which briefing
```

You can instead set `briefing_command` in `~/Library/Application Support/noted/settings.toml` to the absolute path of `.venv/bin/briefing`.

### 8. Install automation

After the manual flow is working, install the `launchd` agents:

→ [`scripts/launchd/README.md`](scripts/launchd/README.md)

### Multi-Mac meeting routing

When `briefing run` or `briefing watch` runs on more than one Mac, use `location_type` labels so only the Mac at the meeting's intended location creates the pre-meeting briefing and starts the recording.

In `user_config/settings.toml`:

```toml
[meeting_intelligence]
default_location_type = "office"
local_location_type = "office"
```

For a shared config used across machines, map host names to locations instead:

```toml
[meeting_intelligence]
default_location_type = "office"

[meeting_intelligence.location_type_by_host]
"Office-Mac" = "office"
"Home-Mac" = "home"
```

`briefing` checks macOS `HostName`, `LocalHostName`, and `ComputerName`. A calendar note can override the location for a single occurrence:

```text
noted config:
location_type: home
```

## Commands

| Command | Purpose |
|---------|---------|
| `uv run briefing run` | Generate briefings for upcoming configured meetings |
| `uv run briefing validate` | Preflight: paths, calendar, LLM, sources, `noted` |
| `uv run briefing init-series` | Bootstrap a series YAML from a calendar event |
| `uv run briefing watch` | Long-running pre-roll planner and `noted` launcher |
| `uv run briefing watch --once --dry-run` | Plan one watch cycle without launching `noted` |
| `uv run briefing session-plan --event-id <id>` | Write a manifest for one event |
| `uv run briefing session-ingest --session-dir <path>` | Ingest a completed recording session |
| `uv run briefing session-reprocess --session-dir <path>` | Rerun summary from an existing transcript |
| `uv run briefing retention-sweep --dry-run` | Preview completed-session raw audio due for Trash |
| `uv run briefing retention-sweep` | Move expired completed-session raw audio to macOS Trash |

## Sources

Each series YAML lists the sources that feed it. Available adapters:

| Source | What it pulls |
|--------|--------------|
| `previous_note` | The most recent earlier note in the same series |
| `slack` | Selected channels or DMs |
| `notion` | Selected standing pages |
| `file` | Local or synced text files |
| `email` | Apple Mail filtered by account, mailbox, address, or subject |

Source-specific setup guides: [`docs/source-guides/`](docs/source-guides/README.md)

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
archive/                  retained local material (git-ignored)
```

## Documentation

- [`docs/setup-and-configuration-walkthrough.md`](docs/setup-and-configuration-walkthrough.md) — full onboarding and settings reference
- [`docs/source-guides/`](docs/source-guides/README.md) — per-source setup guides (Slack, Notion, files, email)
- [`scripts/launchd/README.md`](scripts/launchd/README.md) — automation setup
- [`docs/soak-runbook-week1.md`](docs/soak-runbook-week1.md) — operational checklist for the release soak

## Operational Notes

- macOS will prompt for Calendar access on first run. Grant it, or enable it in System Settings > Privacy & Security > Calendars.
- The selected LLM CLI must already be authenticated before installing `launchd`.
- `launchd` runs in the local Mac timezone.
- The Mac must be awake for scheduled runs to happen on time.
