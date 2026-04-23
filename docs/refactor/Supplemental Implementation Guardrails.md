# Supplemental Implementation Guardrails

## Meeting Intelligence System (`briefing` + `noted`)

**Version:** 2.0
**Relationship to master plan:** This document restates the non-negotiable invariants from the *Meeting Intelligence System — Master Implementation Plan* in a short, scannable form. It is **derivative**, not independent. In any conflict, the master plan is authoritative.

-----

## Purpose

This document captures a small set of **non-negotiable implementation truths**.

These are not design suggestions or future improvements. They are **guardrails** to ensure the system that gets built matches the architecture that was designed.

If these are violated, the system will:

- behave incorrectly in real-world usage, or
- drift architecturally and become difficult to maintain

-----

# 1. Stop Must Be Fast and Non-Blocking

## Rule

`noted stop` must:

- stop audio capture immediately
- flush and persist raw audio
- return promptly

It must **NOT**:

- wait for ASR
- wait for diarization
- wait for transcript generation

## Required Behaviour

After stop:

- session transitions to `processing`
- ASR + diarization run in background
- `completion.json` is only written once processing finishes

## Why This Matters

Back-to-back meetings depend on this.

If stop blocks:

- next meeting starts late
- user experience breaks
- system becomes unusable in realistic schedules

-----

# 2. There Is Exactly One Manifest Schema

## Rule

There is **one and only one** session manifest schema.

This applies to:

- calendar-driven sessions
- ad hoc/manual sessions

## Required Behaviour

- Ad hoc sessions must be normalised into a **full manifest**
- All required fields must exist (with defaults if necessary)
- No “lightweight” or alternate schema is allowed

## Why This Matters

Multiple schema shapes will cause:

- branching logic
- inconsistent behaviour
- debugging complexity

This must be avoided from day one.

-----

# 3. `completion.json` Is the Source of Truth

## Rule

`completion.json` is the **only authoritative record of session outcome**.

## Required Behaviour

`briefing` must:

- read `completion.json` first
- base all decisions on it

`briefing` must NOT:

- infer success from file presence
- parse logs to determine outcome
- guess based on partial outputs

## Why This Matters

This file defines the contract between:

- capture (`noted`)
- orchestration (`briefing`)

If this contract is weak or bypassed:

- behaviour becomes non-deterministic
- failure handling becomes unreliable

-----

# 4. `noted` Must Remain Dumb (by Design)

## Rule

`noted` must not evolve into a second orchestration layer.

## `noted` MUST NOT:

- parse calendar events
- determine meeting eligibility
- infer next meetings
- run LLM summaries
- write notes
- interpret meeting context

## `noted` IS ALLOWED TO:

- execute a session from a manifest
- launch sessions from manifests (including pre-prepared next-meeting manifests)
- construct its own manifest for ad hoc sessions from local defaults
- manage runtime state
- handle UI and user interaction
- record and transcribe

## Why This Matters

The system is explicitly designed with:

- **one brain (`briefing`)**
- **one runtime agent (`noted`)**

If `noted` becomes “smart”:

- logic duplicates
- behaviour diverges
- bugs become subtle and hard to trace

-----

# 5. All Time Handling Must Be Explicit and Timezone-Aware

## Rule

All timestamps must be:

- ISO-8601 formatted
- include timezone offsets

## Required Behaviour

- No naive timestamps
- No reliance on system local time
- No implicit conversions

## Why This Matters

Calendar-driven systems fail silently when time is ambiguous:

- DST changes
- timezone mismatches
- remote participants

These bugs are extremely difficult to debug later.

-----

# 6. Pre-Roll Is Required (Not Optional)

## Rule

Recording must begin **before** the scheduled start time.

## Required Behaviour

- `briefing` schedules start with a buffer (default 90 seconds, configurable 60–180)
- `noted` starts recording before official start time
- the recording-start bell sounds at actual capture start, not at pre-roll start
- system tolerates early idle recording

## Why This Matters

Without pre-roll:

- first seconds of meetings are routinely lost
- system feels unreliable
- user trust degrades quickly

-----

# 7. Speaker Names Are Hints, Not Truth

## Rule

Participant names must be treated as **soft hints only**.

## Required Behaviour

- host may be identified explicitly
- other participants only named when confidence is high
- default to speaker-agnostic phrasing when uncertain

## Must NOT:

- force name assignment onto speakers
- assume diarization is correct
- fabricate attribution

## Why This Matters

Incorrect attribution is worse than no attribution.

This directly impacts:

- user trust
- perceived accuracy
- usefulness of summaries

-----

# 8. Next-Meeting Logic Lives Only in `briefing`

## Rule

`noted` must not determine or compute next meetings.

## Required Behaviour

- `briefing` decides next meeting eligibility
- `briefing` prepares next manifest in advance
- `briefing watch` keeps pre-prepared manifests current with the calendar (deletes on cancellation, rewrites on reschedule)
- `noted` only:
  - reads `next_meeting` from the current manifest
  - displays the option in the popup
  - launches the pre-prepared next manifest when the user signals

## Why This Matters

Calendar interpretation is:

- complex
- policy-driven
- evolving

It must remain centralised.

-----

# 9. Runtime State Must Be Persisted

## Rule

All session state must be externally observable.

## Required Behaviour

`noted` must maintain:

- `runtime/status.json`
- logs
- final `completion.json`

## Why This Matters

This enables:

- debugging
- recovery
- inspection after failure
- integration with `briefing`

Without this:

- failures become opaque
- system becomes brittle

-----

# 10. Raw Audio Is the Primary Asset

## Rule

Raw audio must be preserved whenever capture succeeds.

## Required Behaviour

- store raw audio before processing
- do not delete on failure
- allow future reprocessing via `briefing session-reprocess`

## Why This Matters

ASR and diarization will improve over time.

Audio is the only irrecoverable input.

-----

# 11. Only `briefing` Writes Manifests From Calendar Data

## Rule

`briefing` is the **only** component allowed to turn calendar events into manifests.

## Required Behaviour

`briefing` writes:

- the current session’s manifest
- the next session’s manifest, in advance, at the same time

Manifest contents for series-matched events are composed by `briefing` from three legitimate input sources, resolved by the precedence rule in master plan §7.3: calendar-note values (under a `noted config` marker) override series YAML defaults, which override `briefing` global defaults. Series YAML is the **primary default source** for a recorded series — a user who wants a series recorded sets that once in the series YAML and does not touch calendar notes thereafter. Calendar notes exist for per-instance overrides and for one-off events not covered by a series.

`noted` only writes a manifest in one case: ad hoc sessions with no calendar backing, using its own local settings as the source of defaults.

## `noted` MUST NOT:

- read the calendar
- write a manifest derived from calendar data
- modify a manifest that `briefing` wrote
- synthesise a next-meeting manifest from partial information

## Why This Matters

There is a natural temptation, especially at handoff time, for `noted` to “just quickly” compose the next manifest itself to save a round-trip. That is exactly how calendar interpretation logic duplicates and drifts.

The division is:

- **Manifest *contents* come from `briefing`** (composed from calendar data, series YAML, and global defaults) or from local defaults (ad hoc).
- **Manifest *execution* is `noted`’s job.**

Keep these separate and the system stays deterministic. Blur them and you end up with two calendar clients.

-----

# 12. Managed Blocks Never Touch User-Owned Content

## Rule

The Obsidian meeting note has **managed blocks** (owned by `briefing`, rewritten idempotently) and a **user section** (owned by the user, never touched).

## Required Behaviour

`briefing` may:

- create the note from the template if it does not exist
- insert or replace the `## Briefing` managed block
- insert or replace the managed summary block
- preserve everything else verbatim

`briefing` must NOT:

- merge new content into an existing managed block (always full replace)
- touch content outside managed-block delimiters
- resolve conflicts by guessing
- silently overwrite the whole note

Managed-block boundaries must be machine-detectable (comment markers or explicit heading) so that regeneration is safe.

## Why This Matters

This is the most load-bearing invariant in the Obsidian contract.

A subtle bug here — a greedy regex, a slip in delimiter detection, a merge where there should have been a replace — silently eats user notes that are not stored anywhere else. The user may not notice for days or weeks.

Every change to the note-writing code path should be reviewed against this rule specifically. Every test harness should include a note with rich user content in the user section and assert that content is byte-identical after rewrites.

Managed content is replaceable. User content is not.

-----

# Final Principle

> The system is designed to be:
> 
> - deterministic
> - inspectable
> - composable
> - robust to failure

Every implementation decision should be evaluated against these goals.

-----

## If Unsure

When facing ambiguity, default to:

1. **Does this introduce a second source of truth? → Avoid it**
2. **Does this duplicate logic across components? → Avoid it**
3. **Does this make behaviour harder to inspect/debug? → Avoid it**
4. **Does this block real-time workflow? → Avoid it**