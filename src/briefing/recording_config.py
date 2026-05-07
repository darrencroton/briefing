"""Parsing helpers for noted config markers and series recording metadata."""

from __future__ import annotations

import re
from typing import Any

import yaml

from .coerce import optional_int as _optional_int, optional_str as _optional_str, parse_optional_bool
from .location_routing import normalize_location_type
from .models import RecordingConfig, RecordingPolicyConfig


class RecordingConfigError(ValueError):
    """Raised when recording metadata cannot be parsed."""


_MARKER = re.compile(r"^\s*(?:```)?\s*noted\s+config\s*:?\s*(?:```)?\s*$", re.IGNORECASE)
_FIELDISH = re.compile(r"^\s*[-\w]+\s*:")


def parse_noted_config(notes: str | None) -> RecordingConfig | None:
    """Parse a case-insensitive ``noted config`` YAML marker from event notes."""
    if not notes:
        return None
    lines = notes.splitlines()
    for index, line in enumerate(lines):
        if not _MARKER.match(line):
            continue
        config_lines: list[str] = []
        in_fence = line.strip().startswith("```")
        for raw_line in lines[index + 1 :]:
            stripped = raw_line.strip()
            if in_fence and stripped == "```":
                break
            if not stripped:
                if config_lines:
                    break
                continue
            if not config_lines and not _FIELDISH.match(raw_line):
                continue
            if config_lines and not raw_line.startswith((" ", "-", "\t")) and not _FIELDISH.match(raw_line):
                break
            config_lines.append(raw_line)
        raw = yaml.safe_load("\n".join(config_lines)) if config_lines else {}
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise RecordingConfigError("noted config marker must contain YAML key/value fields")
        return recording_config_from_mapping(raw)
    return None


def recording_config_from_mapping(raw: dict[str, Any]) -> RecordingConfig:
    """Build recording config from marker-style YAML fields."""
    participants = raw.get("participants") or {}
    if not isinstance(participants, dict):
        raise RecordingConfigError("noted config participants must be a mapping")
    transcription = raw.get("transcription") or {}
    if not isinstance(transcription, dict):
        raise RecordingConfigError("noted config transcription must be a mapping")
    policy_raw = raw.get("recording_policy") or raw.get("policy") or {}
    if not isinstance(policy_raw, dict):
        raise RecordingConfigError("noted config recording_policy must be a mapping")

    mode = raw.get("mode")
    mode_type = None
    if raw.get("audio_strategy") is not None:
        raise RecordingConfigError("noted config audio_strategy has been removed; set mode instead")
    if isinstance(mode, dict):
        if mode.get("audio_strategy") is not None:
            raise RecordingConfigError("noted config mode.audio_strategy has been removed; set mode.type instead")
        mode_type = _optional_str(mode.get("type"))
    else:
        mode_type = _optional_str(mode)

    return RecordingConfig(
        record=_optional_bool(raw.get("record")),
        location_type=normalize_location_type(_optional_str(raw.get("location_type"))),
        mode=mode_type,
        host_name=_optional_str(participants.get("host_name", raw.get("host_name"))),
        attendees_expected=_optional_int(participants.get("attendees_expected", raw.get("attendees_expected"))),
        participant_names=[
            str(item)
            for item in participants.get("participant_names", raw.get("participant_names", []))
        ],
        language=_optional_str(transcription.get("language", raw.get("language"))),
        asr_backend=_optional_str(transcription.get("asr_backend", raw.get("asr_backend"))),
        diarization_enabled=_optional_bool(
            transcription.get("diarization_enabled", raw.get("diarization_enabled"))
        ),
        speaker_count_hint=_optional_int(
            transcription.get("speaker_count_hint", raw.get("speaker_count_hint"))
        ),
        note_dir=_optional_str(raw.get("note_dir")),
        note_slug=_optional_str(raw.get("note_slug")),
        recording_policy=RecordingPolicyConfig(
            auto_start=_optional_bool(policy_raw.get("auto_start")),
            auto_stop=_optional_bool(policy_raw.get("auto_stop")),
            default_extension_minutes=_optional_int(policy_raw.get("default_extension_minutes")),
            max_single_extension_minutes=_optional_int(policy_raw.get("max_single_extension_minutes")),
            pre_end_prompt_minutes=_optional_int(policy_raw.get("pre_end_prompt_minutes")),
            no_interaction_grace_minutes=_optional_int(policy_raw.get("no_interaction_grace_minutes")),
        ),
    )


def _optional_bool(value: Any) -> bool | None:
    try:
        return parse_optional_bool(value)
    except ValueError as exc:
        raise RecordingConfigError(f"Invalid boolean value in noted config: {exc}") from exc
