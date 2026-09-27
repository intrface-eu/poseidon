"""Provisional acquisition sidecars, not RecordingManifest v1 or a live driver.

One writer per local workspace. Evidence is append-only; interrupted files are
kept and listed by recovery, never promoted without a committed receipt.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from typing import Iterator
import uuid
import wave


SCHEMA = "poseidon.acquisition-session.provisional.v1"
HEADER = "session.acquisition-v1.json"
FINAL = "segments.acquisition-v1.json"
HALT = "halt.acquisition-v1.json"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_PGM_PIXELS = 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class SessionError(ValueError):
    """Invalid input, damaged evidence, or a closed acquisition workspace."""


class CapacityExceeded(SessionError):
    """Storage or segment capacity reached; no evidence was evicted."""


def finite(value: float, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SessionError(f"{name} must be a finite number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (nonnegative and value < 0):
        raise SessionError(f"invalid {name}")
    return value


def positive_int(value: int, name: str, *, maximum: int = 2**53) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise SessionError(f"invalid {name}")
    return value


def safe_name(value: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value) or value in {".", ".."}:
        raise SessionError("expected a plain, bounded file name or identifier")
    return value


def canonical(value: object) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    except (ValueError, TypeError) as exc:
        raise SessionError(f"invalid JSON value: {exc}") from exc


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@contextmanager
def regular_input(path: Path | str):
    """Only local regular files; no symlinks, FIFOs, sockets or device nodes."""
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise SessionError(f"not a regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SessionError("input changed file type")
        yield stream


def read_bounded(path: Path | str, limit: int = MAX_JSON_BYTES) -> bytes:
    if type(limit) is not int or limit < 0:
        raise SessionError("invalid read budget")
    with regular_input(path) as stream:
        if os.fstat(stream.fileno()).st_size > limit:
            raise SessionError("file exceeds read budget")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise SessionError("file exceeds read budget")
    return data


def _parse_json_bytes(data: bytes):
    """Pure parser shared with delivered-export validation; no filesystem access."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SessionError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(SessionError("nonfinite JSON")))


def load_json(path: Path | str, limit: int = MAX_JSON_BYTES):
    try:
        return _parse_json_bytes(read_bounded(path, limit))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SessionError(f"invalid JSON: {exc}") from exc


def _sync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(directory: Path, name: str, data: bytes) -> None:
    """fsync then link without replacement; a crash leaves inspectable evidence."""
    safe_name(name)
    pending = directory / (name + ".pending-" + uuid.uuid4().hex)
    with pending.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(pending, directory / name, follow_symlinks=False)
    _sync_dir(directory)
    pending.unlink()  # Only our fully published staging link, never source evidence.
    _sync_dir(directory)


@dataclass(frozen=True)
class ClockMap:
    """drift_ppm is the source-to-reference mapping scale, not oscillator-fast sign."""

    reference_domain: str
    reference_epoch: str
    source_anchor_s: float = 0.0
    reference_anchor_s: float = 0.0
    drift_ppm: float = 0.0
    anchor_uncertainty_s: float = 0.0
    drift_uncertainty_ppm: float = 0.0
    source_domain: str = "source_seconds"
    method: str = "operator_declared"
    evidence_ref: str | None = None

    def __post_init__(self):
        safe_name(self.source_domain)
        safe_name(self.reference_domain)
        if self.source_domain == self.reference_domain:
            raise SessionError("source and reference clock domains must be distinct")
        if not isinstance(self.reference_epoch, str) or not self.reference_epoch.strip() or len(self.reference_epoch) > 256:
            raise SessionError("explicit reference_epoch required; no inferred UTC")
        if not isinstance(self.method, str) or self.method not in {"operator_declared", "measured_reference", "shared_clock"}:
            raise SessionError("unsupported clock relation method")
        if self.evidence_ref is not None:
            safe_name(self.evidence_ref)
        elif self.method != "operator_declared":
            raise SessionError("measured/shared-clock claims require an evidence reference")
        for name in ("source_anchor_s", "reference_anchor_s", "drift_ppm"):
            finite(getattr(self, name), name)
        finite(self.anchor_uncertainty_s, "anchor uncertainty", nonnegative=True)
        finite(self.drift_uncertainty_ppm, "drift uncertainty", nonnegative=True)
        if 1 + self.drift_ppm / 1e6 <= 0:
            raise SessionError("clock mapping must have a positive rate")

    @classmethod
    def from_relation(cls, relation: dict, *, reference_epoch: str) -> ClockMap:
        """Map the platform relation without inventing its absent reference epoch."""
        fields = {"source_domain", "reference_domain", "source_anchor_s", "reference_anchor_s", "drift_ppm",
                  "anchor_uncertainty_s", "drift_uncertainty_ppm", "method", "evidence_ref"}
        if not isinstance(relation, dict) or set(relation) != fields:
            raise SessionError("invalid canonical clock relation fields")
        return cls(**relation, reference_epoch=reference_epoch)

    def relation(self) -> dict:
        """Canonical relation fields; the sidecar's epoch must travel separately."""
        return {name: value for name, value in asdict(self).items() if name != "reference_epoch"}

    def at(self, source_s: float) -> tuple[float, float]:
        delta = finite(source_s, "source time") - self.source_anchor_s
        reference = self.reference_anchor_s + delta * (1 + self.drift_ppm / 1e6)
        uncertainty = self.anchor_uncertainty_s + abs(delta) * self.drift_uncertainty_ppm / 1e6
        return finite(reference, "reference time"), finite(uncertainty, "time uncertainty", nonnegative=True)


@dataclass(frozen=True)
class Channel:
    channel_id: str
    role: str

    def __post_init__(self):
        safe_name(self.channel_id)
        if not isinstance(self.role, str) or not self.role.strip() or len(self.role) > 256:
            raise SessionError("channel role required")


@dataclass(frozen=True)
class Source:
    source_id: str
    media: str
    provenance: str
    channels: tuple[Channel, ...]
    clock: ClockMap
    sample_rate_hz: int | None = None
    source_origin_s: float = 0.0
    origin: str = "operator-declared local file"
    input_sha256: str | None = None

    def __post_init__(self):
        safe_name(self.source_id)
        if self.media not in {"pcm16-wav", "pgm8"} or self.provenance not in {"synthetic", "file"}:
            raise SessionError("unsupported media or provenance")
        if (not isinstance(self.channels, tuple) or not 0 < len(self.channels) <= 16
                or any(not isinstance(c, Channel) for c in self.channels)
                or len({c.channel_id for c in self.channels}) != len(self.channels)):
            raise SessionError("immutable, distinct channel identities required")
        if not isinstance(self.clock, ClockMap):
            raise SessionError("clock mapping required")
        if self.media == "pcm16-wav":
            positive_int(self.sample_rate_hz, "sample rate", maximum=768000)
        elif self.sample_rate_hz is not None or len(self.channels) != 1:
            raise SessionError("PGM source requires one image channel and no audio sample rate")
        finite(self.source_origin_s, "source origin")
        if not isinstance(self.origin, str) or not self.origin.strip() or len(self.origin) > 512:
            raise SessionError("bounded origin/provenance description required")
        if self.input_sha256 is not None and (not isinstance(self.input_sha256, str)
                                              or not re.fullmatch(r"[0-9a-f]{64}", self.input_sha256)):
            raise SessionError("invalid original input checksum")

    @classmethod
    def from_dict(cls, value: dict) -> Source:
        try:
            data = dict(value)
            data["channels"] = tuple(Channel(**c) for c in data["channels"])
            data["clock"] = ClockMap(**data["clock"])
            return cls(**data)
        except (KeyError, TypeError) as exc:
            raise SessionError("invalid source metadata") from exc


def decode_pgm8(data: bytes) -> tuple[int, int, bytes]:
    """Bounded canonical P5/255 validation shared by the store and NEREID."""
    if not isinstance(data, bytes) or len(data) > MAX_PGM_PIXELS + 128:
        raise SessionError("PGM byte budget exceeded")
    match = re.match(rb"P5\n([1-9][0-9]{0,6}) ([1-9][0-9]{0,6})\n255\n", data[:128])
    if not match:
        raise SessionError("expected canonical 8-bit P5 PGM header")
    width, height = int(match[1]), int(match[2])
    pixels = data[match.end():]
    if width * height > MAX_PGM_PIXELS or len(pixels) != width * height:
        raise SessionError("PGM dimensions, truncation or trailing bytes")
    return width, height, pixels


def _validate_payload(source: Source, payload: bytes, units: int) -> None:
    if source.media == "pgm8":
        decode_pgm8(payload)
        return
    if (len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE"
            or struct.unpack_from("<I", payload, 4)[0] + 8 != len(payload)):
        raise SessionError("WAV payload RIFF length or header mismatch")
    try:
        with wave.open(io.BytesIO(payload), "rb") as reader:
            if (reader.getcomptype(), reader.getsampwidth(), reader.getnchannels(),
                    reader.getframerate(), reader.getnframes()) != (
                    "NONE", 2, len(source.channels), source.sample_rate_hz, units):
                raise SessionError("WAV payload format, channels, rate or frame count disagrees with source/receipt")
            if len(reader.readframes(units + 1)) != units * len(source.channels) * 2:
                raise SessionError("WAV payload data length disagrees with frame count")
    except (wave.Error, EOFError) as exc:
        raise SessionError(f"invalid PCM16 WAV payload: {exc}") from exc


def _directory(path: Path | str) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise SessionError("workspace must be a real directory")
    return path.resolve()


class Session:
    """Bounded append-only local file capture. All paths hardware-unverified."""

    def __init__(self, directory: Path | str):
        self.directory = _directory(directory)
        header = load_json(self.directory / HEADER)
        try:
            if set(header) != {"schema", "session_id", "sources", "max_bytes", "max_chunks",
                               "hardware_verified", "calibration", "finalize_reserve_bytes"}:
                raise SessionError("invalid session header fields")
            if header["schema"] != SCHEMA or header["hardware_verified"] is not False or header["calibration"] != "unverified":
                raise SessionError("unsupported session schema or hardware claim")
            safe_name(header["session_id"])
            self._sources = tuple(Source.from_dict(value) for value in header["sources"])
            self._validate_sources(self._sources)
            positive_int(header["max_chunks"], "segment capacity", maximum=4096)
            positive_int(header["max_bytes"], "storage capacity", maximum=2**40)
            if header["finalize_reserve_bytes"] != self.reserve(header["max_chunks"]):
                raise SessionError("invalid finalization reserve")
            if header["max_bytes"] < header["finalize_reserve_bytes"] + len(canonical(header)) + 1024:
                raise SessionError("storage budget cannot hold header and finalization reserve")
        except (KeyError, TypeError) as exc:
            raise SessionError("invalid session header") from exc
        self._header_bytes = canonical(header)
        if read_bounded(self.directory / HEADER) != self._header_bytes:
            raise SessionError("session header is noncanonical or changed during load")
        self._header = header

    @staticmethod
    def reserve(max_chunks: int) -> int:
        return 8192 + max_chunks * 512

    @staticmethod
    def _validate_sources(sources: tuple[Source, ...]) -> None:
        if not 0 < len(sources) <= 16 or len({s.source_id for s in sources}) != len(sources):
            raise SessionError("one to sixteen distinct sources required")
        domains = {(s.clock.reference_domain, s.clock.reference_epoch) for s in sources}
        if len(domains) != 1:
            raise SessionError("session sources must share an explicit reference domain and epoch")

    @classmethod
    def create(cls, directory: Path | str, session_id: str, sources: tuple[Source, ...],
               *, max_bytes: int = 16 * 1024 * 1024, max_chunks: int = 256) -> Session:
        safe_name(session_id)
        if not isinstance(sources, tuple) or any(not isinstance(s, Source) for s in sources):
            raise SessionError("immutable source tuple required")
        cls._validate_sources(sources)
        positive_int(max_chunks, "segment capacity", maximum=4096)
        positive_int(max_bytes, "storage capacity", maximum=2**40)
        header = {"schema": SCHEMA, "session_id": session_id, "sources": [asdict(s) for s in sources],
                  "max_bytes": max_bytes, "max_chunks": max_chunks, "hardware_verified": False,
                  "calibration": "unverified", "finalize_reserve_bytes": cls.reserve(max_chunks)}
        data = canonical(header)
        if max_bytes < cls.reserve(max_chunks) + len(data) + 1024:
            raise SessionError("storage budget cannot hold header and finalization reserve")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        publish(directory, HEADER, data)
        return cls(directory)

    @property
    def sources(self) -> tuple[Source, ...]:
        return self._sources

    def source(self, source_id: str) -> Source:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise SessionError("unknown source identity")

    @contextmanager
    def _locked(self):
        lock_path = self.directory / ".writer.lock"
        try:
            mode = lock_path.lstat().st_mode
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(mode):
                raise SessionError("invalid writer lock; nonregular path refused before open")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SessionError("invalid writer lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SessionError("another session writer is active") from exc
            yield
        finally:
            os.close(fd)

    def _inventory(self) -> dict[str, int]:
        result = {}
        for path in self.directory.iterdir():
            if len(result) >= self._header["max_chunks"] * 4 + 32:
                raise SessionError("workspace file count exceeds recovery budget")
            if not stat.S_ISREG(path.lstat().st_mode):
                raise SessionError("nonregular entry in workspace")
            if len(path.name) > 180:
                raise SessionError("unbounded workspace file name")
            result[path.name] = path.stat().st_size
        return result

    def _record(self, source_id: str, unit_start: int, units: int, source_start_s: float,
                source_end_s: float, dropped_units: int, gap_reason: str, payload: bytes,
                receipts: list[dict]) -> dict:
        source = self.source(source_id)
        if type(unit_start) is not int or not 0 <= unit_start <= 2**53:
            raise SessionError("invalid unit start")
        positive_int(units, "unit count")
        if unit_start + units > 2**53:
            raise SessionError("segment unit extent exceeds exact integer range")
        if type(dropped_units) is not int or dropped_units < 0:
            raise SessionError("invalid dropped unit count")
        finite(source_start_s, "source start")
        finite(source_end_s, "source end")
        if source_end_s <= source_start_s:
            raise SessionError("segment must have positive duration")
        if source.media == "pcm16-wav" and not math.isclose(
                source_end_s - source_start_s, units / source.sample_rate_hz, rel_tol=1e-9, abs_tol=1e-9):
            raise SessionError("audio duration disagrees with sample count")
        if source.media == "pgm8" and units != 1:
            raise SessionError("each PGM segment contains one frame")
        previous = next((r for r in reversed(receipts) if r["source_id"] == source_id), None)
        prior_end = source.source_origin_s if previous is None else previous["source_end_s"]
        prior_unit = 0 if previous is None else previous["unit_start"] + previous["units"]
        missing = unit_start - prior_unit
        gap_s = source_start_s - prior_end
        if missing < 0 or gap_s < -1e-9 or dropped_units > missing:
            raise SessionError("backwards/overlapping segment or inconsistent drop accounting")
        gap_s = max(0.0, gap_s)
        if not isinstance(gap_reason, str) or len(gap_reason) > 256:
            raise SessionError("invalid gap reason")
        if (missing or gap_s > 1e-9) and not gap_reason.strip():
            raise SessionError("discontinuity requires an explicit reason")
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_CHUNK_BYTES:
            raise SessionError("payload exceeds chunk budget or is empty")
        _validate_payload(source, payload, units)
        start, start_u = source.clock.at(source_start_s)
        end, end_u = source.clock.at(source_end_s)
        if end <= start:
            raise SessionError("reference interval lost positive duration to numeric precision")
        index = len(receipts)
        extension = "wav" if source.media == "pcm16-wav" else "pgm"
        return {"schema": SCHEMA + ".chunk", "index": index,
                "header_sha256": sha256(self._header_bytes),
                "previous_receipt_sha256": sha256(canonical(receipts[-1])) if receipts else None,
                "source_id": source_id, "path": f"chunk-{index:06d}.{extension}",
                "sha256": sha256(payload), "bytes": len(payload), "unit_start": unit_start,
                "units": units, "source_start_s": source_start_s, "source_end_s": source_end_s,
                "reference_start_s": start, "reference_end_s": end,
                "start_uncertainty_s": start_u, "end_uncertainty_s": end_u,
                "missing_units": missing, "dropped_units": dropped_units,
                "unexplained_missing_units": missing - dropped_units,
                "gap_source_s": gap_s, "gap_reason": gap_reason}

    def _recover(self) -> dict:
        if read_bounded(self.directory / HEADER) != self._header_bytes:
            raise SessionError("session identity changed")
        files = self._inventory()
        if sum(files.values()) > self._header["max_bytes"]:
            raise SessionError("workspace exceeds storage budget; evidence preserved")
        names = sorted(n for n in files if re.fullmatch(r"chunk-\d{6}\.json", n))
        if len(names) > self._header["max_chunks"]:
            raise SessionError("too many committed chunks")
        receipts = []
        known = {HEADER, FINAL, HALT, ".writer.lock"}
        # A crash after link but before unlink can leave two names for the same
        # already-committed inode. Keep that alias, but it is not lost evidence.
        for name in files:
            if ".pending-" in name:
                target = name.rsplit(".pending-", 1)[0]
                if target in files and os.path.samestat((self.directory / name).stat(),
                                                        (self.directory / target).stat()):
                    known.add(name)
        for index, name in enumerate(names):
            if name != f"chunk-{index:06d}.json":
                raise SessionError("missing or reordered chunk receipt")
            record = load_json(self.directory / name, 16384)
            try:
                source = self.source(record["source_id"])
                extension = "wav" if source.media == "pcm16-wav" else "pgm"
                expected_path = f"chunk-{index:06d}.{extension}"
                if record["path"] != expected_path:
                    raise SessionError("invalid chunk path")
                payload = read_bounded(self.directory / expected_path, MAX_CHUNK_BYTES)
                expected = self._record(record["source_id"], record["unit_start"], record["units"],
                                        record["source_start_s"], record["source_end_s"],
                                        record["dropped_units"], record["gap_reason"], payload, receipts)
                if canonical(record) != canonical(expected):
                    raise SessionError("chunk checksum or metadata mismatch")
                if read_bounded(self.directory / name, 16384) != canonical(record):
                    raise SessionError("receipt is not canonical")
            except (KeyError, TypeError) as exc:
                raise SessionError("invalid chunk receipt") from exc
            known.update((name, expected_path))
            receipts.append(record)
        uncommitted = sorted(set(files) - known)
        halt = load_json(self.directory / HALT, 2048) if HALT in files else None
        if halt is not None and (not isinstance(halt, dict) or set(halt) != {"reason", "hardware_verified"}
                                 or halt["reason"] not in {"byte_capacity", "chunk_capacity", "source_error"}
                                 or halt["hardware_verified"] is not False):
            raise SessionError("invalid halt record")
        result = {"schema": SCHEMA + ".segments", "session_id": self._header["session_id"],
                  "header_sha256": sha256(self._header_bytes), "hardware_verified": False,
                  "state": ("recovered_incomplete" if uncommitted else "source_failed"
                            if halt and halt["reason"] == "source_error" else "capacity_halted" if halt else "finalized"),
                  "capture_extent": "stored_segments_only; trailing_extent_not_attested",
                  "halt": halt, "uncommitted_files": uncommitted,
                  "uncommitted_artifacts": [{"path": name, "bytes": files[name],
                                             "sha256": file_sha256(self.directory / name,
                                                                   max_bytes=self._header["max_bytes"])}
                                            for name in uncommitted],
                  "segments": [{"receipt": f"chunk-{r['index']:06d}.json",
                                "receipt_sha256": sha256(canonical(r)), "path": r["path"],
                                "sha256": r["sha256"], "source_id": r["source_id"]} for r in receipts],
                  "accounting": {s.source_id: {
                      "stored_units": sum(r["units"] for r in receipts if r["source_id"] == s.source_id),
                      "missing_units": sum(r["missing_units"] for r in receipts if r["source_id"] == s.source_id),
                      "dropped_units": sum(r["dropped_units"] for r in receipts if r["source_id"] == s.source_id),
                      "gap_source_s": sum(r["gap_source_s"] for r in receipts if r["source_id"] == s.source_id)
                  } for s in self.sources}}
        if FINAL in files and canonical(load_json(self.directory / FINAL)) != canonical(result):
            raise SessionError("finalized manifest does not match committed evidence")
        return {"manifest": result, "receipts": receipts, "finalized": FINAL in files,
                "bytes_used": sum(files.values())}

    def recover(self) -> dict:
        with self._locked():
            return self._recover()

    def append(self, source_id: str, payload: bytes, *, unit_start: int, units: int,
               source_start_s: float, source_end_s: float, dropped_units: int = 0,
               gap_reason: str = "") -> dict:
        with self._locked():
            recovery = self._recover()
            manifest = recovery["manifest"]
            if recovery["finalized"] or manifest["halt"] or manifest["uncommitted_files"]:
                raise SessionError("session is closed or interrupted; recover and review, do not overwrite")
            record = self._record(source_id, unit_start, units, source_start_s, source_end_s,
                                  dropped_units, gap_reason, payload, recovery["receipts"])
            receipt = canonical(record)
            reason = None
            if len(recovery["receipts"]) >= self._header["max_chunks"]:
                reason = "chunk_capacity"
            elif (recovery["bytes_used"] + len(payload) + len(receipt)
                  + self._header["finalize_reserve_bytes"] > self._header["max_bytes"]):
                reason = "byte_capacity"
            if reason:
                publish(self.directory, HALT, canonical({"reason": reason, "hardware_verified": False}))
                raise CapacityExceeded(f"{reason}: capture halted; evidence preserved")
            publish(self.directory, record["path"], payload)
            publish(self.directory, f"chunk-{record['index']:06d}.json", receipt)
            return record

    def abort_source(self) -> None:
        """Persist a known input failure without discarding earlier chunks."""
        with self._locked():
            recovery = self._recover()
            if recovery["finalized"]:
                raise SessionError("cannot alter a finalized session")
            if not recovery["manifest"]["halt"]:
                data = canonical({"reason": "source_error", "hardware_verified": False})
                if recovery["bytes_used"] + len(data) > self._header["max_bytes"]:
                    raise CapacityExceeded("no fault-record capacity; evidence preserved")
                publish(self.directory, HALT, data)

    def finalize(self) -> dict:
        with self._locked():
            recovery = self._recover()
            if not recovery["finalized"]:
                data = canonical(recovery["manifest"])
                if recovery["bytes_used"] + len(data) > self._header["max_bytes"]:
                    raise CapacityExceeded("no finalization capacity; existing evidence preserved")
                publish(self.directory, FINAL, data)
            return recovery["manifest"]


@dataclass(frozen=True)
class AudioBlock:
    unit_start: int
    units: int
    pcm: bytes


def pcm16_wav(pcm: bytes, sample_rate_hz: int, channels: int) -> bytes:
    positive_int(sample_rate_hz, "sample rate", maximum=768000)
    positive_int(channels, "channels", maximum=16)
    if not isinstance(pcm, bytes) or not pcm or len(pcm) % (2 * channels) or len(pcm) + 44 > MAX_CHUNK_BYTES:
        raise SessionError("invalid or oversized PCM16 block")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate_hz)
        writer.writeframes(pcm)
    return buffer.getvalue()


def synthetic_audio(*, frames: int = 8000, sample_rate_hz: int = 8000,
                    channels: int = 1, chunk_frames: int = 2000, seed: int = 7) -> Iterator[AudioBlock]:
    """Integer-only deterministic fixture, not an animal sound or SPL calibration."""
    positive_int(frames, "frames", maximum=100_000_000)
    positive_int(sample_rate_hz, "sample rate", maximum=768000)
    positive_int(channels, "channels", maximum=16)
    positive_int(chunk_frames, "chunk frames", maximum=(MAX_CHUNK_BYTES - 44) // (2 * channels))
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise SessionError("seed must be uint32")
    state = seed
    for start in range(0, frames, chunk_frames):
        count = min(chunk_frames, frames - start)
        pcm = bytearray()
        for _ in range(count * channels):
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            pcm.extend(struct.pack("<h", ((state >> 16) & 8191) - 4096))
        yield AudioBlock(start, count, bytes(pcm))


def wav_blocks(path: Path | str, *, sample_rate_hz: int, channels: int,
               chunk_frames: int = 2000, max_frames: int = 100_000_000) -> Iterator[AudioBlock]:
    """Stream PCM16 WAV from a bounded regular file; reject partial/truncated input."""
    positive_int(sample_rate_hz, "sample rate", maximum=768000)
    positive_int(channels, "channels", maximum=16)
    positive_int(max_frames, "input frame budget", maximum=100_000_000)
    positive_int(chunk_frames, "chunk frames", maximum=(MAX_CHUNK_BYTES - 44) // (2 * channels))
    try:
        with regular_input(path) as stream:
            before = os.fstat(stream.fileno())
            if before.st_size > max_frames * 2 * channels + 65536:
                raise SessionError("WAV file exceeds input budget")
            with wave.open(stream, "rb") as reader:
                if (reader.getcomptype(), reader.getsampwidth(), reader.getnchannels(), reader.getframerate()) != (
                        "NONE", 2, channels, sample_rate_hz):
                    raise SessionError("expected matching uncompressed PCM16 WAV")
                frames = reader.getnframes()
                positive_int(frames, "WAV frame count", maximum=max_frames)
                for start in range(0, frames, chunk_frames):
                    count = min(chunk_frames, frames - start)
                    pcm = reader.readframes(count)
                    if len(pcm) != count * channels * 2:
                        raise SessionError("truncated WAV data")
                    yield AudioBlock(start, count, pcm)
                if reader.readframes(1):
                    raise SessionError("WAV contains an incomplete final PCM frame")
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise SessionError("WAV changed during capture")
    except (wave.Error, EOFError) as exc:
        raise SessionError(f"invalid WAV: {exc}") from exc


@contextmanager
def capture_guard(session: Session):
    try:
        yield
    except Exception as exc:
        try:
            session.abort_source()
        except (SessionError, OSError) as abort_error:
            exc.add_note(f"failure marker not written: {abort_error}; inspect preserved workspace")
        raise


def capture_audio(session: Session, source_id: str, blocks: Iterator[AudioBlock]) -> int:
    source = session.source(source_id)
    if source.media != "pcm16-wav":
        raise SessionError("audio source required")
    count = 0
    with capture_guard(session):
        for block in blocks:
            if len(block.pcm) != block.units * len(source.channels) * 2:
                raise SessionError("PCM length disagrees with frame count")
            session.append(source_id, pcm16_wav(block.pcm, source.sample_rate_hz, len(source.channels)),
                           unit_start=block.unit_start, units=block.units,
                           source_start_s=source.source_origin_s + block.unit_start / source.sample_rate_hz,
                           source_end_s=source.source_origin_s + (block.unit_start + block.units) / source.sample_rate_hz)
            count += 1
    return count


def file_sha256(path: Path | str, *, max_bytes: int = 3_200_065_536) -> str:
    positive_int(max_bytes, "file checksum budget", maximum=2**40)
    digest = hashlib.sha256()
    total = 0
    with regular_input(path) as stream:
        if os.fstat(stream.fileno()).st_size > max_bytes:
            raise SessionError("input exceeds checksum budget")
        while data := stream.read(min(1024 * 1024, max_bytes - total + 1)):
            total += len(data)
            if total > max_bytes:
                raise SessionError("input exceeds checksum budget")
            digest.update(data)
    return digest.hexdigest()


class LinuxPiCaptureAdapter:
    """Operational boundary only; not an ALSA/V4L2/GPIO driver."""

    hardware_verified = False

    def open(self, *args, **kwargs):
        raise PermissionError("live Linux/Pi capture is disabled; future authorization and hardware validation required")
