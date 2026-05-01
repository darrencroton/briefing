from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from briefing.main import cli
from briefing.retention import RetentionResult, run_retention_sweep, run_retention_sweep_best_effort


CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "vendor" / "contracts" / "contracts"
COMPLETION_FIXTURES = CONTRACTS_DIR / "fixtures" / "completions"


def _write_completed_session(
    sessions_root: Path,
    session_id: str,
    *,
    completed_at: str,
    audio: bool = True,
) -> Path:
    session_dir = sessions_root / session_id
    (session_dir / "outputs").mkdir(parents=True)
    (session_dir / "transcript").mkdir()
    (session_dir / "logs").mkdir()
    payload = json.loads((COMPLETION_FIXTURES / "completed.json").read_text(encoding="utf-8"))
    payload["session_id"] = session_id
    payload["completed_at"] = completed_at
    (session_dir / "outputs" / "completion.json").write_text(json.dumps(payload), encoding="utf-8")
    (session_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (session_dir / "transcript" / "transcript.txt").write_text("transcript\n", encoding="utf-8")
    (session_dir / "logs" / "noted.log").write_text("log\n", encoding="utf-8")
    if audio:
        (session_dir / "audio").mkdir()
        (session_dir / "audio" / "raw_room.wav").write_bytes(b"wav")
    return session_dir


def test_retention_dry_run_selects_old_completed_audio_only(app_settings) -> None:
    old_session = _write_completed_session(
        app_settings.meeting_intelligence.sessions_root,
        "old",
        completed_at="2026-04-20T10:00:00+10:00",
    )
    young_session = _write_completed_session(
        app_settings.meeting_intelligence.sessions_root,
        "young",
        completed_at="2026-04-30T10:00:00+10:00",
    )
    trash_calls: list[Path] = []

    result = run_retention_sweep(
        app_settings,
        dry_run=True,
        now=datetime.fromisoformat("2026-05-01T12:00:00+10:00"),
        trash_fn=trash_calls.append,
    )

    assert result.ok
    assert result.scanned_sessions == 2
    assert result.eligible_sessions == 1
    assert result.trashed_files == [str(old_session / "audio" / "raw_room.wav")]
    assert trash_calls == []
    assert (old_session / "manifest.json").exists()
    assert (old_session / "transcript" / "transcript.txt").exists()
    assert (old_session / "outputs" / "completion.json").exists()
    assert any(item["path"] == str(young_session) for item in result.skipped_files)


def test_retention_skips_missing_or_invalid_completion(app_settings) -> None:
    missing = app_settings.meeting_intelligence.sessions_root / "missing"
    (missing / "audio").mkdir(parents=True)
    (missing / "audio" / "raw_room.wav").write_bytes(b"wav")
    invalid = app_settings.meeting_intelligence.sessions_root / "invalid"
    (invalid / "outputs").mkdir(parents=True)
    (invalid / "audio").mkdir()
    (invalid / "outputs" / "completion.json").write_text("{bad", encoding="utf-8")
    (invalid / "audio" / "raw_room.wav").write_bytes(b"wav")

    result = run_retention_sweep(
        app_settings,
        dry_run=True,
        now=datetime.fromisoformat("2026-05-01T12:00:00+10:00"),
    )

    assert result.ok
    assert result.eligible_sessions == 0
    assert result.trashed_files == []
    skipped_paths = {item["path"] for item in result.skipped_files}
    assert str(missing) in skipped_paths
    assert str(invalid) in skipped_paths


def test_retention_apply_uses_injected_trash_function(app_settings) -> None:
    session_dir = _write_completed_session(
        app_settings.meeting_intelligence.sessions_root,
        "old",
        completed_at="2026-04-20T10:00:00+10:00",
    )
    calls: list[Path] = []

    def fake_trash(path: Path) -> None:
        calls.append(path)
        path.unlink()

    result = run_retention_sweep(
        app_settings,
        now=datetime.fromisoformat("2026-05-01T12:00:00+10:00"),
        trash_fn=fake_trash,
    )

    assert result.ok
    assert calls == [session_dir / "audio" / "raw_room.wav"]
    assert not (session_dir / "audio" / "raw_room.wav").exists()


def test_retention_cli_dry_run_outputs_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    app_settings,
) -> None:
    monkeypatch.setattr("sys.argv", ["briefing", "retention-sweep", "--dry-run"])
    monkeypatch.setattr("briefing.main.load_settings", lambda: app_settings)
    monkeypatch.setattr("briefing.main.configure_logging", lambda settings: None)

    exit_code = cli()

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["retention_days"] == 7


def test_retention_best_effort_is_silent_when_nothing_happens(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    app_settings,
) -> None:
    result = RetentionResult(
        ok=True,
        dry_run=False,
        sessions_root=str(app_settings.meeting_intelligence.sessions_root),
        retention_days=7,
        cutoff="2026-05-01T12:00:00+10:00",
        scanned_sessions=1,
    )
    monkeypatch.setattr("briefing.retention.run_retention_sweep", lambda settings, dry_run=False: result)

    with caplog.at_level(logging.INFO, logger="briefing.retention"):
        run_retention_sweep_best_effort(app_settings)

    assert caplog.records == []


def test_retention_best_effort_logs_when_files_are_eligible(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    app_settings,
) -> None:
    result = RetentionResult(
        ok=True,
        dry_run=True,
        sessions_root=str(app_settings.meeting_intelligence.sessions_root),
        retention_days=7,
        cutoff="2026-05-01T12:00:00+10:00",
        scanned_sessions=1,
        eligible_sessions=1,
        trashed_files=["/tmp/session/audio/raw_room.wav"],
    )
    monkeypatch.setattr("briefing.retention.run_retention_sweep", lambda settings, dry_run=False: result)

    with caplog.at_level(logging.INFO, logger="briefing.retention"):
        run_retention_sweep_best_effort(app_settings, dry_run=True)

    assert "Raw-audio retention sweep complete" in caplog.text
