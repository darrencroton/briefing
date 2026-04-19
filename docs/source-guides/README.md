# Source Setup Guides

These guides explain how to get each current source working in `briefing` without guessing.

Each guide starts with a short quickstart, then a detailed step-by-step section for first-time setup.

Use them after the main install is already working:

- run `./scripts/setup.sh`
- edit `user_config/settings.toml`
- confirm `uv run briefing validate` works for calendar and your selected LLM CLI
- create or review at least one series file in `user_config/series/`

## Choose The Right Guide

- [`slack-source-setup.md`](slack-source-setup.md)
  Add Slack channels or DM conversations to a meeting series.
- [`notion-source-setup.md`](notion-source-setup.md)
  Add one or more standing Notion pages to a meeting series.
- [`file-source-setup.md`](file-source-setup.md)
  Add local or synced text files to a meeting series.
- [`email-source-setup.md`](email-source-setup.md)
  Add Apple Mail messages to a meeting series, filtered by sender, mailbox, or subject.
- [`previous-note-source.md`](previous-note-source.md)
  Understand the built-in previous-note source and how to make it useful.

## Which Source Should You Use?

Use the smallest set of sources that gives you reliable meeting context.

- `previous_note`
  Best default source once a series has already run at least once.
- `slack`
  Best when meeting context mostly lives in active channels or DM conversations.
- `notion`
  Best when a recurring meeting revolves around one or two standing pages.
- `file`
  Best when the relevant context already exists as stable Markdown or text files on disk.
- `email`
  Best for 1:1 meetings where recent email threads with that person are the primary context.

For many users, the best first working setup is:

1. calendar plus `previous_note`
2. one extra source only if you still feel under-prepared before meetings

## When To Use `required: true`

Use `required: true` sparingly.

Recommended default:

- leave new sources as `required: false` until you trust them

Good cases for `required: true`:

- a meeting should not generate at all without one specific Notion page
- a file source is the canonical pre-read and must be present

Usually avoid `required: true` for:

- Slack channels
- first-time source setup
- sources that are useful but not essential

Why this matters:

- a required source failure blocks note generation for that meeting
- an optional source failure is logged and omitted, but the run can still succeed

## Important Validation Detail

`uv run briefing validate` checks different things for different sources:

- Slack: token present and token can authenticate.
- Notion: token present and token can authenticate.
- Files: every configured file path exists.
- Email: macOS Automation permission for Apple Mail is granted.
- Previous note: nothing to configure, so there is nothing explicit to validate.

That means source-level mistakes such as a wrong Slack channel, wrong Slack user ID, or a Notion page that was never shared with the integration may only show up when `uv run briefing run` tries to collect real source data.

## Recommended Order

1. Get one meeting series matching reliably first.
2. Add one source at a time.
3. Run `uv run briefing validate`.
4. Run `uv run briefing run` close to a real meeting in that series.
5. Inspect the note output before adding more sources.
