# contracts/

Neutral contracts between `briefing` (Python orchestration) and `noted` (Swift capture agent) for the Meeting Intelligence System.

This directory lives inside the root repository `briefing-noted-contracts` but is the versioned surface consumers pin to. Schemas, CLI contract, on-disk layout, and vocabulary are the only things here. There is no code.

The three JSON Schemas in `schemas/` are **executable contracts**, not documentation. Consumers are expected to validate their payloads against them directly with a standard JSON Schema library (e.g. Python `jsonschema`, Swift `JSONSchema`) at build time and at runtime boundaries. Consumers must enable JSON Schema `format` assertion when validating timestamp fields; the schemas combine `format: date-time` for RFC 3339 shape with a suffix pattern for the explicit-offset guardrail. Compatibility semantics — how the `schema_version` pattern, closed enums, and `additionalProperties: true` interact — are specified in `versioning-policy.md`.

## What's in this directory

| File | Purpose |
|------|---------|
| `schemas/manifest.v1.json` | JSON Schema for the session manifest (Master Plan §8). |
| `schemas/completion.v1.json` | JSON Schema for the session completion file (§11.3). |
| `schemas/runtime-status.v1.json` | JSON Schema for the runtime status file (§10.3). |
| `cli-contract.md` | `noted`'s CLI surface: commands, exit codes, stdout JSON shapes (§9). |
| `session-directory.md` | On-disk layout and file-requirements table (§11). |
| `vocabulary.md` | Locked vocabulary: stop reasons, statuses, phases, filenames (§26). |
| `versioning-policy.md` | How schema versions evolve; change-proposal process. |
| `fixtures/` | Shared valid/invalid manifests, completion examples, and generated smoke-test audio for consumer tests. |
| `CHANGELOG.md` | Versioned change log. |

## How to consume this contract

Both `briefing` and `noted` consume this repo **by pinned semver tag**. Code in either repo must pin against a tag, never against `main`.

### Option A — git submodule (recommended default)

Each consumer repo carries the whole `briefing-noted-contracts` root as a submodule and reads `contracts/` inside it.

```bash
# in briefing/ or noted/
git submodule add https://github.com/darrencroton/briefing-noted-contracts.git vendor/contracts
git -C vendor/contracts checkout v1.0.0
git add .gitmodules vendor/contracts
git commit -m "Pin contracts to v1.0.0"
```

Consumers then read schemas from `vendor/contracts/contracts/schemas/...`.

Bumping:

```bash
git -C vendor/contracts fetch --tags
git -C vendor/contracts checkout v1.1.0
git add vendor/contracts
git commit -m "Bump contracts pin to v1.1.0"
```

### Option B — tarball fetch at tag

For consumers that prefer not to carry a submodule, a small fetch script can download the tagged tarball from GitHub and extract the `contracts/` subdirectory into `vendor/contracts/` at build time. The tag is the thing that matters — if your fetch script doesn't pin one, you don't have a contract.

### Not acceptable

- Copying schema files into a consumer repo and editing them in place. Any change must go through this repo.
- Pinning to a branch or a commit instead of a tag. The tag is the stable reference.
- Two consumers on different majors. If `briefing` is on v2 and `noted` is on v1, the system is broken.

## How to propose a change

See `versioning-policy.md` for the full rules. In short:

1. Open a PR here with the change, a diff summary, a migration note, and a `CHANGELOG.md` entry.
2. Classify the PR: **patch** (docs/examples), **minor** (additive and backward-compatible), or **major** (breaking).
3. Approver signs off. For major bumps, include a rollout plan naming the consumer branches that will adopt v2.
4. Merge, then **immediately** tag `vX.Y.Z` on the root repo.
5. Each consumer opens its own PR to bump the pin.

Contracts commits that are not tagged are not considered released. Never emit a `schema_version` that isn't tagged.

## Non-negotiables (derived from the Supplemental Implementation Guardrails)

- There is exactly **one** manifest schema. Ad hoc sessions use the canonical manifest with nulls in the permitted slots; no "lightweight" variant (guardrail 2).
- `completion.json` is the sole source of truth for session outcome. Consumers must read it first, never infer from file presence or log parsing (guardrail 3).
- All timestamps are ISO-8601 with explicit timezone offsets (guardrail 5).
- `noted` is not allowed to compose a manifest from calendar data. Only `briefing` does that. The contracts reflect this by keeping manifest construction a `briefing`-owned concern (guardrails 4, 8, 11).
- Multi-Mac `meeting.location_type` routing is `briefing` policy. `noted` may carry the field through validation/logging, but it must not interpret it to make calendar or workflow decisions.
- Raw audio is the primary asset and is preserved whenever capture succeeds (guardrail 10). The session-directory contract codifies this with the file-requirements table.

## Phase 1 status

v1.0.0 closes Phase 1 (Lock Contracts) of the master plan. All decisions in §27 that shape Phase 1 artefacts are recorded in the master plan itself and reflected here. Phase 2 work on `noted` may begin once this tag exists.

## Consuming project structure

The broader project is three repositories living side-by-side:

| Repo | Role |
|------|------|
| `briefing-noted-contracts` | This repo. Neutral contracts, pinned by tag. |
| `briefing` | Orchestration brain. Python 3.13+. |
| `noted` | Menubar capture agent. Swift 6.3, macOS 26+. |

See `AGENTS.md` at the root for the architectural boundaries each consumer must respect.
