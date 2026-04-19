# Email Source Discovery (Apple Mail)

This document proposes how to add an `email` source to `briefing` in a way that stays aligned with project constraints: local-first, explicit configuration, deterministic behavior, and blocking failures for required sources.

## User stories

1. **Series-specific pre-read capture**
   - As a user, I want a meeting series to pull relevant emails from the last _N_ days so that pre-meeting briefs include inbox context without manual copy/paste.

2. **Explicit and deterministic matching**
   - As a user, I want to configure clear matching rules (sender list, subject regex, mailbox scope, date window) so the same email set is selected every run.

3. **Stable behavior across title changes**
   - As a user, I want email retrieval tied to configured series rules and occurrence timing (not only event title text) so event renames do not break matching.

4. **Failure visibility for required sources**
   - As a user, I want `briefing validate` (and run-time checks) to fail clearly when email access is unavailable for a required series so I can fix setup before meetings.

5. **Portable output in Markdown**
   - As a user, I want email data normalized into concise Markdown bullets/snippets like other sources so prompt and note generation remain consistent.

6. **No accidental note overwrite**
   - As a user, I want email context to refresh only the managed summary block, never replacing my `Meeting Notes` or `Actions` sections.

## Design options

### Option A — AppleScript CLI adapter over Apple Mail (direct source)

Add `email` as a first-class source and use a small, deterministic AppleScript bridge to query Apple Mail by mailbox/date/sender/subject rules.

**How it works (high level)**
- New `email_source.py` implements the same source interface as Slack/Notion/file sources.
- Source invokes `osascript` with parameterized script(s) that query Apple Mail.
- Output is transformed into normalized source items (`subject`, `from`, `date`, short excerpt, stable message identifier).
- Validation checks automation permissions and mailbox/rule sanity.

**Pros**
- Strong local-first alignment.
- No external services or sync dependency.
- Can mirror current source architecture with minimal new abstractions.

**Cons / risks**
- AppleScript reliability and performance can vary with mailbox size.
- macOS automation permission handling needs clear diagnostics.
- Apple Mail scripting edge cases may require defensive parsing.

### Option B — Export-to-file bridge + existing `file` source (derived source)

Keep core unchanged and have a helper script export filtered Apple Mail messages to Markdown or JSON files; ingest using current file-source machinery.

**How it works (high level)**
- Add export script (`scripts/email/export_apple_mail.sh` + AppleScript) that writes deterministic files under a configured path.
- Reuse `file` source in series config to include exported material.
- Optional launchd step refreshes exports before briefing run.

**Pros**
- Maximum DRY reuse of existing `file` source path.
- Lowest core-code risk in orchestration layer.
- Easy debugging (intermediate artifacts visible on disk).

**Cons / risks**
- Two-step workflow (export then run) can drift if automation fails.
- Weaker first-class validation unless export health is integrated.
- Slightly less ergonomic for users vs direct `email` source.

### Option C — Hybrid: first-class `email` source with shared retrieval adapter

Implement a first-class `email` source, but structure retrieval through a reusable adapter that can also optionally dump debug artifacts (like Option B) when enabled.

**How it works (high level)**
- `email_source.py` calls `mail_adapter.py`.
- Adapter exposes `fetch_messages(config) -> list[EmailMessage]`.
- Optional `debug_export_path` writes retrieved normalized messages for traceability.

**Pros**
- Better long-term maintainability than ad-hoc scripting.
- Keeps UX consistent with other sources.
- Preserves local debugging advantages.

**Cons / risks**
- More implementation work now than Option A/B.
- Requires discipline to avoid over-abstraction.

## Evaluation rubric

Score each criterion from **1 (poor) to 5 (excellent)**. Suggested weights prioritize reliability.

| Criterion | Weight | What “good” looks like |
|---|---:|---|
| Robustness in unattended runs | 30% | Works predictably across repeated runs, with clear errors on permission or query failures. |
| Implementation complexity | 20% | Minimal moving parts, small coherent CLI/config surface, low cognitive overhead. |
| DRY reuse with existing source architecture | 15% | Reuses existing source types, validation patterns, and rendering paths without duplication. |
| KISS fit | 15% | Straight-line design; avoids speculative abstractions and hidden state. |
| Validation and diagnosability | 10% | `validate` can catch setup issues; failures are explicit/actionable. |
| User ergonomics | 10% | Easy per-series config and predictable day-to-day behavior. |

### Sample scoring (initial)

| Option | Robustness (30) | Complexity (20) | DRY (15) | KISS (15) | Diagnostics (10) | Ergonomics (10) | Weighted total |
|---|---:|---:|---:|---:|---:|---:|---:|
| A: Direct AppleScript source | 4 | 3 | 4 | 4 | 4 | 4 | **3.8 / 5** |
| B: Export + file source | 3 | 4 | 5 | 5 | 3 | 3 | **3.85 / 5** |
| C: Hybrid adapter + source | 5 | 2 | 4 | 3 | 5 | 5 | **4.1 / 5** |

## Recommendation

For immediate delivery with KISS+DRY priorities, start with **Option A** and explicitly limit scope:

- only Apple Mail,
- explicit rules only (mailbox, sender, subject regex, date window),
- deterministic sorting and capped excerpts,
- required-source failures are blocking,
- no background daemon or cache in v1.

Then add one **targeted** enhancement from Option C later if needed: a small shared retrieval adapter that can optionally write debug artifacts. This keeps v1 simple while avoiding a dead-end design.

## Proposed v1 config shape (example)

```yaml
sources:
  - type: email
    name: team_updates
    required: true
    config:
      account: "iCloud"
      mailboxes: ["Inbox", "Team"]
      lookback_days: 7
      from_any: ["manager@example.com", "eng-leads@example.com"]
      subject_regex_any: ["weekly update", "roadmap", "incident"]
      max_messages: 20
      max_excerpt_chars: 280
```

Notes:
- Keep matching explicit; no fuzzy title-only inference.
- Keep output Markdown-portable, same as other sources.
- Keep provider-specific details inside source implementation, not runner logic.
