# Slack Source Setup

This guide shows how to connect Slack to `briefing` for one meeting series.

Use Slack when relevant meeting context lives in:

- a team or project channel
- a private channel
- a one-to-one or multi-person DM conversation

`briefing` reads recent message history and turns it into a digest for the LLM. It does not post back to Slack.

## Quickstart

If you want the short version first, do these in order:

1. [Choose the exact channels or DM conversations you want `briefing` to read](#1-decide-which-slack-conversations-matter).
2. [Open Slack's app management site at `https://api.slack.com/apps` and create a new app from scratch for the correct workspace](#2-create-a-slack-app-in-the-correct-workspace).
3. [In `OAuth & Permissions`, add the required entries under `User Token Scopes`](#3-add-the-correct-user-token-scopes).
4. [Install the app to the workspace and copy the installed `User OAuth Token`](#4-install-the-app-and-copy-the-user-oauth-token).
5. [Put that token in `~/.env.briefing` as `SLACK_USER_TOKEN=...`](#5-save-the-token-in-envbriefing).
6. [Add `channel_refs` and/or `dm_conversation_ids` to the right series YAML file](#7-update-the-series-yaml).
7. [Run `uv run briefing validate`](#8-validate).
8. [Run a real `uv run briefing run`](#9-test-with-a-real-run).

If any Slack screen looks unfamiliar, keep going. The detailed steps below name the exact site, sidebar entry, token label, and fields that matter.

## Before You Start

Make sure all of these are already true:

- `./scripts/setup.sh` has been run
- `uv run briefing validate` already works for calendar and LLM
- you already have a series YAML file under `user_config/series/`
- you are signed into the Slack workspace on your Mac

## What `briefing` Actually Needs From Slack

`briefing` needs exactly two kinds of Slack data:

1. An installed Slack user token in `~/.env.briefing`:

```text
SLACK_USER_TOKEN=your_slack_user_token_here
```

2. Conversation identifiers in the series YAML:

- channel references under `sources.slack.channel_refs`
- DM conversation IDs under `sources.slack.dm_conversation_ids`

Important distinctions:

- Use the installed `User OAuth Token` from Slack's `OAuth & Permissions` page.
- Do not use an app-level token such as `xapp-...`.
- Do not use a bot token such as `xoxb-...`.
- Do not use `Client ID`, `Client Secret`, `Signing Secret`, or `Verification Token`.

Slack's token documentation distinguishes user, bot, and app-level tokens. `briefing` uses a user token because it reads Slack as the installing user. In Slack's current UI that token is shown as the installed `User OAuth Token`, and Slack user tokens typically start with `xoxp-`. See Slack's official token docs: [Slack token types](https://docs.slack.dev/authentication/tokens/).

What the other Slack secrets are for:

- `Client ID` and `Client Secret`: needed for a public OAuth flow. `briefing` does not use Slack OAuth callbacks.
- `Signing Secret` and `Verification Token`: needed when Slack sends HTTP requests to your app. `briefing` does not receive Slack events.
- `App-Level Tokens`: used for different Slack APIs. `briefing` does not use them.

## 1. Decide Which Slack Conversations Matter

Before touching configuration, write down the exact conversations you want the briefing to read.

Good candidates:

- one stable team channel for a weekly team meeting
- one project channel for a steering or delivery meeting
- one DM conversation for a recurring one-on-one or small standing group

Avoid starting with too many channels. A smaller, higher-signal set usually produces better briefings and is easier to debug.

## 2. Create A Slack App In The Correct Workspace

Open Slack's app management site in your browser:

- [https://api.slack.com/apps](https://api.slack.com/apps)

Then do this:

1. Sign in if Slack asks you to.
2. Click `Create New App`.
3. Choose `From scratch`.
4. Enter a simple name such as `Briefing Local`.
5. Choose the Slack workspace that contains the channels or DMs you want `briefing` to read.
6. Finish the creation flow.

You should now be on the new app's settings pages in Slack's browser UI.

If your workspace blocks app creation, ask a workspace admin or owner to create the app or allow local-use apps.

## 3. Add The Correct User Token Scopes

In the app settings sidebar:

1. Click `OAuth & Permissions`.
2. Scroll to the `Scopes` section.
3. Under `User Token Scopes`, click `Add an OAuth Scope`.
4. Add only the scopes that match the conversations you plan to read.

Use these scopes:

- Public channels: `channels:read`, `channels:history`
- Private channels: `groups:read`, `groups:history`
- One-to-one DMs by conversation ID: `im:read`, `im:history`
- Multi-person DMs by conversation ID: `mpim:read`, `mpim:history`
- Human-readable participant names in digests: `users:read`

Why `briefing` needs them:

- it resolves channel names or IDs
- it resolves DM conversation IDs and types
- it reads conversation history
- it resolves readable Slack member names for the digest

If you only need channels, you can skip the DM scopes. If you only need one-to-one DMs, you can skip the `mpim:*` scopes. If you only need group DMs, you can skip the `im:*` scopes.

If you add or change scopes after installing the app, return to `OAuth & Permissions` and run `Install to Workspace` again so Slack issues an updated installed token.

Slack's official guide for this page is here: [Using OAuth scopes](https://docs.slack.dev/authentication/installing-with-oauth#using-oauth-scopes).

## 4. Install The App And Copy The User OAuth Token

Stay on the same `OAuth & Permissions` page.

Then:

1. Scroll to the top `OAuth Tokens` area.
2. Click `Install to Workspace`.
3. Approve the requested permissions as yourself.
4. Return to `OAuth & Permissions`.
5. Copy the installed `User OAuth Token`.

That installed user token is the value `briefing` needs.

Do not copy any of these instead:

- `Bot User OAuth Token`
- `Client Secret`
- `Signing Secret`
- `Verification Token`
- any app-level token

Important practical point:

- the token reflects the access of the user who installed it
- if that user cannot see a private channel, `briefing` cannot read it either
- if that user leaves a channel later, Slack access for that source can break

## 5. Save The Token In `~/.env.briefing`

Put the token in `~/.env.briefing`:

```text
SLACK_USER_TOKEN=your_slack_user_token_here
```

If `~/.env.briefing` already exists, add or update that line and keep any existing variables such as `NOTION_TOKEN`.

## 6. Collect The Conversation Identifiers

### Channels

You can configure channels by name or by channel ID.

Public and private channels use the same YAML field: `sources.slack.channel_refs`.

The only setup difference is access:

- public channels need the public-channel scopes
- private channels need the private-channel scopes
- the installing user must already be able to see the private channel

- Easiest: use the current channel name exactly as it appears in Slack, without the leading `#`
- More stable: use the channel ID

Recommended first-time path:

- start with the channel name if you just need to get working
- switch to the channel ID later if the channel may be renamed

How to get a channel ID:

1. Open the channel in Slack.
2. Open or copy the channel link in the Slack web UI.
3. Look at the URL. Slack channel URLs include `/archives/CHANNEL_ID`.
4. Copy the final `C...` or `G...` identifier.

Examples:

- channel name: `eng-leads`
- channel ID: `C0123456789`

### Direct Messages

For DMs, `briefing` needs the DM conversation ID.

Use the conversation ID, not:

- the other person's member ID
- the other person's display name
- their `@handle`

This now works for both:

- a one-to-one DM conversation
- a multi-person DM conversation

How to get the conversation ID:

1. Open the DM conversation in Slack.
2. Open or copy the conversation link in the Slack web UI.
3. Look at the URL. Slack DM conversation URLs include `/archives/CONVERSATION_ID`.
4. Copy the final `D...` or `G...` identifier.

Examples:

- one-to-one DM conversation ID: `D0123ABC456`
- multi-person DM conversation ID: `G0123ABC456`

`briefing` reads the conversation directly from that ID instead of opening it from a member ID.

## 7. Update The Series YAML

Open the relevant file under `user_config/series/` and add a Slack block.

Example with one channel and one DM:

```yaml
sources:
  slack:
    channel_refs:
      - eng-leads
    dm_conversation_ids:
      - D0123ABC456
```

Example with a private channel by ID:

```yaml
sources:
  slack:
    channel_refs:
      - G0123456789
```

If you want multiple channels, list each one as a separate YAML list item:

```yaml
sources:
  slack:
    channel_refs:
      - general
      - jayde-phd
    dm_conversation_ids:
      - D0123ABC456
      - G0123ABC789
    required: false
```

Inline YAML lists also work if you prefer that style:

```yaml
sources:
  slack:
    channel_refs: [general, jayde-phd]
    dm_conversation_ids: [D0123ABC456, G0123ABC789]
    required: false
```

Do not write multiple channels as one comma-separated string without the surrounding `[` `]`, because that would be a single YAML string rather than a list.

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

## 8. Validate

Run:

```bash
uv run briefing validate
```

For Slack, this confirms:

- `SLACK_USER_TOKEN` exists
- the token can authenticate with Slack

It does not confirm:

- that every channel reference is correct
- that every DM conversation ID is correct
- that the token has access to the specific private channels you chose
- that you copied a user token with all required scopes for every configured conversation type

## 9. Test With A Real Run

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

### I created a Slack app, but I only see `Client ID`, `Client Secret`, `Signing Secret`, or app-level tokens

You are looking in the wrong place. Go to the app sidebar entry `OAuth & Permissions`, add the required entries under `User Token Scopes`, install the app to the workspace, then copy the installed `User OAuth Token`.

### `validate` says Slack token is missing

Add `SLACK_USER_TOKEN` to `~/.env.briefing` and rerun validation.

### `validate` says the Slack token failed

The token is wrong, revoked, expired, copied incorrectly, or you copied something other than the installed user token. Re-copy the installed `User OAuth Token` and rerun.

### The run fails for one private channel

Usually one of:

- the installing user is not a member of that private channel
- the channel reference is wrong
- the token is missing one of the private-channel scopes

### The run fails for a DM

Usually one of:

- you used a member ID or display name instead of the DM conversation ID
- the token is missing the required `im:*` or `mpim:*` scopes
- the conversation ID points to a public/private channel instead of a DM conversation
- the user token cannot access that DM conversation in the current workspace

### The run succeeds but the Slack content is noisy

Reduce `history_days`, remove low-signal channels, or lower `max_characters` for that series.

## What This Source Does Not Do

The current Slack source is intentionally narrow:

- it reads recent history from configured channels and DM conversations
- it includes thread replies under matched parent messages
- it does not search all of Slack
- it does not infer channels automatically from meeting names

For the config shape, see the summary in [`../setup-and-configuration-walkthrough.md`](../setup-and-configuration-walkthrough.md). For the full source guide index, go back to [`README.md`](README.md).
