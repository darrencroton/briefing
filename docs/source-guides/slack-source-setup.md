# Slack Source Setup

This guide shows how to connect Slack to `briefing` for one meeting series.

Use Slack when relevant meeting context lives in:

- a team or project channel
- a private channel
- a one-to-one DM with a recurring participant

`briefing` reads recent message history and turns it into a digest for the LLM. It does not post back to Slack.

## Before You Start

Make sure all of these are already true:

- `./scripts/setup.sh` has been run
- `uv run briefing validate` already works for calendar and LLM
- you already have a series YAML file under `user_config/series/`
- you are signed into the Slack workspace on your Mac

## What You Need From Slack

`briefing` expects a Slack user token in `~/.env.briefing`:

```text
SLACK_USER_TOKEN=your_slack_user_token_here
```

It also needs one or both of:

- channel references under `sources.slack.channel_refs`
- Slack user IDs under `sources.slack.dm_user_ids`

Channel references can be channel names or channel IDs. For long-term stability, channel IDs are safer because channel names can change.

Direct messages must use Slack user IDs, not display names.

## Step 1. Decide Which Slack Conversations Matter

Before touching configuration, write down the exact conversations you want the briefing to read.

Good candidates:

- one stable team channel for a weekly team meeting
- one project channel for a steering or delivery meeting
- one DM for a recurring one-on-one

Avoid starting with too many channels. A smaller, higher-signal set usually produces better briefings and is easier to debug.

## Step 2. Create A Slack App For Your Workspace

Create a Slack app in the workspace that holds the conversations you want to read.

Suggested approach:

1. Open the Slack app management site for your workspace.
2. Create a new app from scratch.
3. Give it a clear local-use name such as `Briefing Local`.
4. Select the Slack workspace you want `briefing` to read from.

This app is only there to obtain a user token with the right scopes.

## Step 3. Add The User Token Scopes You Need

Add only the scopes that match the sources you plan to use.

For public channels:

- `channels:read`
- `channels:history`

For private channels:

- `groups:read`
- `groups:history`

For direct messages:

- `im:history`
- `im:write`

For readable names in digests:

- `users:read`

Why these matter in `briefing`:

- it resolves channel references
- it opens direct-message conversations from a user ID
- it reads conversation history
- it resolves human-readable Slack member names for the digest

If you only need channels, you can skip the DM-related scopes.

## Step 4. Install The App And Copy The User Token

Install the app to the workspace, then copy the user token Slack provides for the installing user.

Put it in `~/.env.briefing`:

```text
SLACK_USER_TOKEN=your_slack_user_token_here
```

If `~/.env.briefing` already exists, just add the new line and keep any existing variables such as `NOTION_TOKEN`.

Important practical point:

- the token reflects the access of the user who installed it
- if that user cannot see a private channel, `briefing` cannot read it either
- if that user leaves a channel later, Slack access for that source can break

## Step 5. Collect The Conversation Identifiers

### For channels

Pick one of these approaches:

- easiest: use the Slack channel name, for example `eng-leads`
- more stable: use the Slack channel ID

If you are just getting started, a channel name is fine. If the channel might be renamed, switch to the ID later.

### For direct messages

Open the person’s Slack profile and copy their member ID. Slack user IDs usually look like `U0123ABC456`.

Use the member ID, not:

- the person’s display name
- the `@handle`
- the DM conversation ID

`briefing` opens the DM from the Slack user ID each time it runs.

## Step 6. Update The Series YAML

Open the relevant file under `user_config/series/` and add a Slack block.

Example with one channel and one DM:

```yaml
sources:
  slack:
    channel_refs:
      - eng-leads
    dm_user_ids:
      - U0123ABC456
```

Useful optional fields:

- `required`
  Set to `true` only if the meeting should fail when Slack cannot be collected.
- `history_days`
  Override the default Slack lookback window for this series.
- `max_characters`
  Override the per-series text cap before truncation.

Example with explicit overrides:

```yaml
sources:
  slack:
    channel_refs:
      - C0123456789
    required: false
    history_days: 5
    max_characters: 12000
```

### Should Slack Be Required?

Usually no.

Slack is often useful context, but it is also the source most likely to fail for operational reasons such as token expiry, workspace access, or private-channel membership.

Recommended default:

- start with `required: false`

Only consider `required: true` if the meeting briefing would be actively misleading without Slack and you are comfortable blocking note generation when Slack cannot be collected.

## Step 7. Validate

Run:

```bash
uv run briefing validate
```

For Slack, this confirms:

- `SLACK_USER_TOKEN` exists
- the token can authenticate with Slack

It does not confirm:

- that every channel reference is correct
- that every DM user ID is correct
- that the token has access to the specific private channels you chose

## Step 8. Test With A Real Run

Run:

```bash
uv run briefing run
```

Do this close to a real meeting that matches the series.

Then inspect the resulting note and check that:

- the meeting matched the expected series
- the briefing contains Slack-derived context
- the digest is relevant rather than noisy

If the note is missing expected Slack content, review the runtime logs in `logs/` and the run diagnostics in `state/runs/`.

## Recommended First-Time Pattern

If you are unsure how much Slack to include, start with this:

1. one channel only, no DMs
2. `required: false`
3. default `history_days`
4. one manual test run

Once that works, add a DM or tighten the lookback window.

## Common Problems

### `validate` says Slack token is missing

Add `SLACK_USER_TOKEN` to `~/.env.briefing` and rerun validation.

### `validate` says the Slack token failed

The token is wrong, expired, revoked, or missing a valid workspace installation. Re-copy the installed user token and rerun.

### The run fails for one private channel

The installing user usually is not a member of that private channel, or the channel reference is wrong.

### The run succeeds but the Slack content is noisy

Reduce `history_days`, remove low-signal channels, or lower `max_characters` for that series.

## What This Source Does Not Do

The current Slack source is intentionally narrow:

- it reads recent history from configured channels and one-to-one DMs
- it includes thread replies under matched parent messages
- it does not search all of Slack
- it does not infer channels automatically from meeting names

For the config shape, see the summary in [`../setup-and-configuration-walkthrough.md`](../setup-and-configuration-walkthrough.md). For the full source guide index, go back to [`README.md`](README.md).
