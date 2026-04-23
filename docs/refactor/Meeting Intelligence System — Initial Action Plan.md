# Meeting Intelligence System — Initial Action Plan

**Audience:** You, as director of the project, managing a dev team.
**Purpose:** Take you from “master plan exists, no code touched yet” to “both repos scaffolded, contracts locked, first vertical slice in progress” — without painting yourself into any architectural corners.
**How to use:** Work through the steps in order. Each step tells you *why it matters*, *what you’re directing*, *what “done” looks like*, *pitfalls*, and *questions to ask the dev team* so you can run reviews credibly. Do not skip ahead — several steps depend on earlier ones being properly closed out.

-----

## Is this a good idea?

Short answer: **yes, with two caveats**.

The master plan is unusually strong for an early-stage project. The guardrails are explicit, the open questions are mostly decided, the two-component split is architecturally correct (for the lifecycle reasons §5.1.1 gives), and the invariants are specific enough that a dev team can’t accidentally drift without someone noticing. Most plans at this stage are vaguer.

The two caveats:

1. **The plan is enterprise-grade for what is, today, a personal-scale tool.** That’s not a reason to scale it back — rigour early is cheaper than retrofitting later — but be aware you’re signing up for real engineering discipline. The contracts repo (below) is the concrete manifestation of that. Cut it and the rest of the plan starts decaying within weeks.
2. **There’s one silent architectural decision that needs making before anyone writes code.** HushScribe is Swift end-to-end, but the master plan names Python ASR libraries (`faster-whisper`, `whisperx`). That conflict has to be resolved deliberately, not by whoever opens the first pull request. Step 2 below handles it.

Neither caveat is a reason to stop. They’re reasons to do Steps 1–3 properly before Step 4.

-----

## The sequence at a glance

|#|Step                                           |Owner                       |Blocking        |
|-|-----------------------------------------------|----------------------------|----------------|
|1|Audit HushScribe’s modules (keep/strip/rewrite)|Dev team, you review        |Step 4          |
|2|Resolve Swift-vs-Python ASR decision           |You decide, dev team advises|Steps 3, 4      |
|3|Create contracts repo; lock Phase 1 contracts  |Dev team, you sign off      |Steps 4, 5, 6   |
|4|Fork HushScribe → `noted`; strip               |Dev team                    |Step 5          |
|5|Build shared test fixtures in contracts repo   |Dev team                    |Step 6, 7       |
|6|Write the two component sub-plans              |You + me, dev team reviews  |Step 7          |
|7|First vertical slice end-to-end                |Dev team                    |Everything after|

Estimated calendar time to reach end of Step 7, assuming a part-time dev: **3–5 weeks**. The bulk of that is Step 4 (the strip) and Step 7 (first slice). Steps 1, 2, 3 should take a week combined if done properly.

-----

## Structural recommendations for the repos — read this before Step 1

You flagged that getting the structural setup right is as important as anything else. Agreed. Here is what “right” looks like.

### Three repos, not two

You end up with three Git repositories, even though the plan talks about two components:

1. **`briefing`** — the existing Python orchestration app. Stays where it is: `github.com/darrencroton/briefing`.
2. **`noted`** — the new Swift menubar app, forked from HushScribe then stripped.
3. **`meeting-intelligence-contracts`** — a small, neutral repo that owns the manifest schema, completion.json schema, runtime status schema, CLI contract, and shared test fixtures.

The contracts repo is the single most important structural decision in this whole project. Without it, you have two independent codebases implementing the same handoff interface, and nothing forces them to stay aligned. With it, any change to the handoff interface has to be made in one place, versioned, and picked up by both sides deliberately. That is exactly the discipline the master plan’s invariants demand.

The contracts repo should contain, and nothing else:

- JSON Schema files: `manifest.v1.json`, `completion.v1.json`, `runtime-status.v1.json`.
- Markdown contracts: `cli-contract.md` (noted’s CLI surface), `session-directory.md` (on-disk layout), `versioning-policy.md`.
- Test fixtures: example valid/invalid manifests, example completion files for each terminal status, a tiny WAV for capture smoke tests.
- A `CHANGELOG.md` and semver-tagged releases.

Both `briefing` and `noted` consume it. How they consume it is a dev decision — git submodule, a `curl` script in CI that pins a tag, a copied folder with a CI check that detects drift. My preference is **pinned tag via a simple fetch script**, because submodules are fiddly and copying-with-CI-check works fine. But let the dev team pick.

### Why three repos, not a monorepo

A monorepo would centralise contracts naturally. But it would also:

- Blur the “these are two independent components that happen to work together” discipline that guardrail #4 depends on.
- Make it harder to fork HushScribe cleanly (HushScribe’s history becomes entangled with `briefing`’s).
- Make versioning, CI, and deploys more complex than a single-user project needs.

Three small repos with one shared dependency is the cleanest shape for this problem.

### The non-negotiables for all three repos

Before the dev team touches any of them:

- **Default branch `main`**, no exceptions.
- **Protected `main`** on all three: no direct pushes, PR required, at least one review (from you, for the first month).
- **Conventional commits** or similar — commit messages should be parseable by tooling. The dev team will thank you when they need to auto-generate a changelog.
- **Semver-tagged releases** on all three. Contracts repo starts at `v1.0.0` the moment Step 3 closes. `noted` and `briefing` can stay pre-1.0 for a while.
- **An `ARCHITECTURE.md` at the top level** of `noted` and `briefing`, describing what that component does and, critically, what it **does not do**. Restate the guardrails from the supplemental doc. Link to the contracts repo. This is the document that prevents scope creep six months from now when someone new joins and thinks “why doesn’t noted just read the calendar?”

### Licence and attribution

HushScribe is MIT, which itself is forked from Tome, which is forked from OpenGranola. When you fork:

- **Keep the MIT licence file in `noted` verbatim.** Do not replace it with yours.
- **Preserve the “Credits” section in the README** naming HushScribe, Tome, and OpenGranola, plus the upstream model/library credits (FluidAudio, WhisperKit, MLX). Add a line at the top stating `noted` is a fork of HushScribe.
- You can add your own copyright line above the existing ones. You cannot remove them.

This is both legally required and professionally correct. The dev team should not need reminding, but it’s worth being the one who asks “did we preserve attribution?” at PR review.

### Bundle identifier and coexistence

`noted` will run on your Mac alongside HushScribe during development. If the dev team reuses HushScribe’s bundle identifier (something like `app.hushscribe.HushScribe`), the two apps will clobber each other’s preferences and confuse macOS’s TCC (privacy) database. They must:

- Change the bundle identifier to something like `app.noted.Noted` (or a reverse-domain form you control).
- Change the app name everywhere it appears in `Info.plist`.
- Pick a distinct menubar icon early, even if it’s a placeholder — just so the two apps are visually distinguishable in the menubar during dev.

A side effect of changing the bundle identifier: macOS will re-prompt for microphone and screen-recording permission the first time `noted` runs. That’s correct and expected — it gives you a clean TCC slate. Just don’t be surprised when it happens.

-----

## Step 1 — Audit HushScribe’s modules

### Why this matters

Before the dev team strips anything, they need to know precisely what HushScribe contains and what depends on what. The public README and ARCHITECTURE.md are useful but not load-bearing — the truth is in the source tree. Audio capture is deeply wired into macOS frameworks (AVAudioEngine, ScreenCaptureKit), and it is genuinely easy to accidentally delete a protocol that the capture pipeline silently depends on. One hour of auditing saves a day of “why does capture not work any more.”

### What you’re directing

Ask the dev team to clone HushScribe, open it in Xcode, and produce a single document — a **triage table** — that lists every file in `HushScribe/Sources/HushScribe/` and assigns each one to one of three buckets:

- **KEEP** — stays essentially as-is in `noted` (possibly with imports renamed).
- **STRIP** — delete outright.
- **REWRITE** — the responsibility stays but the implementation needs substantial change.

For each file, a one-line justification.

I’ve drafted a starting point in the appendix of this document. Have the dev team refine it against the actual source — my version is inferred from the architecture doc, not read from the code. Their version is the one that matters.

### What “done” looks like

A triage table committed to the `noted` repo as `docs/hushscribe-triage.md` (before any stripping). Every source file appears in the table. The team can articulate why each STRIP file is safe to remove without breaking a KEEP file.

### Pitfalls

- **Don’t strip based on file names alone.** `SummaryService.swift` sounds obviously strippable, but if `TranscriptionEngine.swift` imports it somewhere, the strip will fail the build. Verify by actually searching for references.
- **Watch for shared types.** `Models/Models.swift` probably contains types used by both the strippable summariser and the keepable transcription engine. The audit should identify these.
- **Test targets matter.** If HushScribe has tests that cover summarisation, those tests strip out with the summariser. That’s fine — just note it so the dev team isn’t surprised when test count drops.

### Questions to ask at review

- “Walk me through why `X.swift` is in the STRIP bucket. What else references it?”
- “What’s the smallest change that would let us build a stripped version that still runs?”
- “Are there any files you’re unsure about? Those are the interesting ones.”

-----

## Step 2 — Resolve Swift-vs-Python ASR decision

### Why this matters

The master plan §15.2 defaults ASR to `faster-whisper` and §27.9 decided on `whisperx` — both Python. HushScribe uses WhisperKit (Swift-native, Apple Silicon-optimised) and FluidAudio’s Parakeet-TDT v3 (also Swift-native). These are incompatible defaults.

If `noted` stays all-Swift, you throw away HushScribe’s working ASR + diarization pipeline — which is the main asset you’re forking the repo for. If `noted` becomes a Swift menubar UI that shells out to a Python ASR worker, you add process-boundary complexity for no clear benefit.

Almost certainly the correct answer is to update the master plan to name the Swift-native stack. But this is an architectural decision, and it should be made deliberately, in writing, before Step 3 locks contracts that depend on it.

### What you’re directing

Ask the dev team to produce a short written recommendation — one page — covering:

- What HushScribe’s current ASR/diarization stack gives you out of the box.
- Any concrete reason to prefer Python (`whisperx`/`pyannote.audio`) over Swift (`WhisperKit`/`FluidAudio`). Quality? Language support? Maintenance?
- What changes to master plan §15 and §27.9 would be needed to adopt the Swift stack.
- Whether the manifest’s `transcription.asr_backend` field changes from `"faster-whisper"` to `"whisperkit"` (or a similar name) in schema v1.0.

Then you make the decision. Edit the master plan in-place — add a dated decision note under §27.9 saying what changed and why. This amendment travels with the master plan document thereafter.

### What “done” looks like

- Master plan §15.2 and §27.9 updated with the chosen backend.
- Manifest schema draft (which will be locked in Step 3) uses the correct `asr_backend` value.
- The triage table from Step 1 is re-confirmed — nothing that’s being kept relies on a Python assumption.

### Pitfalls

- **Don’t let this become a quality debate.** The question is “does HushScribe’s existing stack meet the quality floor?” not “what’s the theoretical best diarizer?” Perfect is the enemy of shipped here.
- **Don’t pick a hybrid accidentally.** “Keep Swift for ASR, use Python for diarization” is a legitimate option but adds complexity. It should only be chosen if there’s a concrete quality reason the Swift diarizer (FluidAudio’s `OfflineDiarizerManager`) can’t clear the bar.

### Questions to ask at review

- “If we keep the Swift stack, what do we lose relative to the Python stack the master plan named?”
- “If we switch to the Python stack, how much of HushScribe are we actually keeping? Is this still a fork, or a new project?”
- “Does the choice affect what permissions `noted` needs to request on first run?”

-----

## Step 3 — Create the contracts repo and lock Phase 1 contracts

### Why this matters

Phase 1 of the master plan is “Lock Contracts”, and the plan is explicit that this must close before Phase 2 begins. In practice that means: before anyone writes `noted` code that produces or consumes a manifest or completion file, those formats must be frozen in a neutral location that both repos reference.

This is also the most deferrable-feeling step, which is precisely why it’s the one most likely to get skipped under time pressure. Skip it and you get contract drift within a month. Do it properly and you buy a lot of calm for the rest of the project.

### What you’re directing

Create the repo and populate it. The dev team does the scaffolding; you review every artefact personally before it’s tagged.

The initial contents, derived directly from the master plan:

- `schemas/manifest.v1.json` — JSON Schema for §8 manifest, all fields with types and constraints.
- `schemas/completion.v1.json` — JSON Schema for §11.3 completion file.
- `schemas/runtime-status.v1.json` — JSON Schema for §10.3 runtime status file.
- `cli-contract.md` — `noted`’s CLI surface from §9. Commands, exit codes, stdout JSON shapes. Explicit examples.
- `session-directory.md` — the on-disk layout from §11.1, and the file-requirements table from §11.2.
- `vocabulary.md` — the locked vocabulary from §26 (stop reasons, terminal statuses, transcript filenames, timezone handling).
- `versioning-policy.md` — how schema versions evolve (§8.4), how breaking changes are handled, who authorises them.
- `fixtures/` — empty for now, filled in Step 5.
- `README.md` — what this repo is, how to consume it, how to propose changes.
- `CHANGELOG.md` — starting at `v1.0.0`.

Tag `v1.0.0` the moment all of the above is reviewed and merged. Do not commit contracts with schema_version 1.0 that are not tagged — the tag is the thing that makes “schema v1.0” a real, immutable reference.

### What “done” looks like

- Contracts repo exists, all files above present and merged to `main`.
- Tagged `v1.0.0`.
- Both `briefing` and `noted` repos have an agreed mechanism to consume the contracts (submodule, pinned-tag fetch, or similar).
- A change-proposal process is written down in the contracts repo’s `README.md`: what triggers a minor version bump, what triggers a major version bump, who approves.

### Pitfalls

- **The master plan already has open questions that affect schemas.** §27.4 (summary block placement) is decided — option (b), append after `## Meeting Notes` — but the decision lives in the plan, not in the schemas. Make sure every decided §27 item is reflected in the contracts. Anything not yet decided is a blocker for locking — flag it and resolve it before tagging.
- **Don’t over-specify.** The contracts are about the handoff interface. They are not the place to spell out *how* `noted` implements capture or *how* `briefing` implements summarisation. Keep them minimal; that’s their power.
- **Version from day one.** Every schema file includes `schema_version: "1.0"`. Every completion file, every manifest, will carry a version. Enforce this in the schemas themselves.

### Questions to ask at review

- “If someone in six months wants to add a new field to the manifest, what exactly do they do? Walk me through the process.”
- “Can `noted` and `briefing` be built and tested independently against these schemas, with no shared code?”
- “What happens if `noted` produces a completion file with `schema_version: 1.1` and `briefing` only understands 1.0?”

-----

## Step 4 — Fork HushScribe → `noted`, then strip

### Why this matters

This is the biggest single chunk of work in the early phase, and the point where the project visibly becomes real. The goal is to end up with a repo that builds, runs as a menubar app, captures audio, transcribes and diarizes — and nothing else. No summariser. No transcript viewer. No meeting-app auto-detection. The CLI, manifest loader, session directory writer, and end-of-meeting popup come in later phases; this step just gets you to a clean, buildable starting point.

### What you’re directing

**First, how to fork.** Two options:

- **(a) Fresh repo, squashed import.** Create an empty `noted` repo. Add HushScribe as a single initial commit (squashed from HushScribe’s full history). Clean history, clean mental model, preserves attribution in README and LICENSE. **Recommended.**
- **(b) GitHub fork + strip branch.** Keeps HushScribe’s full commit history. Slightly muddier ownership narrative — tools looking at the repo will still call it “forked from HushScribe” even a year later. Not wrong, just less clean.

I recommend (a). Tell the dev team which.

**Second, what to strip.** The triage table from Step 1 is the authoritative list. Broadly, from the HushScribe module structure:

- **STRIP** — `Services/LLMSummaryEngine.swift`, `Services/SummaryService.swift`, `Services/MeetingMonitor.swift`, `Models/SummaryModel.swift`, `Views/SummarizeView.swift`, the entire AI summary UI surface, MLX dependency, Qwen3/Gemma 3 model-download logic.
- **KEEP (mostly as-is)** — `Audio/*`, `Transcription/*`, `Models/Models.swift`, `Models/RecordingState.swift`, `Storage/SessionStore.swift` (with edits).
- **REWRITE** — `Storage/TranscriptLogger.swift` (output format changes from single .md to session-directory layout), `Settings/AppSettings.swift` (migrate from UserDefaults to the TOML file in §20.4), `Views/ContentView.swift` and the other view files (replace the main window with a menubar menu and a minimal popup — this is the big one).
- **NEW (to add in later phases, not this step)** — CLI entry point, manifest loader/validator, session directory writer, runtime status file writer, completion file writer, end-of-meeting popup.

**Third, the repo hygiene.**

- Bundle identifier changed per the “Bundle identifier and coexistence” section above.
- App name changed everywhere.
- README rewritten — short, accurate, states what `noted` is and what it is *not* (cite the guardrails). Keeps the credits to HushScribe/Tome/OpenGranola.
- `ARCHITECTURE.md` rewritten to describe the stripped shape, not HushScribe’s.
- Homebrew cask files (`Casks/`) removed — `noted` isn’t distributed via Homebrew yet and won’t be for a while.
- Assets (logo, screenshots) replaced or removed. A placeholder logo is fine.
- Dependencies pruned — `mlx-swift-lm` in particular comes out once `LLMSummaryEngine` is gone.

### What “done” looks like

- `noted` repo exists, builds clean in Xcode 26.3+ on Apple Silicon with macOS 26+.
- Launching the app produces a menubar icon and nothing else (no main window).
- Starting a recording from the menubar (even via the HushScribe-inherited UI, for now) captures audio to disk, runs ASR, runs diarization, and writes output somewhere — proving the kept pipeline still works.
- `ARCHITECTURE.md` describes the current (stripped) shape and explicitly lists what’s coming in later phases.
- Licence and attribution preserved correctly.

### Pitfalls

- **Scope creep into Phase 2 work.** It is tempting, while “in the area”, to add the CLI or the manifest loader now. Resist this. Step 4 is the strip only. New capabilities come next.
- **Silent macOS version lock-in.** HushScribe requires macOS 26+ and Apple Silicon. Confirm this is acceptable for your target deployment (your Mac is almost certainly fine; the dev team’s may or may not be). If you need broader support, that’s a different conversation with different implications.
- **TCC permissions.** Because the bundle ID changes, first launch will re-prompt for mic and screen recording. The dev team should document this in the README — first-run instructions will be non-trivial for a while.
- **Don’t delete the Homebrew cask files and then realise you wanted them later.** They’re small; they can always come back. But remove them from the default state.

### Questions to ask at review

- “Show me the app launching. What do I see? What do I not see?”
- “If I hit Record from the (inherited) HushScribe UI, does the full capture + transcribe + diarize pipeline still work? Let’s prove it.”
- “What’s still imported that we don’t actually need? Walk me through the Package.swift.”
- “Show me the LICENSE file and the README’s credits section.”

-----

## Step 5 — Build shared test fixtures

### Why this matters

Two independent repos implementing a contract need to test their half of that contract without requiring the other half to exist. If `noted`’s tests can only run when a real `briefing` is installed, you have a coupling problem. The cure is fixture files — canonical example manifests and completion files — that both repos consume from the contracts repo.

This is also cheap. An afternoon’s work now saves days of integration-test pain later.

### What you’re directing

Fill out the `fixtures/` folder in the contracts repo with:

- **`fixtures/manifests/valid-inperson.json`** — a fully-populated calendar-driven manifest.
- **`fixtures/manifests/valid-adhoc.json`** — an ad hoc manifest with nulls where §20.1 permits.
- **`fixtures/manifests/valid-with-next-meeting.json`** — one with `next_meeting.exists: true` and a `manifest_path`.
- **`fixtures/manifests/invalid-missing-required.json`** — for validation negative tests.
- **`fixtures/manifests/invalid-bad-timezone.json`** — naive timestamp, to assert the guardrail.
- **`fixtures/completions/completed.json`** — happy path.
- **`fixtures/completions/completed-with-warnings.json`** — diarization failed, transcript OK.
- **`fixtures/completions/failed-startup.json`** — capture never started.
- **`fixtures/completions/failed-capture.json`** — capture started, failed mid-session.
- **`fixtures/audio/smoke-30s.wav`** — a 30-second WAV (generated, not a real meeting) for capture-replacement tests.

Both `briefing` and `noted` add test suites that load these fixtures from the pinned contracts version and verify their own contract compliance. `noted`’s `validate-manifest` command, once it exists, should be run against every manifest fixture as part of its CI.

### What “done” looks like

- All fixture files above present in the contracts repo at the `v1.0.0` tag (or bumped to `v1.0.1` if Step 3 already tagged).
- Both repos have at least one test that loads a fixture and asserts something meaningful about it.
- A `fixtures/README.md` explains what each fixture is for.

### Pitfalls

- **Don’t let fixtures be the spec.** The JSON Schemas are the spec. Fixtures are examples. If a fixture disagrees with the schema, the schema wins and the fixture is fixed.
- **Name fixtures for what they test, not what they look like.** `invalid-missing-required.json` is useful; `manifest3.json` is useless.

### Questions to ask at review

- “If I change the manifest schema tomorrow, how do I know which fixtures need updating?”
- “What’s the smallest fixture that would catch a regression where someone forgets to add `schema_version`?”

-----

## Step 6 — Write the two component sub-plans

### Why this matters

The master plan is system-level. The dev team needs component-level plans — one for `noted`, one for `briefing` — that translate the master plan’s phases into concrete engineering tickets. This is where “Phase 2: Minimal `noted` Runtime” becomes “issues #1 through #14 in the `noted` repo, estimated at so-many days, with acceptance criteria that reference the contracts.”

Doing this *after* Steps 1–5 means the sub-plans can reference real things: the stripped `noted` repo, the locked contracts, the triage table, the fixtures. Doing it before would mean writing plans against moving targets.

### What you’re directing

You and I draft these together — this is where my earlier offer to help applies. We produce:

- **`noted` implementation plan** — tracks master plan phases 2 through 5 for the `noted` side. Phase 2 is the first real work (CLI, manifest loader, session directory writer). Lives in `noted/docs/implementation-plan.md`.
- **`briefing` extension plan** — tracks master plan phase 4 (ingestion and summarisation) plus the §18.2 additions (new source adapter, new prompt template, new subcommands, series YAML extensions, `briefing watch` invalidation sweep). Lives in `briefing/docs/implementation-plan.md`.

Each plan contains, per phase:

- Concrete acceptance criteria (tied to contracts where possible).
- A rough breakdown of issues/tickets.
- Dependencies on the other component (e.g. “Phase 4 of `briefing` blocks on Phase 3 of `noted`”).
- Any remaining open questions that this component’s implementation needs resolved.

The dev team reviews both plans, pushes back on anything unworkable, and then uses them as the basis for GitHub issues.

### What “done” looks like

- Both sub-plans merged to their respective repos.
- A cross-repo dependency map — which phase in one blocks which phase in the other — is legible at a glance. A simple Gantt-like Markdown table is fine.
- The dev team has enough detail to start cutting issues for Step 7 (the first vertical slice).

### Pitfalls

- **Don’t estimate in hours.** Estimate in “days of focused work.” Hours-level estimation is false precision this early.
- **Don’t plan Phase 5 (polish, retention, online mode) in detail yet.** That’s months away and the plan will have changed by then. Plan Phases 2 and 4 in detail, Phase 3 in medium detail, Phase 5 in broad strokes only.

### Questions to ask at review

- “Which tickets could the dev team start tomorrow without waiting on anyone?”
- “Which phase would hurt the most if we got wrong?”
- “What assumptions are we making that could turn out to be false? What’s the cheapest way to find out?”

-----

## Step 7 — First vertical slice, end to end

### Why this matters

You now have: stripped `noted`, extended `briefing`, locked contracts, and written plans. What you don’t have is proof that any of them actually talk to each other. A vertical slice proves the whole pipeline works, even if every individual stage is shallow. It’s the single most important confidence-builder on the project, and the earliest point at which you find out if the contracts are actually right.

### What you’re directing

The slice: **a hand-written manifest on disk → `noted start --manifest <path>` → 30-second audio capture → `noted stop` → `completion.json` appears → `briefing session-ingest` reads it and writes a stub summary block to an Obsidian note.**

Deliberately excluded from this slice:

- No calendar integration. The manifest is hand-written for this test.
- No LLM call. `briefing session-ingest` writes a placeholder summary like `[summary will go here]` — just enough to prove the note-writing path.
- No diarization required. ASR is enough — diarization is orthogonal and can be added next.
- No menubar popup. The session runs to completion because the 30-second manifest sets a scheduled end time 30 seconds in the future.
- No `briefing watch`. `briefing session-ingest` is invoked manually for this test.

What this slice proves:

- Manifest validation works (tested by intentionally breaking the manifest and verifying `validate-manifest` rejects it).
- Session directory is created correctly (every file the plan §11.2 requires is present).
- Audio capture actually writes a file to disk.
- ASR runs.
- `completion.json` is produced with the right shape, readable against the schema.
- `briefing session-ingest` can find and parse it.
- The managed summary block is inserted into the Obsidian note at the correct position (end of note, per §27.4 decision (b)), preserving user content.

If any of these fail, you’ve found a real bug — either in code or in the contract — and it’s cheap to fix now.

### What “done” looks like

- The slice runs end-to-end, reproducibly, on your MacBook Pro.
- A short script (zsh) in one of the repos automates the whole run for regression purposes.
- A written post-mortem — even one paragraph — notes what turned out harder or easier than expected. This feeds the sub-plans’ estimates going forward.

### Pitfalls

- **Scope creep.** “While we’re here, let’s just add the calendar bit” is how a 3-day slice becomes a 3-week rabbit hole. If it’s not in the list above, it’s in the *next* slice.
- **Testing with a real meeting.** Use a 30-second audio clip played from your phone or a test fixture — not a real conversation. Real meetings are noisy in ways that will distract from whether the pipeline works.
- **Don’t ship this as “done.”** This is infrastructure. Users (you) still get nothing useful. But it’s the infrastructure that everything else plugs into.

### Questions to ask at review

- “Show me the run. End to end. Don’t explain — just run it.”
- “What didn’t work the first time?”
- “If I change one field in the manifest schema tomorrow, what breaks in this slice? How do you know?”

-----

## Decisions you personally need to make before Step 1 starts

These are quick — but they’re blockers.

1. **Fork strategy for `noted`**: fresh repo with squashed import, or GitHub fork + strip branch? (Recommended: fresh repo.)
2. **Contracts repo name**: `meeting-intelligence-contracts`? Something else? (Whatever you pick, pick it now — it gets referenced in both other repos.)
3. **Contracts consumption mechanism**: git submodule, pinned-tag fetch, or copied folder with CI check? (Recommended: pinned-tag fetch. But the dev team may have strong preferences.)
4. **Bundle identifier for `noted`**: what reverse-domain form do you own or plan to use? (Something like `app.noted.Noted` works as a placeholder.)
5. **Target macOS version**: HushScribe is macOS 26+, Apple Silicon only. Is that acceptable? (For your own use, yes. If the dev team is on older hardware, that’s a conversation.)

Hand these five answers to the dev team as part of kicking off Step 1.

-----

## What I can help with next

Ranked by usefulness right now:

1. **Draft the contracts repo’s initial contents** (Step 3 content). I have all the source material in the master plan; I can produce a first-draft set of schema files, CLI contract doc, and versioning policy that the dev team reviews rather than writes from scratch. This is probably the highest-leverage thing I can do for you.
2. **Draft the two component sub-plans** (Step 6). Once Steps 1–5 are complete, I can turn the master plan phases into concrete ticket-level plans for each repo.
3. **Draft the HushScribe strip PR description** (Step 4). A detailed, reviewable description of what’s being removed and why, based on the triage table, so the dev team’s actual PR is reviewable in one sitting.
4. **Draft the first-vertical-slice test script** (Step 7). A zsh script that runs the slice end-to-end, so the dev team has a concrete acceptance test to build towards.

Say which you want and I’ll start.

-----

## Appendix: HushScribe module triage (my first-pass)

Use this as the dev team’s starting point for Step 1. They should refine it against the actual source; this is inferred from the architecture doc, not read from the code.

|File                                      |Bucket         |Why                                                                                                     |
|------------------------------------------|---------------|--------------------------------------------------------------------------------------------------------|
|`App/HushScribeApp.swift`                 |REWRITE        |App entry point stays, but menubar setup and initial UI swap to `noted`’s menubar-only shape.           |
|`Audio/MicCapture.swift`                  |KEEP           |AVAudioEngine mic capture is exactly what `in_person` mode needs.                                       |
|`Audio/SystemAudioCapture.swift`          |KEEP           |ScreenCaptureKit-based system audio capture. Needed for `online` mode (Phase 5).                        |
|`Models/Models.swift`                     |KEEP (audit)   |Core domain types. Audit for summariser-specific types that come out.                                   |
|`Models/RecordingState.swift`             |REWRITE        |Session state enum exists; must be expanded to match §10.1 (eight states, not HushScribe’s smaller set).|
|`Models/SummaryModel.swift`               |STRIP          |LLM model list. Summarisation is `briefing`’s job now.                                                  |
|`Models/TranscriptStore.swift`            |KEEP (audit)   |Live transcript state. Keep if small; trim observability helpers that only feed the viewer.             |
|`Services/LLMSummaryEngine.swift`         |STRIP          |MLX-based on-device LLM. Out.                                                                           |
|`Services/MeetingMonitor.swift`           |STRIP          |Auto-detects meeting apps. Explicitly against guardrail #4 (`noted` doesn’t interpret context).         |
|`Services/SummaryService.swift`           |STRIP          |Apple NL extractive summarisation. Out.                                                                 |
|`Settings/AppSettings.swift`              |REWRITE        |Migrate from UserDefaults to `~/Library/Application Support/noted/settings.toml` per §20.4.             |
|`Storage/SessionStore.swift`              |REWRITE        |Session metadata storage. Must produce the §11.1 session directory layout.                              |
|`Storage/TranscriptLogger.swift`          |REWRITE        |Writes .md today. Must write `transcript.txt`, `transcript.json`, `segments.json` per §15.5 and §26.3.  |
|`Transcription/ASRBackend.swift`          |KEEP           |Protocol stays.                                                                                         |
|`Transcription/SFSpeechBackend.swift`     |KEEP           |Apple Speech backend. Useful as a fallback option in settings.                                          |
|`Transcription/StreamingTranscriber.swift`|KEEP           |VAD + ASR pipeline. Core asset.                                                                         |
|`Transcription/TranscriptionEngine.swift` |KEEP           |Dual-stream orchestration. Core asset.                                                                  |
|`Transcription/WhisperKitBackend.swift`   |KEEP           |Primary ASR backend if Swift path is chosen (Step 2).                                                   |
|`Views/ContentView.swift`                 |STRIP          |Main window. `noted` has no main window — menubar only.                                                 |
|`Views/ControlBar.swift`                  |STRIP          |Main-window record controls. Replaced by menubar menu items.                                            |
|`Views/OnboardingView.swift`              |REWRITE        |First-launch flow stays, but content changes (permissions, settings file location, Obsidian vault).     |
|`Views/SettingsView.swift`                |REWRITE        |Settings stay; content is the §20.4 minimal set.                                                        |
|`Views/SpeakerNamingView.swift`           |STRIP          |Post-session speaker naming UI. Attribution is `briefing`’s concern via the attribution policy (§16.3). |
|`Views/SummarizeView.swift`               |STRIP          |Transcript viewer + AI summary. Explicitly out per the master plan.                                     |
|`Views/TranscriptView.swift`              |STRIP          |Live transcript bubbles. `noted` does not surface the live transcript.                                  |
|`Views/WaveformView.swift`                |KEEP (optional)|VU meters. Nice-to-have for the status panel (§6.4). Low priority.                                      |

Dependencies expected to come out with the strips: `mlx-swift-lm`, MLX model cache logic. `FluidAudio` stays (diarization, VAD). `WhisperKit` stays if Swift ASR is chosen.
