"""Tests for briefing session-reprocess."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from briefing.llm import LLMResponse
from briefing.session.reprocess import run_session_reprocess


CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "vendor" / "contracts" / "contracts"
COMPLETION_FIXTURES = CONTRACTS_DIR / "fixtures" / "completions"
MANIFEST_FIXTURES = CONTRACTS_DIR / "fixtures" / "manifests"

TRANSCRIPT = "Alice: We decided to ship v2 by May 15.\nBob: Agreed, I'll handle the release notes.\n"
SESSION_ID = "2026-04-25T100000+1000-reprocess-test"


class StubProvider:
    def __init__(self, text: str = "- Decision: stubbed reprocess summary") -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> LLMResponse:
        self.prompts.append(prompt)
        return LLMResponse(text=self.text, raw=self.text)


@dataclass(slots=True)
class SessionFixture:
    session_dir: Path
    note_path: Path
    manifest_path: Path
    transcript_path: Path


def _base_manifest(note_path: Path, session_id: str) -> dict:
    data = json.loads((MANIFEST_FIXTURES / "valid-inperson.json").read_text())
    data["session_id"] = session_id
    data["paths"]["session_dir"] = str(note_path.parent.parent / "session")
    data["paths"]["output_dir"] = str(note_path.parent.parent / "session" / "outputs")
    data["paths"]["note_path"] = str(note_path)
    return data


def _write_session(
    tmp_path: Path,
    *,
    session_id: str = SESSION_ID,
    transcript: str | None = TRANSCRIPT,
    completion_fixture: str | None = "completed.json",
    note_seed: str | None = None,
) -> SessionFixture:
    session_dir = tmp_path / "sessions" / session_id
    (session_dir / "outputs").mkdir(parents=True)
    (session_dir / "transcript").mkdir()
    (session_dir / "logs").mkdir()

    note_path = tmp_path / "vault" / "Meetings" / f"{session_id}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    if note_seed is not None:
        note_path.write_text(note_seed, encoding="utf-8")

    manifest = _base_manifest(note_path, session_id)
    (session_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if completion_fixture is not None:
        src = json.loads((COMPLETION_FIXTURES / completion_fixture).read_text())
        src["session_id"] = session_id
        (session_dir / "outputs" / "completion.json").write_text(json.dumps(src), encoding="utf-8")

    transcript_path = session_dir / "transcript" / "transcript.txt"
    if transcript is not None:
        transcript_path.write_text(transcript, encoding="utf-8")

    return SessionFixture(
        session_dir=session_dir,
        note_path=note_path,
        manifest_path=session_dir / "manifest.json",
        transcript_path=transcript_path,
    )


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


def test_reprocess_with_completion_writes_summary(tmp_path: Path, app_settings) -> None:
    """Reprocess succeeds when completion.json is present and transcript exists."""
    note_seed = "---\ntitle: Test\n---\n\n## Briefing\n\n- context\n\n## Meeting Notes\n\nmy notes\n"
    fx = _write_session(tmp_path, note_seed=note_seed, completion_fixture="completed.json")
    provider = StubProvider()

    result = run_session_reprocess(app_settings, fx.session_dir, provider=provider)

    assert result.ok
    assert result.exit_code == 0
    assert result.decision == "reprocess"
    assert result.block_written or result.block_replaced
    assert "## Meeting Summary" in fx.note_path.read_text(encoding="utf-8")


def test_reprocess_without_completion_uses_synthetic(tmp_path: Path, app_settings) -> None:
    """Reprocess succeeds without completion.json using a synthetic completion."""
    note_seed = "---\ntitle: Test\n---\n\n## Briefing\n\n- context\n\n## Meeting Notes\n\nmy notes\n"
    fx = _write_session(tmp_path, note_seed=note_seed, completion_fixture=None)
    provider = StubProvider()

    result = run_session_reprocess(app_settings, fx.session_dir, provider=provider)

    assert result.ok
    assert result.exit_code == 0
    assert result.block_written or result.block_replaced
    # Synthetic completion carries reprocessed_without_completion warning via terminal_status
    assert result.terminal_status == "completed_with_warnings"


def test_reprocess_replaces_existing_summary_block(tmp_path: Path, app_settings) -> None:
    """Re-running reprocess replaces the existing managed section, not appends."""
    existing_block = (
        "---\n"
        "## Meeting Summary\n\n- old summary\n"
    )
    note_seed = (
        "---\ntitle: Test\n---\n\n## Briefing\n\n- ctx\n\n## Meeting Notes\n\nmy notes\n\n"
        + existing_block
        + "\n"
    )
    fx = _write_session(tmp_path, note_seed=note_seed)
    provider = StubProvider(text="- new summary line")

    result = run_session_reprocess(app_settings, fx.session_dir, provider=provider)

    assert result.ok
    note_content = fx.note_path.read_text(encoding="utf-8")
    assert note_content.count("## Meeting Summary") == 1
    assert "new summary line" in note_content
    assert "old summary" not in note_content


def test_reprocess_dry_run_does_not_write(tmp_path: Path, app_settings) -> None:
    """Dry run returns ok without touching the note."""
    note_seed = "---\ntitle: T\n---\n\n## Briefing\n\n- ctx\n\n## Meeting Notes\n\nnotes\n"
    fx = _write_session(tmp_path, note_seed=note_seed)
    original = fx.note_path.read_text(encoding="utf-8")
    provider = StubProvider()

    result = run_session_reprocess(app_settings, fx.session_dir, provider=provider, dry_run=True)

    assert result.ok
    assert result.dry_run
    assert not result.block_written
    assert not result.block_replaced
    assert fx.note_path.read_text(encoding="utf-8") == original


def test_reprocess_creates_missing_note(tmp_path: Path, app_settings) -> None:
    """If the note doesn't exist, reprocess creates it from the template."""
    fx = _write_session(tmp_path)  # no note_seed to note_path doesn't exist
    provider = StubProvider()

    result = run_session_reprocess(app_settings, fx.session_dir, provider=provider)

    assert result.ok
    assert result.note_created
    assert fx.note_path.exists()


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_reprocess_missing_transcript_returns_exit_6(tmp_path: Path, app_settings) -> None:
    fx = _write_session(tmp_path, transcript=None)
    provider = StubProvider()

    result = run_session_reprocess(app_settings, fx.session_dir, provider=provider)

    assert not result.ok
    assert result.exit_code == 6


def test_reprocess_missing_manifest_returns_exit_4(tmp_path: Path, app_settings) -> None:
    session_dir = tmp_path / "empty"
    session_dir.mkdir()
    provider = StubProvider()

    result = run_session_reprocess(app_settings, session_dir, provider=provider)

    assert not result.ok
    assert result.exit_code == 4


def test_reprocess_llm_failure_returns_exit_6(tmp_path: Path, app_settings) -> None:
    from briefing.llm import LLMError

    note_seed = "---\ntitle: T\n---\n\n## Briefing\n\n- ctx\n\n## Meeting Notes\n\nnotes\n"
    fx = _write_session(tmp_path, note_seed=note_seed)

    class FailingProvider:
        def generate(self, prompt: str) -> LLMResponse:
            raise LLMError("LLM unavailable")

    result = run_session_reprocess(app_settings, fx.session_dir, provider=FailingProvider())

    assert not result.ok
    assert result.exit_code == 6
