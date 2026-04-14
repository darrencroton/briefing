# Previous Note Source

This guide explains the built-in `previous_note` source in `briefing`.

Unlike Slack, Notion, and file sources, you do not configure this source manually. It is always attempted automatically for every series.

It is also always non-blocking. If no earlier note exists yet, the run still continues normally.

## What It Does

For each meeting occurrence, `briefing` looks for the most recent earlier note with the same `series_id`.

If it finds one, it extracts the high-value parts of that note:

- the note title
- the previous `Briefing`
- the previous `Meeting Notes`
- the previous `Actions`

That material is then passed into the next run as source context.

If no earlier note exists yet, `briefing` simply records that no previous meeting note was found and continues.

## Why It Matters

For many recurring meetings, the previous note becomes the most useful source after the first few runs because it carries forward:

- unresolved actions
- the last meeting’s context
- any notes you wrote in the meeting itself

In practice, many users can get good results from calendar plus previous note alone before adding Slack, Notion, or file sources.

## What You Need To Do

There is no dedicated YAML block to add.

To make the previous-note source useful, focus on the parts of the setup that determine note continuity:

1. make sure the meeting series matches reliably
2. keep the same `series_id` for the same recurring meeting
3. let `briefing` create at least one note for that series
4. keep using that series for later occurrences

## Step 1. Make The Series Match Reliably

The previous-note source only helps if each occurrence lands in the same series consistently.

Review the series YAML and make sure the `match` rules are stable. Good options are:

- title plus calendar name for a recurring team meeting
- attendee email for a recurring one-on-one
- title plus organizer email when titles are slightly inconsistent

If the match rules are too loose, the wrong meeting can match the series. If they are too tight, later occurrences may stop matching entirely.

## Step 2. Keep `series_id` Stable

`briefing` finds previous notes by looking at the `series_id` stored in note frontmatter.

That means:

- changing `display_name` is usually fine
- changing `series_id` breaks the chain to earlier notes

If you need to rename a series for presentation reasons, prefer changing `display_name` first and leaving `series_id` alone.

## Step 3. Let The First Note Be Created

The first occurrence in a new series will not have a previous note yet. That is expected.

Run:

```bash
uv run briefing run
```

Once the first note exists, later runs in the same series can use it as historical context.

## Step 4. Keep The Managed Note Structure Intact

The previous-note summariser looks at the note structure that `briefing` writes:

- `## Briefing`
- `## Meeting Notes`
- `## Actions`

Normal user editing inside `Meeting Notes` and `Actions` is expected and useful. That content is part of what makes the previous-note source valuable.

What matters is keeping the note as a normal `briefing` meeting note rather than turning it into an unrelated document format.

## Step 5. Check That It Is Working

After at least two successful occurrences in the same series:

1. run `uv run briefing run` before a later meeting
2. inspect the new note
3. confirm that the generated briefing clearly reflects context from the previous note

If it does not, check whether:

- the meetings are matching the same series
- the older note still has the correct `series_id` in frontmatter
- the older note’s `start` value is earlier than the current meeting

## Common Problems

### The first meeting says no previous note was found

Expected. There is no earlier note yet.

### Later meetings still say no previous note was found

Usually one of:

- the meetings are not matching the same `series_id`
- the earlier note is missing or was moved out of `meeting_notes_dir`
- the earlier note frontmatter no longer contains the expected `series_id` or `start`

### I changed the series configuration and history stopped carrying forward

If you changed `series_id`, that is the most likely cause. Restore the original `series_id` if you want continuity with existing notes.

## Recommended First-Time Pattern

For a new install:

1. get one recurring series matching correctly
2. let `briefing` create the first note
3. attend the meeting and add useful notes/actions
4. let the next occurrence reuse that material
5. only then decide whether extra sources are actually necessary

For the broader setup flow, see [`../setup-and-configuration-walkthrough.md`](../setup-and-configuration-walkthrough.md). For the full source guide index, go back to [`README.md`](README.md).
