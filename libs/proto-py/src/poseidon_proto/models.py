"""Version 1 data models for passive acoustic replay evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any, ClassVar, Mapping


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_MAX_FRAME_INDEX = 2**63 - 1
_MAX_SAMPLE_RATE_HZ = 384_000
_MAX_CHANNEL_COUNT = 8


class ModelValidationError(ValueError):
    """Raised when serialized evidence does not meet its schema."""


def _require_exact_keys(data: Mapping[str, Any], expected: set[str], model: str) -> None:
    actual = set(data)
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"unexpected {', '.join(sorted(extra))}")
        raise ModelValidationError(f"invalid {model} fields: {'; '.join(parts)}")


def _require_int(
    name: str,
    value: Any,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise ModelValidationError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ModelValidationError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ModelValidationError(f"{name} must be at most {maximum}")
    return value


def _require_number(
    name: str,
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if type(value) not in (int, float):
        raise ModelValidationError(f"{name} must be a number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ModelValidationError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ModelValidationError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ModelValidationError(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ModelValidationError(f"{name} must be at most {maximum}")
    return result


def _require_identifier(name: str, value: Any) -> str:
    if type(value) is not str or not _IDENTIFIER_RE.fullmatch(value):
        raise ModelValidationError(
            f"{name} must be a nonempty identifier using letters, digits, '.', '_' or '-'"
        )
    return value


def _require_literal(name: str, value: Any, allowed: set[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise ModelValidationError(f"{name} must be one of {', '.join(sorted(allowed))}")
    return value


def _require_rfc3339(name: str, value: Any) -> str:
    if type(value) is not str or not _RFC3339_RE.fullmatch(value):
        raise ModelValidationError(f"{name} must be a timezone-aware RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ModelValidationError(f"{name} must be a valid RFC3339 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ModelValidationError(f"{name} must include a timezone offset")
    return value


def _reject_constant(value: str) -> None:
    raise ModelValidationError(f"invalid JSON numeric constant: {value}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelValidationError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a strict JSON object, rejecting duplicate fields and non-finite numbers."""

    if type(text) is not str:
        raise ModelValidationError("JSON input must be text")
    try:
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_object_without_duplicates,
        )
    except ModelValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise ModelValidationError(f"invalid JSON: {exc.msg}") from exc
    except (ValueError, RecursionError) as exc:
        raise ModelValidationError(
            "JSON numeric value or nesting exceeds supported limits"
        ) from exc
    if type(value) is not dict:
        raise ModelValidationError("JSON root must be an object")
    return value


def canonical_json(data: Mapping[str, Any]) -> str:
    """Return deterministic compact JSON suitable for fingerprints and JSONL."""

    try:
        return json.dumps(
            dict(data),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ModelValidationError(f"value is not serializable canonical JSON: {exc}") from exc


@dataclass(frozen=True, slots=True)
class RecordingManifest:
    """Identity and provenance for one WAV recording."""

    schema_version: int
    recording_id: str
    site_id: str
    zone_id: str
    device_id: str
    started_at: str
    provenance: str
    wav_sha256: str
    calibration_status: str

    SCHEMA_VERSION: ClassVar[int] = 1
    FIELDS: ClassVar[set[str]] = {
        "schema_version",
        "recording_id",
        "site_id",
        "zone_id",
        "device_id",
        "started_at",
        "provenance",
        "wav_sha256",
        "calibration_status",
    }

    def __post_init__(self) -> None:
        if _require_int("schema_version", self.schema_version) != self.SCHEMA_VERSION:
            raise ModelValidationError("schema_version must be 1")
        for name in ("recording_id", "site_id", "zone_id", "device_id"):
            _require_identifier(name, getattr(self, name))
        _require_rfc3339("started_at", self.started_at)
        _require_literal("provenance", self.provenance, {"field", "synthetic"})
        if type(self.wav_sha256) is not str or not _SHA256_RE.fullmatch(self.wav_sha256):
            raise ModelValidationError("wav_sha256 must be 64 lowercase hexadecimal characters")
        _require_literal("calibration_status", self.calibration_status, {"uncalibrated"})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RecordingManifest:
        if not isinstance(data, Mapping):
            raise ModelValidationError("recording manifest must be an object")
        _require_exact_keys(data, cls.FIELDS, "recording manifest")
        return cls(**{name: data[name] for name in cls.FIELDS})

    @classmethod
    def from_json(cls, text: str) -> RecordingManifest:
        return cls.from_dict(parse_json_object(text))


@dataclass(frozen=True, slots=True)
class AcousticCandidateEvent:
    """An uncalibrated normalized-amplitude candidate from local WAV replay."""

    schema_version: int
    event_id: str
    recording_id: str
    site_id: str
    zone_id: str
    device_id: str
    event_type: str
    source: str
    provenance: str
    start_frame: int
    end_frame: int
    start_time_s: float
    end_time_s: float
    sample_rate_hz: int
    channel_count: int
    normalized_peak_max: float
    normalized_rms_max: float
    amplitude_units: str
    calibration_status: str
    detector_version: str
    detector_config_id: str
    run_id: str
    emission_enabled: bool

    SCHEMA_VERSION: ClassVar[int] = 1
    FIELDS: ClassVar[set[str]] = {
        "schema_version",
        "event_id",
        "recording_id",
        "site_id",
        "zone_id",
        "device_id",
        "event_type",
        "source",
        "provenance",
        "start_frame",
        "end_frame",
        "start_time_s",
        "end_time_s",
        "sample_rate_hz",
        "channel_count",
        "normalized_peak_max",
        "normalized_rms_max",
        "amplitude_units",
        "calibration_status",
        "detector_version",
        "detector_config_id",
        "run_id",
        "emission_enabled",
    }

    def __post_init__(self) -> None:
        if _require_int("schema_version", self.schema_version) != self.SCHEMA_VERSION:
            raise ModelValidationError("schema_version must be 1")
        for name in (
            "event_id",
            "recording_id",
            "site_id",
            "zone_id",
            "device_id",
            "detector_version",
            "detector_config_id",
            "run_id",
        ):
            _require_identifier(name, getattr(self, name))
        _require_literal("event_type", self.event_type, {"acoustic_candidate"})
        _require_literal("source", self.source, {"replay"})
        _require_literal("provenance", self.provenance, {"field", "synthetic"})
        start_frame = _require_int(
            "start_frame", self.start_frame, minimum=0, maximum=_MAX_FRAME_INDEX
        )
        end_frame = _require_int(
            "end_frame", self.end_frame, minimum=1, maximum=_MAX_FRAME_INDEX
        )
        if end_frame <= start_frame:
            raise ModelValidationError("end_frame must be greater than start_frame")
        sample_rate = _require_int(
            "sample_rate_hz", self.sample_rate_hz, minimum=1, maximum=_MAX_SAMPLE_RATE_HZ
        )
        _require_int(
            "channel_count", self.channel_count, minimum=1, maximum=_MAX_CHANNEL_COUNT
        )
        start_time = _require_number("start_time_s", self.start_time_s, minimum=0.0)
        end_time = _require_number("end_time_s", self.end_time_s, minimum=0.0)
        if end_time <= start_time:
            raise ModelValidationError("end_time_s must be greater than start_time_s")
        if not math.isclose(start_time, start_frame / sample_rate, rel_tol=0.0, abs_tol=1e-12):
            raise ModelValidationError("start_time_s must equal start_frame / sample_rate_hz")
        if not math.isclose(end_time, end_frame / sample_rate, rel_tol=0.0, abs_tol=1e-12):
            raise ModelValidationError("end_time_s must equal end_frame / sample_rate_hz")
        peak = _require_number("normalized_peak_max", self.normalized_peak_max, minimum=0.0, maximum=1.0)
        rms = _require_number("normalized_rms_max", self.normalized_rms_max, minimum=0.0, maximum=1.0)
        if rms > peak + 1e-15:
            raise ModelValidationError("normalized_rms_max cannot exceed normalized_peak_max")
        _require_literal(
            "amplitude_units", self.amplitude_units, {"normalized_pcm16_full_scale"}
        )
        _require_literal("calibration_status", self.calibration_status, {"uncalibrated"})
        if type(self.emission_enabled) is not bool or self.emission_enabled:
            raise ModelValidationError("emission_enabled must be false")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AcousticCandidateEvent:
        if not isinstance(data, Mapping):
            raise ModelValidationError("acoustic candidate event must be an object")
        _require_exact_keys(data, cls.FIELDS, "acoustic candidate event")
        return cls(**{name: data[name] for name in cls.FIELDS})

    @classmethod
    def from_json(cls, text: str) -> AcousticCandidateEvent:
        return cls.from_dict(parse_json_object(text))
