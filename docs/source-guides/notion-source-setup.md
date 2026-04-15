# Notion Source Setup

This guide shows how to connect Notion to `briefing` for one meeting series.

Use the Notion source when a recurring meeting depends on one or more standing pages such as:

- a weekly agenda page
- a project status page
- a planning page
- a shared prep page that is updated between meetings

The current Notion source reads page content as block text. It is best for normal Notion pages rather than database-style querying.

## Quickstart

If you want the short version first, do these in order:

1. [Choose the exact Notion pages that should feed the briefing](#1-decide-which-pages-should-feed-the-briefing).
2. [Create an internal Notion integration in the `My integrations` dashboard](#2-create-an-internal-notion-integration).
3. [On the integration's `Capabilities` tab, enable at least `Read content`](#3-enable-the-required-capability).
4. [On the integration's `Configuration` tab, copy the integration token and store it as `NOTION_TOKEN`](#4-copy-the-integration-token).
5. [Open each page, use `...` > `Add connections`, and add the integration](#5-share-each-page-with-the-integration).
6. [Copy each page ID and add it to the series YAML](#6-copy-the-page-id).
7. [Run `uv run briefing validate`](#8-validate).
8. [Run a real `uv run briefing run`](#9-test-with-a-real-run).

If you have seen Notion screens talking about OAuth, redirect URIs, or client secrets, ignore that for this setup. `briefing` uses a single-workspace internal integration, not a public OAuth integration.

## Before You Start

Make sure all of these are already true:

- `./scripts/setup.sh` has been run
- `uv run briefing validate` already works for calendar and LLM
- you already have a series YAML file under `user_config/series/`
- you can open the target Notion pages on your Mac

## What `briefing` Actually Needs From Notion

`briefing` needs exactly two things from Notion:

1. A Notion integration token in `~/.env.briefing`:

```text
NOTION_TOKEN=your_notion_integration_token_here
```

2. One or more page IDs in your series YAML:

```yaml
sources:
  notion:
    - label: Weekly agenda
      page_id: your_notion_page_id_here
```

Important distinctions:

- Use an internal integration, not a public OAuth integration.
- Use the integration token from the integration's `Configuration` tab.
- Share each target page with that integration.
- Do not use an OAuth client secret, redirect URI, authorization URL, or integration ID in place of the token.

## 1. Decide Which Pages Should Feed The Briefing

Pick the pages that genuinely help before the meeting.

Good candidates:

- the standing agenda page for that meeting
- one project status page
- one planning or tracker page that is maintained between meetings

Avoid adding many overlapping pages on day one. If several pages repeat the same material, the digest becomes noisy fast.

## 2. Create An Internal Notion Integration

Open Notion's integrations dashboard.

Official entry points:

- [Authorization guide](https://developers.notion.com/guides/get-started/authorization)
- [Build your first integration](https://developers.notion.com/guides/get-started/create-a-notion-integration)

From those pages, open `My integrations`. In current Notion workspaces this lands in the integrations dashboard for your account.

Then do this:

1. Click `New integration`.
2. Choose `Internal`.
3. Give it a simple name such as `Briefing Local`.
4. Choose the workspace that contains the pages you want `briefing` to read.
5. Finish the creation flow.

Notion's official authorization guide notes that internal integrations are tied to a single workspace and are the right fit when you are reading pages inside your own workspace.

If you cannot create the integration, check whether you are a workspace owner or whether your workspace restricts integration creation.

## 3. Enable The Required Capability

Open the new integration in the Notion integrations dashboard.

Then:

1. Click the `Capabilities` tab.
2. Enable `Read content`.
3. Save if Notion asks you to.

`briefing` only reads existing pages, so `Read content` is the critical capability. Notion's capabilities reference says integrations that export or read data only need `Read content`: [Integration capabilities](https://developers.notion.com/reference/capabilities).

## 4. Copy The Integration Token

Stay on the same integration and open the `Configuration` tab.

Then:

1. Find the integration token in the `Configuration` tab.
2. Copy that token.
3. Put it in `~/.env.briefing`:

```text
NOTION_TOKEN=your_notion_integration_token_here
```

If the env file already exists, keep any other variables and just add or update the Notion line.

Do not use any of these instead:

- OAuth client ID
- OAuth client secret
- redirect URI
- authorization URL
- integration ID

Those values matter for public OAuth integrations. They are not part of the `briefing` setup flow.

## 5. Share Each Page With The Integration

This is the step most people miss.

Creating the integration is not enough by itself. The integration must also be granted access to each page you want `briefing` to read.

For every page you plan to configure:

1. Open the page in Notion.
2. Click the `...` menu at the top right.
3. Scroll down to `Add connections`.
4. Search for the integration you created.
5. Select it and confirm the connection.

That exact `...` > `Add connections` path is described in Notion's authorization guide and getting-started guide.

If a page is not shared with the integration, `briefing` may validate the token successfully but still fail at runtime when it tries to read that page.

## 6. Copy The Page ID

For each page:

1. Open the page in Notion.
2. Copy the page link.
3. Find the long page identifier in the URL.
4. Use that page ID in your YAML.

Practical rule:

- if the copied URL ends with a 32-character page ID, use that
- if it contains hyphens, remove the hyphens so the YAML matches the examples in this repo
- ignore any trailing `?` query string

Example:

- URL fragment: `01234567-89ab-cdef-0123-456789abcdef`
- YAML value: `0123456789abcdef0123456789abcdef`

## 7. Update The Series YAML

Open the relevant file under `user_config/series/` and add one or more Notion entries.

Example:

```yaml
sources:
  notion:
    - label: Weekly agenda
      page_id: 0123456789abcdef0123456789abcdef
    - label: Delivery tracker
      page_id: fedcba9876543210fedcba9876543210
      required: false
```

Useful optional fields:

- `required`
  Set to `true` only if the meeting should fail when that page cannot be read.
- `max_characters`
  Override the per-page text cap before truncation.

Example with a tighter cap:

```yaml
sources:
  notion:
    - label: Weekly agenda
      page_id: 0123456789abcdef0123456789abcdef
      max_characters: 8000
```

### Should A Notion Page Be Required?

Sometimes, yes.

This is the most reasonable source to mark as required when one specific page is the standing agenda or the single source of truth for that meeting.

Recommended default:

- start with `required: false`
- switch to `required: true` only after the page access and page ID are proven stable

## 8. Validate

Run:

```bash
uv run briefing validate
```

For Notion, this confirms:

- `NOTION_TOKEN` exists
- the token can authenticate with Notion

It does not confirm:

- that every configured page ID is correct
- that each page was shared with the integration
- that the integration has the right content capability
- that the selected pages are the right ones for the meeting

## 9. Test With A Real Run

Run:

```bash
uv run briefing run
```

Do this close to a real meeting that matches the series.

Then inspect the note and check that:

- the briefing contains the expected Notion-derived content
- the content is readable and relevant
- the configured pages are not overwhelming the note

If a page fails at runtime, check the logs and confirm all of these:

- the `page_id` in YAML is correct
- the page is explicitly shared with the integration
- the integration still has `Read content`

## Recommended First-Time Pattern

If you are setting this up for the first time:

1. start with one page only
2. keep `required: false`
3. run one manual test
4. add a second page only if the first one is useful and low-noise

## Common Problems

### I created a Notion integration, but I only see OAuth settings and client secrets

You are likely looking at a public integration. For `briefing`, create or use an `Internal` integration instead and copy the token from its `Configuration` tab.

### `validate` says the Notion token is missing

Add `NOTION_TOKEN` to `~/.env.briefing` and rerun validation.

### `validate` says the Notion token failed

The token is wrong, revoked, copied incorrectly, or the integration is no longer valid for that workspace. Re-copy the integration token from the `Configuration` tab and rerun.

### `validate` passes but the run fails for one page

The token is valid, but one of these is wrong:

- the `page_id` is wrong
- the page was never shared with the integration
- the integration does not have `Read content`

### The page content is too long or too noisy

Lower `max_characters`, remove low-signal pages, or use a tighter page that contains only meeting-relevant material.

## What This Source Does Not Do

The current Notion source is intentionally narrow:

- it reads configured page content as a block tree
- it does not search all of Notion
- it does not infer pages automatically from meeting names
- it is not a full database/query integration

For the config shape, see the summary in [`../setup-and-configuration-walkthrough.md`](../setup-and-configuration-walkthrough.md). For the full source guide index, go back to [`README.md`](README.md).
