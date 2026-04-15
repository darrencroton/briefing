# File Source Setup

This guide shows how to add local or synced files to a meeting series in `briefing`.

Use the file source when important meeting context already exists as text on disk, for example:

- a Markdown project tracker
- an exported planning document
- a plain-text status note
- a synced text file from another tool

The file source is often the easiest additional source because it does not require an external API token.

## Quickstart

If you want the short version first:

1. [Choose one small, relevant text file](#step-1-choose-the-exact-files).
2. [Confirm the exact filesystem path on the Mac that runs `briefing`](#step-2-confirm-the-file-path-on-disk).
3. [Add that path under `sources.files` in the series YAML](#step-3-update-the-series-yaml).
4. [Run `uv run briefing validate`](#step-4-validate).
5. [Run a real `uv run briefing run` and confirm the file adds signal rather than noise](#step-5-test-with-a-real-run).

## Before You Start

Make sure all of these are already true:

- `./scripts/setup.sh` has been run
- `uv run briefing validate` already works for calendar and LLM
- you already have a series YAML file under `user_config/series/`
- the files you want to use already exist on the Mac that runs `briefing`

## What Makes A Good File Source

Good file sources are:

- stable paths that do not move often
- UTF-8 text files
- relatively focused on one meeting, project, or workstream
- updated often enough to stay useful

Best results usually come from Markdown or plain-text files with a clear structure.

Avoid:

- binary files
- files that sync unreliably to the Mac
- giant catch-all notes with many unrelated topics

## Step 1. Choose The Exact Files

Write down the files that should feed the meeting briefing.

Good starting point:

- one file for one series

If you are unsure, start with the smallest file that would still help you prepare for the meeting.

## Step 2. Confirm The File Path On Disk

Open the file on your Mac and confirm the actual filesystem path.

Practical ways to get the path:

- in Finder, select the file and use `Get Info`
- in Finder, hold `Option`, right-click the file, and use `Copy ... as Pathname`
- if the file is already inside this repo, use the repo-relative path

`briefing` supports paths such as:

- an absolute path
- a `~` home-relative path
- a repo-relative path

Examples:

```text
~/Documents/projects/roadmap.md
/Users/you/Library/Mobile Documents/com~apple~CloudDocs/Team/project-status.md
notes/reference/project-brief.md
```

Choose paths that are likely to stay stable. If the file lives in a folder that changes names often, move or duplicate it to a more stable location first.

## Step 3. Update The Series YAML

Open the relevant file under `user_config/series/` and add a `files` block.

Example:

```yaml
sources:
  files:
    - label: Project tracker
      path: ~/Documents/projects/project-tracker.md
```

You can add more than one file:

```yaml
sources:
  files:
    - label: Project tracker
      path: ~/Documents/projects/project-tracker.md
    - label: Delivery notes
      path: ~/Documents/projects/delivery-notes.md
      required: false
```

Useful optional fields:

- `required`
  Set to `true` only if the meeting should fail when that file is missing.
- `max_characters`
  Override the per-file text cap before truncation.

Example with an explicit cap:

```yaml
sources:
  files:
    - label: Project tracker
      path: ~/Documents/projects/project-tracker.md
      max_characters: 10000
```

### Should A File Source Be Required?

Sometimes, yes.

A local file is a good candidate for `required: true` when it is the canonical brief, tracker, or pre-read for that meeting and the path is stable.

Recommended default:

- start with `required: false`
- switch to `required: true` only after validation and a few successful manual runs

## Step 4. Validate

Run:

```bash
uv run briefing validate
```

For file sources, validation checks every configured path and tells you if any file is missing.

This is stronger than the Slack and Notion validation because the app can directly test the file paths.

## Step 5. Test With A Real Run

Run:

```bash
uv run briefing run
```

Do this close to a real meeting that matches the series.

Then inspect the note and check that:

- the file-derived content appears in the briefing
- the selected files add signal rather than repetition
- the content is not so large that it drowns out the rest of the note

## Recommended First-Time Pattern

If you are using file sources for the first time:

1. start with one file
2. keep `required: false`
3. let validation confirm the path
4. run one manual test
5. add more files only if each one clearly adds value

## Common Problems

### `validate` says the file is missing

The path is wrong, the file moved, or the file is not present on the current Mac.

### The run fails with a text decoding error

The file is probably not plain UTF-8 text. Convert or export it to a text format such as Markdown first.

### The briefing becomes too long or repetitive

Use fewer files, smaller files, or a lower `max_characters` per file.

## What This Source Does Not Do

The current file source is intentionally simple:

- it reads a configured file path directly
- it does not search folders
- it does not infer files from meeting names
- it works best with text files, especially Markdown

For the config shape, see the summary in [`../setup-and-configuration-walkthrough.md`](../setup-and-configuration-walkthrough.md). For the full source guide index, go back to [`README.md`](README.md).
