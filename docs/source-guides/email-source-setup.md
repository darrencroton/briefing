# Email Source Setup

This guide shows how to connect Apple Mail to `briefing` for one meeting series.

Use the email source when relevant meeting context lives in:

- recent messages exchanged with a specific person or small group
- emails in a dedicated mailbox or project folder
- threads matching a recurring subject keyword

`briefing` reads recent message history from Apple Mail and turns it into a digest for the LLM. It does not send or modify any email.

## Quickstart

If you want the short version first, do these in order:

1. [Grant macOS Automation permission to allow `briefing` to script Apple Mail](#1-grant-macos-automation-permission).
2. [Decide which emails matter for the meeting series](#2-decide-which-emails-matter).
3. [Add an `email` block to the relevant series YAML file](#3-update-the-series-yaml).
4. [Run `uv run briefing validate`](#4-validate).
5. [Run a real `uv run briefing run`](#5-test-with-a-real-run).

## Before You Start

Make sure all of these are already true:

- `./scripts/setup.sh` has been run
- `uv run briefing validate` already works for calendar and LLM
- you already have a series YAML file under `user_config/series/`
- Apple Mail is installed and configured with at least one account
- Apple Mail is open (or set to open at login)

## What `briefing` Actually Needs From Mail

`briefing` needs exactly one thing:

- macOS Automation permission granted so that `osascript` can query Apple Mail

There are no tokens, API keys, or credentials to configure. `briefing` does not connect directly to your mail server. It queries Apple Mail locally using the same AppleScript interface available to any Mac application with Automation access.

What `briefing` reads for each configured email source:

- the subject line
- the sender name and address
- the date and time received
- the first 400 characters of the message body

It does not read attachments, read receipts, or private metadata beyond those fields.

## 1. Grant macOS Automation Permission

Before Apple Mail can be scripted, macOS requires explicit Automation permission for the process doing the scripting.

The first time `briefing` runs with an email source configured, macOS will show a system permission dialog:

> `uv` wants to control `Mail`. Allowing control will provide access to documents and data in `Mail`, and to perform actions within that app.

Click `Allow`.

If you dismissed that dialog without allowing it, fix it manually:

1. Open **System Settings**.
2. Go to **Privacy & Security → Automation**.
3. Find `uv` (or `Python`, depending on how you run `briefing`) in the list.
4. Enable the toggle next to **Mail**.

Run `uv run briefing validate` after granting permission to confirm it worked.

## 2. Decide Which Emails Matter

Before editing configuration, decide the filtering approach for the series.

The email source supports three independent filters that can be combined:

### Filter by email address

Best when the meeting involves a specific person and any email exchanged with them is relevant — whether you sent it or they did.

```yaml
email_addresses: [ben@example.com]
```

`briefing` keeps any email where the configured address appears in either the `From` or `To` field. This means outgoing emails (e.g. a report request you sent that has not yet been replied to) are captured alongside incoming ones.

You can list multiple addresses. `briefing` keeps emails where any of the configured addresses appear in `From` or `To` (OR logic).

```yaml
email_addresses: [ben@example.com, alice@example.com]
```

### Filter by mailbox

Best when you have already organised relevant emails into a folder or project mailbox.

```yaml
mailboxes: [INBOX]
```

Use the exact mailbox name as it appears in Apple Mail's sidebar. For example:

- `INBOX` — your inbox in the default account
- `Project Alpha` — a custom folder
- `Sent` — your sent messages

If you omit `mailboxes`, `briefing` searches all mailboxes in all configured accounts.

### Filter by subject

Best for project-specific threads with a consistent subject pattern.

```yaml
subject_regex_any: [Q2 planning, roadmap]
```

Each pattern is a case-insensitive Python regular expression. `briefing` keeps emails where the subject matches any of the patterns (OR logic).

### Filter by account

If you have multiple mail accounts in Apple Mail and want to limit the search to one:

```yaml
account: iCloud
```

Use the account name exactly as it appears in Apple Mail's sidebar under **Accounts**.

### Lookback window

`briefing` looks back 7 days by default. For fortnightly or monthly meetings you may want a longer window:

```yaml
history_days: 14
```

## 3. Update The Series YAML

Open the relevant file under `user_config/series/` and add an `email` block inside `sources`.

The source label in the LLM prompt is derived automatically as "Emails related to `<series display_name>`".

Minimal example — filter by email address (matches both sent and received):

```yaml
sources:
  email:
    - email_addresses: [ben@example.com]
      history_days: 7
      required: false
```

Example with mailbox and subject filter combined:

```yaml
sources:
  email:
    - mailboxes: [Project Alpha]
      subject_regex_any: [alpha, project kickoff]
      history_days: 14
      required: false
```

Example with all filter fields for a 1:1 meeting:

```yaml
sources:
  email:
    - account: iCloud
      mailboxes: [INBOX]
      email_addresses: [ben@example.com]
      subject_regex_any: []
      history_days: 7
      max_messages: 20
      max_characters: 10000
      required: false
```

You can configure multiple email sources per series by adding more list items:

```yaml
sources:
  email:
    - email_addresses: [ben@example.com]
      history_days: 7
      required: false
    - mailboxes: [Project Alpha]
      history_days: 14
      required: false
```

Available fields:

| Field | Required | Default | Notes |
|---|---|---|---|
| `email_addresses` | no | `[]` | Email addresses to match; OR logic |
| `account` | no | all accounts | Apple Mail account name |
| `mailboxes` | no | all mailboxes | Mailbox names to search; OR logic |
| `subject_regex_any` | no | `[]` | Case-insensitive Python regex patterns; OR logic |
| `history_days` | no | 7 | Lookback window |
| `max_messages` | no | 20 | Cap on messages returned before truncation |
| `max_characters` | no | 10000 | Cap on formatted output before truncation |
| `required` | no | `false` | Block note generation if this source fails |

### Should the Email Source Be Required?

Usually no.

The email source fails if Apple Mail is not running when `briefing` fires. Under launchd, Mail may not yet be open during an early-morning trigger. Setting `required: false` means a note is still generated using other sources.

Recommended default:

- start with `required: false`

Only set `required: true` if the meeting briefing would be actively misleading without email context and you are certain Apple Mail is always running.

## 4. Validate

Run:

```bash
uv run briefing validate
```

For the email source, this confirms that:

- Apple Mail can be scripted from the current process

It does not confirm:

- that every address in `email_addresses` is correct
- that the mailbox names exist in Apple Mail
- that the lookback window will return any messages

## 5. Test With A Real Run

Run:

```bash
uv run briefing run
```

Do this close to a real meeting that matches the series.

Then inspect the resulting note and check that:

- the meeting matched the expected series
- the briefing contains email-derived context
- the digest is relevant rather than noisy

If the note is missing expected email content, review the runtime logs in `logs/` and the run diagnostics in `state/runs/`.

## Recommended First-Time Pattern

If you are unsure how to configure email for a series, start with this:

1. one address in `email_addresses`
2. no mailbox filter (search everywhere)
3. `required: false`
4. default `history_days`
5. one manual test run

Once that works, add a mailbox filter or subject pattern to narrow the results.

## Common Problems

### `validate` says Apple Mail automation permission required

Go to **System Settings → Privacy & Security → Automation**, find `uv` in the list, and enable the toggle next to **Mail**. Then rerun `validate`.

### `validate` says Apple Mail is not running

Open Mail.app. Then rerun `validate`.

### The note has no email content

Usually one of:

- no emails in the lookback window match the configured filters
- the sender address is slightly different from what Apple Mail received (check the actual `From:` header in the mail)
- the mailbox name does not match what Apple Mail shows (check the sidebar spelling exactly)

### The note has too much email content

Reduce `history_days`, tighten `email_addresses` to fewer addresses, add a `subject_regex_any` filter, or lower `max_characters` for that series.

### Emails appear in the briefing from unexpected senders

You have not set a `email_addresses` filter. Add one to restrict to the relevant person.

### The email source fails under launchd but works interactively

Apple Mail is not running when the launchd job fires. Either open Mail at login (**System Settings → General → Login Items**) or accept that the email source will be skipped on early-morning runs and keep `required: false`.

### `osascript` is slow on a large mailbox

Add a `mailboxes` filter to scope the search to a specific folder rather than searching all mailboxes. The AppleScript query is faster when limited to a single mailbox.

## What This Source Does Not Do

The email source is intentionally narrow:

- it reads recent messages from Apple Mail on the local machine
- it filters by sender, mailbox, and subject; it does not do full-text search of message bodies
- it reads the first 400 characters of each message body; it does not parse full threads
- it does not read attachments
- it does not connect to your mail server directly
- it does not search across all email automatically from meeting names

For the config shape, see the summary in [`../setup-and-configuration-walkthrough.md`](../setup-and-configuration-walkthrough.md). For the full source guide index, go back to [`README.md`](README.md).
