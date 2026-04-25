"""Fixture-driven tests for the session-ingest path (B-20)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from briefing.llm import LLMResponse
from briefing.main import _session_ingest
from briefing.notes import NoteStructureError
from briefing.session.completion import (
    CompletionInvalid,
    CompletionMissing,
    CompletionUnsupportedVersion,
    IngestDecision,
    decide,
    read_completion,
)
from briefing.session.ingest import run_session_ingest
from briefing.session.loader import ManifestInvalid, ManifestMissing, load_manifest
from briefing.session.note_summary import (
    SUMMARY_HEADING,
    MissingNoteTemplate,
    write_summary_block,
)
from briefing.session.transcript import TranscriptEmpty, TranscriptMissing, load_transcript


CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "vendor" / "contracts" / "contracts"
COMPLETION_FIXTURES = CONTRACTS_DIR / "fixtures" / "completions"
MANIFEST_FIXTURES = CONTRACTS_DIR / "fixtures" / "manifests"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class StubProvider:
    """Minimal LLM provider stub that returns a canned summary."""

    def __init__(self, text: str = "- Decision: stubbed summary line") -> None:
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
    completion_path: Path
    transcript_path: Path


def _base_manifest_payload(note_path: Path, session_id: str) -> dict:
    data = json.loads((MANIFEST_FIXTURES / "valid-inperson.json").read_text())
    data["session_id"] = session_id
    data["paths"]["session_dir"] = str(note_path.parent.parent / "session")
    data["paths"]["output_dir"] = str(note_path.parent.parent / "session" / "outputs")
    data["paths"]["note_path"] = str(note_path)
    return data


def _write_session(
    tmp_path: Path,
    completion_fixture_name: str,
    *,
    session_id: str = "2026-04-24T093000+1000-weekly-product-review",
    transcript: str | None = "The team agreed to ship v2 by 2026-05-15.\n",
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

    manifest_path = session_dir / "manifest.json"
    manifest = _base_manifest_payload(note_path, session_id)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    completion_src = json.loads((COMPLETION_FIXTURES / completion_fixture_name).read_text())
    completion_src["session_id"] = session_id
    completion_path = session_dir / "outputs" / "completion.json"
    completion_path.write_text(json.dumps(completion_src, indent=2), encoding="utf-8")

    transcript_path = session_dir / "transcript" / "transcript.txt"
    if transcript is not None:
        transcript_path.write_text(transcript, encoding="utf-8")

    return SessionFixture(
        session_dir=session_dir,
        note_path=note_path,
        manifest_path=manifest_path,
        completion_path=completion_path,
        transcript_path=transcript_path,
    )


# ---------------------------------------------------------------------------
# B-12 completion reader
# ---------------------------------------------------------------------------


def test_completion_reader_accepts_all_shared_fixtures(tmp_path: Path) -> None:
    for name in ("completed.json", "completed-with-warnings.json", "failed-capture.json", "failed-startup.json"):
        fx = _write_session(tmp_path / name.split(".")[0], name, session_id=f"id-{name}")
        completion = read_completion(fx.session_dir)
        assert completion.schema_version.startswith("1.")


def test_completion_reader_missing_file_raises(tmp_path: Path) -> None:
    empty_session = tmp_path / "empty"
    empty_session.mkdir()
    with pytest.raises(CompletionMissing):
        read_completion(empty_session)


def test_completion_reader_rejects_bad_json(tmp_path: Path) -> None:
    fx = _write_session(tmp_path / "bad", "completed.json")
    fx.completion_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CompletionInvalid):
        read_completion(fx.session_dir)


def test_completion_reader_rejects_unknown_major_version(tmp_path: Path) -> None:
    fx = _write_session(tmp_path / "v2", "completed.json")
    payload = json.loads(fx.completion_path.read_text())
    payload["schema_version"] = "2.0"
    fx.completion_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompletionUnsupportedVersion):
        read_completion(fx.session_dir)


def test_completion_reader_rejects_schema_violation(tmp_path: Path) -> None:
    fx = _write_session(tmp_path / "bad-status", "completed.json")
    payload = json.loads(fx.completion_path.read_text())
    payload["terminal_status"] = "bogus"
    fx.completion_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompletionInvalid):
        read_completion(fx.session_dir)


# ---------------------------------------------------------------------------
# decide() — partial-context policy (B-18)
# ---------------------------------------------------------------------------


def test_decide_maps_each_fixture_to_expected_bucket(tmp_path: Path) -> None:
    expectations = {
        "completed.json": IngestDecision.SUMMARISE,
        "completed-with-warnings.json": IngestDecision.SUMMARISE_WITH_WARNINGS,
        "failed-capture.json": IngestDecision.TRANSCRIPT_MISSING,
        "failed-startup.json": IngestDecision.STARTUP_FAILED,
    }
    for name, expected in expectations.items():
        fx = _write_session(tmp_path / name, name, session_id=f"id-{name}")
        completion = read_completion(fx.session_dir)
        assert decide(completion) == expected, name


# ---------------------------------------------------------------------------
# B-13 manifest loader
# ---------------------------------------------------------------------------


def test_manifest_loader_reads_note_path_only_from_manifest(tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json")
    manifest = load_manifest(fx.session_dir)
    assert manifest.note_path == fx.note_path
    assert manifest.title == "Weekly Product Review"


def test_manifest_loader_missing_file(tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json")
    fx.manifest_path.unlink()
    with pytest.raises(ManifestMissing):
        load_manifest(fx.session_dir)


def test_manifest_loader_rejects_invalid_payload(tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json")
    payload = json.loads(fx.manifest_path.read_text())
    del payload["meeting"]["title"]
    fx.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestInvalid):
        load_manifest(fx.session_dir)


# ---------------------------------------------------------------------------
# B-14 transcript adapter
# ---------------------------------------------------------------------------


def test_transcript_adapter_loads_and_hashes(tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json", transcript="hello world\n")
    transcript = load_transcript(fx.transcript_path)
    assert transcript.text == "hello world\n"
    assert len(transcript.sha256) == 64


def test_transcript_adapter_missing(tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json", transcript=None)
    with pytest.raises(TranscriptMissing):
        load_transcript(fx.transcript_path)


def test_transcript_adapter_empty(tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json", transcript="   \n")
    with pytest.raises(TranscriptEmpty):
        load_transcript(fx.transcript_path)


# ---------------------------------------------------------------------------
# B-17 managed summary block writer
# ---------------------------------------------------------------------------


def test_summary_block_appends_after_meeting_notes_and_preserves_user_content(tmp_path: Path) -> None:
    fx = _write_session(
        tmp_path,
        "completed.json",
        note_seed=(
            "---\ntitle: Weekly Product Review\n---\n"
            "# Weekly Product Review\n\n"
            "---\n## Briefing\n\n- Prior briefing bullet\n\n"
            "---\n## Meeting Notes\n\n"
            "- Manual hand-written note that must not change\n"
        ),
    )
    manifest = load_manifest(fx.session_dir)
    user_line = "- Manual hand-written note that must not change"
    result = write_summary_block(
        fx.note_path,
        manifest,
        "- Decision: ship v2 on 2026-05-15",
        session_id=manifest.session_id,
        transcript_sha256="abc123",
    )
    assert result.note_created is False
    assert result.block_written is True
    text = fx.note_path.read_text(encoding="utf-8")
    assert user_line in text
    assert SUMMARY_HEADING in text
    assert "MEETING-SUMMARY:start" in text
    assert "MEETING-SUMMARY:end" in text
    # Briefing stays intact
    assert "Prior briefing bullet" in text


def test_summary_block_preserves_blank_lines_before_following_heading(tmp_path: Path) -> None:
    note_seed = (
        "---\ntitle: Weekly Product Review\n---\n"
        "# Weekly Product Review\n\n"
        "---\n## Meeting Notes\n\n"
        "- Manual note with intentional spacing\n"
        "\n"
        "\n"
        "## Decisions\n\n"
        "- Existing decision stays untouched\n"
    )
    fx = _write_session(tmp_path, "completed.json", note_seed=note_seed)
    manifest = load_manifest(fx.session_dir)

    write_summary_block(
        fx.note_path,
        manifest,
        "- Summary bullet",
        session_id=manifest.session_id,
        transcript_sha256="abc123",
    )

    text = fx.note_path.read_text(encoding="utf-8")
    marker = "<!-- MEETING-SUMMARY:start"
    insertion_point = note_seed.index("## Decisions")
    assert text[: text.index(marker)] == note_seed[:insertion_point]
    assert text[text.index("## Decisions") :] == note_seed[insertion_point:]


def test_summary_block_replaces_existing_managed_block_only(tmp_path: Path) -> None:
    fx = _write_session(
        tmp_path,
        "completed.json",
        note_seed=(
            "---\ntitle: Weekly Product Review\n---\n"
            "# Weekly Product Review\n\n"
            "---\n## Meeting Notes\n\n- Byte-exact user content\n"
        ),
    )
    manifest = load_manifest(fx.session_dir)
    write_summary_block(
        fx.note_path,
        manifest,
        "- old summary",
        session_id=manifest.session_id,
        transcript_sha256="hash-one",
    )
    intermediate = fx.note_path.read_text(encoding="utf-8")

    result = write_summary_block(
        fx.note_path,
        manifest,
        "- new summary",
        session_id=manifest.session_id,
        transcript_sha256="hash-two",
    )
    assert result.block_replaced is True
    final = fx.note_path.read_text(encoding="utf-8")

    # User region (everything up to the managed block) is byte-identical
    marker = "<!-- MEETING-SUMMARY:start"
    assert intermediate[: intermediate.index(marker)] == final[: final.index(marker)]
    assert "- new summary" in final
    assert "- old summary" not in final
    assert 'transcript_sha256="hash-two"' in final


def test_summary_block_creates_missing_note_from_manifest(tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json", note_seed=None)
    assert not fx.note_path.exists()
    manifest = load_manifest(fx.session_dir)
    missing_note_template = MissingNoteTemplate(
        template_text=(
            "{{FRONTMATTER}}\n"
            "# {{HEADING}}\n"
            "[[{{DATE_LINK}}]] | [[{{SERIES_LINK}}]]\n\n"
            "---\n"
            "{{BRIEFING_BLOCK}}\n\n"
            "---\n"
            "## Meeting Notes\n\n"
            "{{MEETING_NOTES_PLACEHOLDER}}\n"
        ),
        meeting_notes_placeholder="- template placeholder",
    )
    result = write_summary_block(
        fx.note_path,
        manifest,
        "- only summary bullet",
        session_id=manifest.session_id,
        transcript_sha256="seed",
        missing_note_template=missing_note_template,
    )
    assert result.note_created is True
    text = fx.note_path.read_text(encoding="utf-8")
    assert "# Weekly Product Review" in text
    assert "[[2026-04-24]] | [[product-review-weekly Meetings]]" in text
    assert "- template placeholder" in text
    assert "## Meeting Notes" in text
    assert SUMMARY_HEADING in text
    assert "- only summary bullet" in text


def test_summary_block_rejects_notes_without_meeting_notes_section(tmp_path: Path) -> None:
    fx = _write_session(
        tmp_path,
        "completed.json",
        note_seed="# Weekly Product Review\n\nSome freeform user content\n",
    )
    manifest = load_manifest(fx.session_dir)
    with pytest.raises(NoteStructureError):
        write_summary_block(
            fx.note_path,
            manifest,
            "- summary",
            session_id=manifest.session_id,
            transcript_sha256="seed",
        )


# ---------------------------------------------------------------------------
# End-to-end ingest (B-18, B-19)
# ---------------------------------------------------------------------------


def test_ingest_completed_writes_summary_block(app_settings, tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json")
    provider = StubProvider()
    result = run_session_ingest(app_settings, fx.session_dir, provider=provider)
    assert result.ok
    assert result.exit_code == 0
    assert result.decision == IngestDecision.SUMMARISE.value
    assert result.block_written is True
    assert result.note_created is True
    assert provider.prompts and "Transcript:" in provider.prompts[0]
    assert "stubbed summary" in fx.note_path.read_text(encoding="utf-8")
    assert (fx.session_dir / "logs" / "briefing.log").exists()


def test_ingest_boundary_logs_include_manifest_identity(
    app_settings,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fx = _write_session(tmp_path, "completed.json")
    provider = StubProvider()

    with caplog.at_level(logging.INFO, logger="briefing.session.ingest"):
        result = run_session_ingest(app_settings, fx.session_dir, provider=provider)

    assert result.ok
    payloads: dict[str, dict[str, object]] = {}
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith("boundary="):
            continue
        boundary, payload = message.split(" ", 1)
        payloads[boundary.removeprefix("boundary=")] = json.loads(payload)

    for boundary in ("session_ingest_decision", "note_write"):
        assert payloads[boundary]["event_id"] == "calendar-event-7d9f2a1b"
        assert payloads[boundary]["series_id"] == "product-review-weekly"


def test_ingest_dry_run_generates_summary_without_writing_note(app_settings, tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json")
    provider = StubProvider()

    result = run_session_ingest(app_settings, fx.session_dir, provider=provider, dry_run=True)

    assert result.ok
    assert result.dry_run is True
    assert result.block_written is False
    assert result.note_created is False
    assert provider.prompts and "Transcript:" in provider.prompts[0]
    assert not fx.note_path.exists()


def test_ingest_completed_with_warnings_uses_speaker_agnostic_attribution(
    app_settings, tmp_path: Path
) -> None:
    fx = _write_session(tmp_path, "completed-with-warnings.json")
    provider = StubProvider()
    result = run_session_ingest(app_settings, fx.session_dir, provider=provider)
    assert result.decision == IngestDecision.SUMMARISE_WITH_WARNINGS.value
    assert "speaker-agnostic" in provider.prompts[0].lower()


def test_ingest_failed_startup_makes_no_summary_attempt(app_settings, tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "failed-startup.json", transcript=None)
    provider = StubProvider()
    result = run_session_ingest(app_settings, fx.session_dir, provider=provider)
    assert result.ok
    assert result.exit_code == 0
    assert result.decision == IngestDecision.STARTUP_FAILED.value
    assert result.block_written is False
    assert provider.prompts == []
    assert not fx.note_path.exists()


def test_ingest_failed_capture_without_transcript_is_recoverable_noop(
    app_settings, tmp_path: Path
) -> None:
    fx = _write_session(tmp_path, "failed-capture.json", transcript=None)
    provider = StubProvider()
    result = run_session_ingest(app_settings, fx.session_dir, provider=provider)
    assert result.ok
    assert result.exit_code == 0
    assert result.decision == IngestDecision.TRANSCRIPT_MISSING.value
    assert provider.prompts == []


def test_ingest_missing_completion_exits_2(app_settings, tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json")
    fx.completion_path.unlink()
    result = run_session_ingest(app_settings, fx.session_dir, provider=StubProvider())
    assert not result.ok
    assert result.exit_code == 2


def test_ingest_invalid_completion_exits_3(app_settings, tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json")
    fx.completion_path.write_text("{broken", encoding="utf-8")
    result = run_session_ingest(app_settings, fx.session_dir, provider=StubProvider())
    assert result.exit_code == 3


def test_ingest_missing_manifest_exits_4(app_settings, tmp_path: Path) -> None:
    fx = _write_session(tmp_path, "completed.json")
    fx.manifest_path.unlink()
    result = run_session_ingest(app_settings, fx.session_dir, provider=StubProvider())
    assert result.exit_code == 4


def test_ingest_rejects_mismatched_completion_and_manifest_session_ids(
    app_settings, tmp_path: Path
) -> None:
    fx = _write_session(tmp_path, "completed.json")
    manifest = json.loads(fx.manifest_path.read_text())
    manifest["session_id"] = "different-session-id"
    fx.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_session_ingest(app_settings, fx.session_dir, provider=StubProvider())

    assert not result.ok
    assert result.exit_code == 4
    assert "session_id" in (result.error or "")
    assert not fx.note_path.exists()


def test_ingest_reingest_replaces_existing_block_without_touching_user_content(
    app_settings, tmp_path: Path
) -> None:
    fx = _write_session(
        tmp_path,
        "completed.json",
        note_seed=(
            "---\ntitle: Weekly Product Review\n---\n"
            "# Weekly Product Review\n\n"
            "---\n## Meeting Notes\n\n- Hand-written note line\n"
        ),
    )
    provider = StubProvider(text="- first ingest bullet")
    first = run_session_ingest(app_settings, fx.session_dir, provider=provider)
    assert first.block_written is True
    first_text = fx.note_path.read_text(encoding="utf-8")

    # Second ingest with a different summary replaces only the managed block
    provider = StubProvider(text="- second ingest bullet")
    second = run_session_ingest(app_settings, fx.session_dir, provider=provider)
    assert second.block_replaced is True
    second_text = fx.note_path.read_text(encoding="utf-8")

    marker = "<!-- MEETING-SUMMARY:start"
    assert first_text[: first_text.index(marker)] == second_text[: second_text.index(marker)]
    assert "- Hand-written note line" in second_text
    assert "- second ingest bullet" in second_text
    assert "- first ingest bullet" not in second_text


def test_session_ingest_cli_bad_session_dir_emits_machine_readable_json(
    app_settings, tmp_path: Path, capsys
) -> None:
    missing_session_dir = tmp_path / "missing-session"

    exit_code = _session_ingest(app_settings, str(missing_session_dir))

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert captured.err == ""
    assert payload["ok"] is False
    assert payload["exit_code"] == 4
    assert payload["dry_run"] is False
    assert payload["session_dir"] == str(missing_session_dir)
    assert "session-dir not found" in payload["error"]
