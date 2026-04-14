# Notion Source Setup

This guide shows how to connect Notion to `briefing` for one meeting series.

Use the Notion source when a recurring meeting depends on one or more standing pages such as:

- a weekly agenda page
- a project status page
- a planning page
- a shared prep page that is updated between meetings

The current Notion source reads page content as block text. It is best for normal Notion pages rather than database-style querying.

## Before You Start

Make sure all of these are already true:

- `./scripts/setup.sh` has been run
- `uv run briefing validate` already works for calendar and LLM
- you already have a series YAML file under `user_config/series/`
- you can open the target Notion pages on your Mac

## What You Need From Notion

`briefing` expects a Notion integration token in `~/.env.briefing`:

```text
NOTION_TOKEN=your_notion_integration_token_here
```

It also needs one or more page IDs in your series YAML:

```yaml
sources:
  notion:
    - label: Weekly agenda
      page_id: your_notion_page_id_here
```

## Step 1. Decide Which Pages Should Feed The Briefing

Pick the pages that genuinely help before the meeting.

Good candidates:

- the standing agenda page for that meeting
- one project status page
- one planning or tracker page that is maintained between meetings

Avoid adding many overlapping pages on day one. If several pages repeat the same material, the digest becomes noisy fast.

## Step 2. Create A Notion Integration

Create an internal integration in Notion for local use with `briefing`.

Suggested approach:

1. Open the Notion integrations dashboard.
2. Create a new internal integration.
3. Give it a clear name such as `Briefing Local`.
4. Finish creation and copy the integration secret.

Put that token in `~/.env.briefing`:

```text
NOTION_TOKEN=your_notion_integration_token_here
```

If the env file already exists, keep any other variables and just add or update the Notion line.

## Step 3. Share Each Page With The Integration

This is the step most people miss.

Creating the integration is not enough by itself. The integration must also be granted access to each page you want `briefing` to read.

For every page you plan to configure:

1. Open the page in Notion.
2. Use the page sharing or connections UI.
3. Add the integration you created in the previous step.
4. Confirm it now appears as a connection on that page.

If a page is not shared with the integration, `briefing` may validate the token successfully but still fail at runtime when it tries to read that page.

## Step 4. Copy The Page ID

For each page:

1. Open the page.
2. Copy the page link.
3. Extract the page ID from the URL.

In most Notion page URLs, the page ID is the long identifier at the end of the URL before any `?` query string.

Use one consistent format in your config. If you are unsure, paste the page ID exactly as copied from the URL or link.

## Step 5. Update The Series YAML

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

## Step 6. Validate

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
- that the selected pages are the right ones for the meeting

## Step 7. Test With A Real Run

Run:

```bash
uv run briefing run
```

Do this close to a real meeting that matches the series.

Then inspect the note and check that:

- the briefing contains the expected Notion-derived content
- the content is readable and relevant
- the configured pages are not overwhelming the note

If a page fails at runtime, check the logs and confirm both of these:

- the `page_id` in YAML is correct
- the page is explicitly shared with the integration

## Recommended First-Time Pattern

If you are setting this up for the first time:

1. start with one page only
2. keep `required: false`
3. run one manual test
4. add a second page only if the first one is useful and low-noise

## Common Problems

### `validate` says the Notion token is missing

Add `NOTION_TOKEN` to `~/.env.briefing` and rerun validation.

### `validate` says the Notion token failed

The token is wrong, revoked, or copied incorrectly. Re-copy the integration token and rerun.

### `validate` passes but the run fails for one page

The token is valid, but the page ID is wrong or the page was never shared with the integration.

### The page content is too long or too noisy

Lower `max_characters`, remove low-signal pages, or use a tighter page that contains only meeting-relevant material.

## What This Source Does Not Do

The current Notion source is intentionally narrow:

- it reads configured page content as a block tree
- it does not search all of Notion
- it does not infer pages automatically from meeting names
- it is not a full database/query integration

For the config shape, see the summary in [`../setup-and-configuration-walkthrough.md`](../setup-and-configuration-walkthrough.md). For the full source guide index, go back to [`README.md`](README.md).
