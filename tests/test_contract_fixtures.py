from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


def _contracts_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "vendor" / "contracts" / "contracts"


def test_contracts_snapshot_is_pinned_to_expected_tag() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tag = (repo_root / "vendor" / "contracts" / "CONTRACTS_TAG").read_text().strip()

    assert tag == "v1.0.2"


def test_shared_contract_fixtures_validate_against_schemas() -> None:
    contracts_dir = _contracts_dir()
    manifest_schema = json.loads((contracts_dir / "schemas" / "manifest.v1.json").read_text())
    completion_schema = json.loads((contracts_dir / "schemas" / "completion.v1.json").read_text())

    manifest_validator = Draft202012Validator(manifest_schema, format_checker=FormatChecker())
    completion_validator = Draft202012Validator(completion_schema, format_checker=FormatChecker())

    manifest_expectations = {
        "valid-inperson.json": True,
        "valid-adhoc.json": True,
        "valid-with-next-meeting.json": True,
        "invalid-missing-required.json": False,
        "invalid-bad-timezone.json": False,
        "invalid-naive-scheduled-end-time.json": False,
    }

    for filename, should_be_valid in manifest_expectations.items():
        fixture = json.loads((contracts_dir / "fixtures" / "manifests" / filename).read_text())
        errors = list(manifest_validator.iter_errors(fixture))
        assert (not errors) is should_be_valid, filename
        if filename == "invalid-bad-timezone.json":
            assert any(error.validator == "pattern" for error in errors), filename
        if filename == "invalid-naive-scheduled-end-time.json":
            assert any(list(error.path) == ["meeting", "scheduled_end_time"] for error in errors), filename

    for path in (contracts_dir / "fixtures" / "completions").glob("*.json"):
        fixture = json.loads(path.read_text())
        assert not list(completion_validator.iter_errors(fixture)), path.name


def test_manifest_schema_rejects_malformed_offset_timestamp() -> None:
    contracts_dir = _contracts_dir()
    manifest_schema = json.loads((contracts_dir / "schemas" / "manifest.v1.json").read_text())
    validator = Draft202012Validator(manifest_schema, format_checker=FormatChecker())
    fixture = json.loads((contracts_dir / "fixtures" / "manifests" / "valid-inperson.json").read_text())

    fixture["created_at"] = "not-a-date+10:00"

    errors = list(validator.iter_errors(fixture))
    assert any(error.validator == "format" and list(error.path) == ["created_at"] for error in errors)


def test_completion_fixtures_preserve_ingest_decision_contract() -> None:
    contracts_dir = _contracts_dir()
    completions_dir = contracts_dir / "fixtures" / "completions"

    completed = json.loads((completions_dir / "completed.json").read_text())
    warning = json.loads((completions_dir / "completed-with-warnings.json").read_text())
    failed_startup = json.loads((completions_dir / "failed-startup.json").read_text())
    failed_capture = json.loads((completions_dir / "failed-capture.json").read_text())

    assert completed["terminal_status"] == "completed"
    assert completed["audio_capture_ok"] is True
    assert completed["transcript_ok"] is True

    assert warning["terminal_status"] == "completed_with_warnings"
    assert warning["transcript_ok"] is True
    assert warning["diarization_ok"] is False

    assert failed_startup["stop_reason"] == "startup_failure"
    assert failed_startup["audio_capture_ok"] is False

    assert failed_capture["stop_reason"] == "capture_failure"
    assert failed_capture["audio_capture_ok"] is True
