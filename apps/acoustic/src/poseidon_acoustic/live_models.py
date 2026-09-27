"""Immutable, file-only contracts for the separate live-capture journal family."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Protocol

SCHEMA = "poseidon.live-capture-journal.v1"
MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 65536
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class LiveValidationError(ValueError):
    pass


class EndOfSource(Exception):
    """An explicitly synthetic provider exhausted its declared input."""


class BackendFault(RuntimeError):
    def __init__(self, code: str, domain: str = "application", native_code: int | None = None):
        super().__init__(code)
        self.code, self.domain, self.native_code = code, domain, native_code


def canonical(value: object) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    except (ValueError, TypeError, OverflowError) as exc:
        raise LiveValidationError("metadata must be finite JSON") from exc


def parse_canonical(data: bytes, *, maximum: int = MAX_METADATA_BYTES) -> dict:
    if type(data) is not bytes or not 0 < len(data) <= maximum:
        raise LiveValidationError("metadata byte bound")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise LiveValidationError("duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(LiveValidationError("nonfinite JSON")))
        if type(value) is not dict or canonical(value) != data:
            raise LiveValidationError("metadata must be a canonical JSON object")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LiveValidationError("invalid canonical metadata") from exc


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _integer(value, name, low=1, high=2**63 - 1):
    if type(value) is not int or not low <= value <= high:
        raise LiveValidationError(f"{name} outside integer bounds")


def _number(value, name, high):
    try:
        valid = type(value) in (int, float) and 0 < value <= high and math.isfinite(value)
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise LiveValidationError(f"{name} outside positive finite bounds")


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise LiveValidationError(f"explicit {name} required")


@dataclass(frozen=True)
class CaptureLimitsV1:
    duration_s: float
    chunk_frames: int
    max_chunk_bytes: int
    queue_chunks: int
    source_queue_bytes: int
    queue_bytes: int
    output_bytes: int
    max_chunks: int
    reserve_bytes: int
    poll_timeout_s: float
    shutdown_timeout_s: float

    def __post_init__(self):
        _number(self.duration_s, "duration_s", 86400)
        _number(self.poll_timeout_s, "poll_timeout_s", 10)
        _number(self.shutdown_timeout_s, "shutdown_timeout_s", 60)
        for name in ("chunk_frames", "max_chunk_bytes", "queue_chunks", "source_queue_bytes",
                     "queue_bytes", "output_bytes", "max_chunks", "reserve_bytes"):
            _integer(getattr(self, name), name)
        _integer(self.max_chunk_bytes, "max_chunk_bytes", high=MAX_CHUNK_BYTES)
        _integer(self.queue_chunks, "queue_chunks", high=1024)
        _integer(self.max_chunks, "max_chunks", high=1000000)
        _integer(self.reserve_bytes, "reserve_bytes", low=16384, high=16 * 1024 * 1024)
        if not self.max_chunk_bytes <= self.source_queue_bytes <= self.queue_bytes <= 256 * 1024 * 1024:
            raise LiveValidationError("queue byte budgets inconsistent")
        if self.output_bytes <= self.reserve_bytes + MAX_METADATA_BYTES:
            raise LiveValidationError("output budget must leave intent and reserve capacity")


@dataclass(frozen=True)
class SourcePlanV1:
    source_id: str
    kind: str
    backend: str
    device_node: str | None
    expected_identity_json: bytes
    channels: tuple[str, ...]
    channel_roles: tuple[str, ...]
    sample_rate_hz: int | None
    width: int | None
    height: int | None
    frame_rate_num: int | None
    frame_rate_den: int | None
    subdevice: int | None
    period_frames: int | None
    period_frames_max: int | None
    buffer_frames: int | None
    buffer_frames_max: int | None
    mapped_buffers: int | None
    mapped_bytes: int | None
    provenance: str

    def __post_init__(self):
        if type(self.source_id) is not str or not _ID.fullmatch(self.source_id):
            raise LiveValidationError("invalid source_id")
        identity = parse_canonical(self.expected_identity_json)
        if self.kind not in ("audio", "video") or self.backend not in ("synthetic", "linux_alsa", "linux_v4l2"):
            raise LiveValidationError("unsupported source/backend")
        if self.backend != "synthetic" and self.backend != {"audio": "linux_alsa", "video": "linux_v4l2"}[self.kind]:
            raise LiveValidationError("backend/source mismatch")
        if type(self.channels) is not tuple or type(self.channel_roles) is not tuple:
            raise LiveValidationError("channel declarations must be immutable tuples")
        if self.backend == "synthetic":
            if self.provenance != "synthetic" or self.device_node is not None or identity:
                raise LiveValidationError("synthetic providers cannot claim device or physical provenance")
        else:
            if self.provenance not in ("bench", "field") or not identity:
                raise LiveValidationError("explicit unverified physical origin and expected identity required")
            pattern = r"/dev/snd/pcmC(0|[1-9][0-9]*)D(0|[1-9][0-9]*)c" if self.kind == "audio" else r"/dev/video(0|[1-9][0-9]*)"
            if type(self.device_node) is not str or not re.fullmatch(pattern, self.device_node):
                raise LiveValidationError("literal capture node required; no resolution/discovery")
            required_identity = {"pcm_id"} if self.kind == "audio" else {"driver", "card", "bus_info"}
            if set(identity) != required_identity:
                raise LiveValidationError("exact expected native identity fields required")
            for value in identity.values():
                _text(value, "expected native identity")
            for number in re.findall(r"[0-9]+", self.device_node):
                _integer(int(number), "numeric node selector", low=0, high=65535)
        if self.kind == "audio":
            _integer(len(self.channels), "channels", high=8)
            if len(set(self.channels)) != len(self.channels) or len(self.channels) != len(self.channel_roles):
                raise LiveValidationError("ordered channel IDs/roles mismatch")
            for value in self.channels + self.channel_roles:
                _text(value, "channel identity/role")
            _integer(self.sample_rate_hz, "sample_rate_hz", high=384000)
            for name in ("width", "height", "frame_rate_num", "frame_rate_den", "mapped_buffers", "mapped_bytes"):
                if getattr(self, name) is not None:
                    raise LiveValidationError(f"audio {name} must be null")
            if self.backend != "synthetic":
                _integer(self.subdevice, "subdevice", low=0, high=65535)
                for name in ("period_frames", "period_frames_max", "buffer_frames", "buffer_frames_max"):
                    _integer(getattr(self, name), name, high=4194304)
                if not self.period_frames <= self.period_frames_max <= self.buffer_frames_max or not self.period_frames <= self.buffer_frames <= self.buffer_frames_max:
                    raise LiveValidationError("explicit ALSA buffering bounds inconsistent")
            elif any(getattr(self, n) is not None for n in ("subdevice", "period_frames", "period_frames_max", "buffer_frames", "buffer_frames_max")):
                raise LiveValidationError("synthetic audio cannot declare native buffering")
        else:
            if self.channels or self.channel_roles or any(getattr(self, n) is not None for n in ("sample_rate_hz", "subdevice", "period_frames", "period_frames_max", "buffer_frames", "buffer_frames_max")):
                raise LiveValidationError("video audio fields must be empty/null")
            _integer(self.width, "width", high=1048576)
            _integer(self.height, "height", high=1048576)
            if self.width % 2 or self.width * self.height > 1048576:
                raise LiveValidationError("YUYV requires even width and bounded pixels")
            _integer(self.frame_rate_num, "frame_rate_num", high=1000000)
            _integer(self.frame_rate_den, "frame_rate_den", high=1000000)
            if self.backend != "synthetic":
                _integer(self.mapped_buffers, "mapped_buffers", high=8)
                _integer(self.mapped_bytes, "mapped_bytes", high=64 * 1024 * 1024)
                if self.mapped_bytes < self.width * self.height * 2 * self.mapped_buffers:
                    raise LiveValidationError("mapped-byte budget below active frames")
            elif self.mapped_buffers is not None or self.mapped_bytes is not None:
                raise LiveValidationError("synthetic video cannot declare native mappings")

    @property
    def format(self) -> str:
        return "S16_LE" if self.kind == "audio" else "YUYV"

    def to_dict(self) -> dict:
        result = asdict(self)
        result["expected_identity_json"] = parse_canonical(self.expected_identity_json)
        result["format"] = self.format
        return result

    @property
    def sha256(self) -> str:
        return digest(canonical(self.to_dict()))


@dataclass(frozen=True)
class CapturePlanV1:
    capture_id: str
    sources: tuple[SourcePlanV1, ...]
    limits: CaptureLimitsV1
    approval_reference: str
    actor: str

    def __post_init__(self):
        if type(self.capture_id) is not str or not _ID.fullmatch(self.capture_id):
            raise LiveValidationError("invalid capture_id")
        if type(self.sources) is not tuple or not 1 <= len(self.sources) <= 2 or any(type(s) is not SourcePlanV1 for s in self.sources):
            raise LiveValidationError("one audio and/or one video source required")
        if len({s.kind for s in self.sources}) != len(self.sources) or len({s.source_id for s in self.sources}) != len(self.sources):
            raise LiveValidationError("duplicate kind or source_id")
        if len({s.backend == "synthetic" for s in self.sources}) != 1:
            raise LiveValidationError("cannot mix synthetic and physical sources")
        if type(self.limits) is not CaptureLimitsV1:
            raise LiveValidationError("explicit limits required")
        for source in self.sources:
            size = self.limits.chunk_frames * len(source.channels) * 2 if source.kind == "audio" else source.width * source.height * 2
            if size > self.limits.max_chunk_bytes:
                raise LiveValidationError("requested payload exceeds chunk budget")
        _text(self.approval_reference, "approval_reference declaration")
        _text(self.actor, "actor declaration")

    @property
    def synthetic(self) -> bool:
        return self.sources[0].backend == "synthetic"

    def to_dict(self) -> dict:
        return {"capture_id": self.capture_id, "sources": [s.to_dict() for s in self.sources],
                "limits": asdict(self.limits), "approval_reference": self.approval_reference, "actor": self.actor}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return digest(self.canonical_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes) -> CapturePlanV1:
        data = parse_canonical(raw)
        try:
            sources = []
            for item in data.pop("sources"):
                item = dict(item)
                fmt = item.pop("format")
                item["expected_identity_json"] = canonical(item["expected_identity_json"])
                item["channels"] = tuple(item["channels"])
                item["channel_roles"] = tuple(item["channel_roles"])
                source = SourcePlanV1(**item)
                if fmt != source.format:
                    raise LiveValidationError("format substitution")
                sources.append(source)
            plan = cls(sources=tuple(sources), limits=CaptureLimitsV1(**data.pop("limits")), **data)
            if plan.canonical_bytes != raw:
                raise LiveValidationError("plan normalization is forbidden")
            return plan
        except (TypeError, KeyError, AttributeError) as exc:
            raise LiveValidationError("missing/unknown plan fields") from exc


@dataclass(frozen=True)
class CapturedBlockV1:
    payload: bytes
    units: int
    raw_metadata_json: bytes
    sequence: int | None = None

    def __post_init__(self):
        if type(self.payload) is not bytes or not 0 < len(self.payload) <= MAX_CHUNK_BYTES:
            raise LiveValidationError("payload must be bounded immutable owned bytes")
        _integer(self.units, "units")
        parse_canonical(self.raw_metadata_json)
        if self.sequence is not None:
            _integer(self.sequence, "sequence", low=0, high=2**32 - 1)


class CaptureBackend(Protocol):
    def configure(self) -> bytes: ...
    def start(self) -> None: ...
    def read(self, timeout_s: float) -> CapturedBlockV1 | None: ...
    def close(self) -> None: ...


class BackendFactory(Protocol):
    synthetic: bool
    def open(self, source: SourcePlanV1, limits: CaptureLimitsV1, admission: object) -> CaptureBackend: ...
