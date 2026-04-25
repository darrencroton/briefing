# Human-Rated Summary Evaluation Set

**Target size:** 8–12 meetings  
**Purpose:** Regression harness for prompt changes and LLM provider swaps (§24.1)

---

## What Goes Here

One JSON entry per rated meeting in `eval-set.json`. Each entry is a human assessment of a generated summary against a hand-written reference. Entries are populated from the first real meetings after the Phase 5A soak begins.

---

## Rating Rubric

### Primary axes (§24.1)

Rate each on a **1–5 integer scale**:

| Axis | 1 | 3 | 5 |
|------|---|---|---|
| **Coverage** | Important decisions or discussion threads are absent | Most key points captured; minor gaps | All decisions, agreements, and significant discussion captured |
| **Correctness** | Invented facts, hallucinated attributions, or materially wrong claims | Mostly accurate; minor paraphrasing errors | Factually exact relative to the transcript; nothing invented |
| **Action-item recall** | Action items from the transcript are missing | Most actions present; some missed or vague | Every extractable action item (what + who + when) is present |

### Attribution accuracy (§24.2)

Measured per-session when speaker identity is known:

- **Attribution precision** — of names used in the summary, what fraction are correctly attributed?  
  *Target: ≥ 0.90*
- **Attribution recall** — of correctly-known attributions in the reference, what fraction appear in the summary?

If diarization was unavailable or produced `diarization_ok: false`, set both to `null` and note `"speaker_agnostic": true`.

### End-to-end latency (§24.3)

Time in seconds from `completion.json.completed_at` to the summary block appearing in the Obsidian note.  
*Target: ≤ 300 s for a one-hour meeting.*

---

## Regression Threshold

A prompt or model change must not reduce any axis by more than **1 rating point** on the average of this eval set.

Compute the per-change delta:
```
delta_axis = mean(new_scores[axis]) - mean(old_scores[axis])
```
Reject if any `delta_axis < -1.0`.

---

## Entry Schema

See `entry-template.json` for the canonical shape. Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `session_id` | string | from `completion.json` |
| `series_id` | string or null | |
| `rated_at` | ISO-8601 date | |
| `rater` | string | initials or name |
| `coverage` | int 1–5 | |
| `correctness` | int 1–5 | |
| `action_item_recall` | int 1–5 | |
| `attribution_precision` | float 0–1 or null | null when diarization unavailable |
| `attribution_recall` | float 0–1 or null | null when diarization unavailable |
| `speaker_agnostic` | bool | true when no diarization |
| `latency_seconds` | int or null | null if latency was not measured |
| `reference_summary` | string | hand-written reference (Markdown) |
| `generated_summary` | string | machine-generated text (Markdown) |
| `notes` | string | free-text observations, failure analysis |

---

## Storage Layout

```
docs/eval/
  README.md           — this file (rubric + instructions)
  entry-template.json — blank entry to copy when rating a new meeting
  eval-set.json       — array of rated entries; empty until first real meetings are rated
```

`eval-set.json` is the regression harness input. Do not rename it.
