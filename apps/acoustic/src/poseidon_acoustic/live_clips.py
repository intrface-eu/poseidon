"""Bounded, file-only PCM16 clips from a closed live journal, not v1 replay.

The local detector uses nominal stored frames. It cannot establish physical
continuity, UTC, exposure, synchronization, calibration, or missing capture.
"""
from __future__ import annotations

from array import array
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys

from .detector import DetectorConfig, PCM16_SCALE, _EventStats, _WindowStats
from .errors import InputError
from .live_journal import (
    JournalFault, _configuration, _intent, _receipt, _valid_fault_observations,
    _validate_block,
)
from .live_models import (
    MAX_CHUNK_BYTES, MAX_METADATA_BYTES, SCHEMA, CapturePlanV1, CapturedBlockV1,
    LiveValidationError, canonical, digest, parse_canonical,
)

DETECTOR_VERSION = "live-nominal-normalized-rms-v1"
MANIFEST_SCHEMA = "poseidon.live-event-clips.local.v1"
POSITION_MEANING = "source-relative-nominal-stored-frames; not-physical-continuity-or-time"


class LiveClipError(ValueError):
    """Refused input, changed evidence, resource bound, or publication failure."""


class LiveClipPublicationUncertain(LiveClipError):
    """Publication failed and receipt retraction/durability is not confirmed."""

    publication_state = "uncertain"

    def __init__(self, output_dir, publication_error, cleanup_error):
        self.output_dir = output_dir
        self.publication_error = str(publication_error)
        self.cleanup_error = str(cleanup_error)
        super().__init__(f"publication uncertain for {output_dir}: receipt retraction could not be confirmed "
                         f"({cleanup_error}); original failure: {publication_error}")


def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise LiveClipError(f"{name} outside integer bounds")


@dataclass(frozen=True)
class ClipLimits:
    """Caller may tighten these ceilings, never remove them. Bytes include headers."""

    max_journal_entries: int = 2048
    max_input_bytes: int = 32 * 1024 * 1024
    max_scan_bytes: int = 80 * 1024 * 1024
    max_events: int = 64
    max_clip_frames: int = 384_000
    max_clip_bytes: int = 4 * 1024 * 1024
    max_output_bytes: int = 16 * 1024 * 1024
    max_manifest_bytes: int = 1024 * 1024

    def __post_init__(self):
        for name, ceiling in (
            ("max_journal_entries", 2048), ("max_input_bytes", 32 * 1024 * 1024),
            ("max_scan_bytes", 80 * 1024 * 1024), ("max_events", 64),
            ("max_clip_frames", 384_000), ("max_clip_bytes", 4 * 1024 * 1024),
            ("max_output_bytes", 16 * 1024 * 1024), ("max_manifest_bytes", 1024 * 1024),
        ):
            _int(getattr(self, name), name, 1, ceiling)


@dataclass(frozen=True)
class LiveEvent:
    event_id: str
    run_id: str
    source_id: str
    start_frame: int
    end_frame: int
    normalized_peak_max: float
    normalized_rms_max: float


@dataclass(frozen=True)
class LiveDetectionResult:
    events: tuple[LiveEvent, ...]
    run_id: str
    source_id: str
    frame_count: int
    sample_rate_hz: int
    channels: tuple[str, ...]
    journal_intent_sha256: str
    journal_final_sha256: str
    detector_config_json: bytes
    detector_config_id: str
    clock_relation: None = None
    physical_uncertainty_ns: None = None
    utc_start: None = None
    utc_end: None = None
    position_meaning: str = POSITION_MEANING


@dataclass(frozen=True)
class LiveClipResult:
    output_dir: Path
    manifest_sha256: str
    manifest_json: bytes
    detection: LiveDetectionResult


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _refusals():
    try:
        yield
    except LiveClipError:
        raise
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError,
            StopIteration, JournalFault, LiveValidationError, InputError) as exc:
        raise LiveClipError(f"live clip refused: {exc}") from exc


class _Snapshot:
    """Read regular files through a pinned directory, without a writer lease.

    All artifact bytes, including unadopted orphans, count against the input and
    scan budgets. Identity checks include ctime so write-and-restore is refused.
    """

    def __init__(self, path, limits):
        self.path = Path(path).resolve(strict=True)
        self.limits = limits
        self.scanned = 0
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self.root = _identity(os.fstat(self.fd))
            self.inventory = self._inventory()
            # Reserve both complete byte passes (+ one EOF probe per file) before
            # allocating any file. This is an input budget, independent of clips.
            scan_cost = 2 * sum(info[3] + 1 for info in self.inventory.values())
            if scan_cost > limits.max_scan_bytes:
                raise LiveClipError("journal scan byte budget")
            self.files = {name: self.read(name) for name in sorted(self.inventory)}
            self.hashes = {name: digest(data) for name, data in self.files.items()}
            self.assert_inventory()
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def _inventory(self):
        if _identity(os.stat(self.path, follow_symlinks=False)) != self.root:
            raise LiveClipError("journal directory changed")
        result = {}
        total = 0
        with os.scandir(self.fd) as entries:
            for entry in entries:
                if len(result) >= self.limits.max_journal_entries:
                    raise LiveClipError("journal entry budget")
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise LiveClipError("journal artifacts must be regular files")
                maximum = 16 * 1024 * 1024 if entry.name == ".reserve" else MAX_CHUNK_BYTES
                if entry.name.endswith(".json"):
                    maximum = MAX_METADATA_BYTES
                if info.st_size > maximum:
                    raise LiveClipError("journal file size bound before open")
                total += info.st_size
                if total > self.limits.max_input_bytes:
                    raise LiveClipError("journal input byte budget")
                result[entry.name] = _identity(info)
        return result

    def assert_inventory(self):
        if self._inventory() != self.inventory or _identity(os.fstat(self.fd)) != self.root:
            raise LiveClipError("journal artifacts changed during read")

    def read(self, name):
        expected = self.inventory[name]
        size = expected[3]
        if self.scanned + size + 1 > self.limits.max_scan_bytes:
            raise LiveClipError("journal scan byte budget")
        self.scanned += size + 1
        if _identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)) != expected:
            raise LiveClipError("journal file changed before read")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        try:
            if _identity(os.fstat(fd)) != expected:
                raise LiveClipError("journal file changed on open")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(size + 1)
            if len(raw) != size or _identity(os.fstat(fd)) != expected:
                raise LiveClipError("journal file changed during read")
            if _identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)) != expected:
                raise LiveClipError("journal file replaced during read")
            return raw
        finally:
            os.close(fd)

    def verify_again(self):
        self.assert_inventory()
        for name in sorted(self.inventory):
            if digest(self.read(name)) != self.hashes[name]:
                raise LiveClipError("journal bytes changed during extraction")
        self.assert_inventory()


@dataclass(frozen=True)
class _Journal:
    snapshot: _Snapshot
    plan: CapturePlanV1
    intent: dict
    final: dict
    receipts: tuple[dict, ...]
    orphans: tuple[str, ...]


def _validate(snapshot):
    """Validate the bounded immutable snapshot using the accepted pure contracts.

    Deliberately does not call LiveJournal.recover, _open_owner, or the path-based
    verifier: that verifier takes its scan bounds from mutable on-disk intent.
    """
    files = snapshot.files
    intent = parse_canonical(files["intent.json"])
    plan = CapturePlanV1.from_bytes(canonical(intent["plan"]))
    if files["intent.json"] != canonical(_intent(plan)):
        raise LiveClipError("intent mismatch")
    if "final.json" not in files:
        raise LiveClipError("journal must already be sealed or recovered")
    final = parse_canonical(files["final.json"])
    if final.get("integrity_error") is not None:
        raise LiveClipError("journal reports an integrity error")
    if len(files) > plan.limits.max_chunks * 3 + 64:
        raise LiveClipError("journal artifact-count bound")
    if sum(map(len, files.values())) > plan.limits.output_bytes + plan.limits.max_chunk_bytes + MAX_METADATA_BYTES:
        raise LiveClipError("journal storage bound")
    if files[".owner.lock"] != b"":
        raise LiveClipError("invalid ownership artifact")
    consumed = {"intent.json", ".owner.lock", "final.json"}
    if ".reserve" in files:
        reserve = files[".reserve"]
        if len(reserve) != plan.limits.reserve_bytes or any(reserve):
            raise LiveClipError("invalid reserve artifact")
        consumed.add(".reserve")
    configs = {}
    starts = set()
    for source in plan.sources:
        name = f"config-{source.source_id}.json"
        if name in files:
            _configuration(plan, source.source_id, files[name])
            configs[source.source_id] = digest(files[name])
            consumed.add(name)
    if "start-request.json" in files:
        if files["start-request.json"] != canonical({"kind": "start-request", "plan_sha256": plan.sha256}):
            raise LiveClipError("start request mismatch")
        consumed.add("start-request.json")
    for source in plan.sources:
        name = f"start-{source.source_id}.json"
        if name in files:
            start = parse_canonical(files[name])
            timestamp = start.get("host_monotonic_ns")
            if (source.source_id not in configs or "start-request.json" not in consumed or
                    type(timestamp) is not int or timestamp < 0 or files[name] != canonical({
                        "kind": "start-return", "source_id": source.source_id,
                        "host_monotonic_ns": timestamp})):
                raise LiveClipError("start return mismatch")
            starts.add(source.source_id)
            consumed.add(name)
    positions = {s.source_id: 0 for s in plan.sources}
    sequences = {sid: None for sid in positions}
    clocks = dict(sequences)
    receipts = []
    previous = None
    payload_bytes = 0
    # Never iterate a declared max_chunks of up to one million. The admitted
    # artifact inventory supplies the smaller bound.
    for index in range(min(plan.limits.max_chunks, len(files))):
        name = f"receipt-{index:09d}.json"
        if name not in files:
            break
        raw = files[name]
        record = parse_canonical(raw)
        sid = record["source_id"]
        source = next(s for s in plan.sources if s.source_id == sid)
        payload_name = f"payload-{index:09d}.bin"
        block = CapturedBlockV1(files[payload_name], record["units"], canonical(record["raw"]), record["sequence"])
        _, clock = _validate_block(source, plan.limits, block, sequences[sid], clocks[sid])
        expected = _receipt(plan, index, previous, sid, configs[sid], positions[sid], block)
        if sid not in starts or raw != canonical(expected):
            raise LiveClipError("receipt binding/chain/position mismatch")
        consumed.update((name, payload_name))
        previous = digest(raw)
        positions[sid] += block.units
        sequences[sid], clocks[sid] = block.sequence, clock
        payload_bytes += len(block.payload)
        receipts.append(record)
    orphans = tuple(sorted(set(files) - consumed))
    if any(name.startswith("receipt-") for name in orphans):
        raise LiveClipError("receipt outside intact committed chain")
    if (not _valid_fault_observations(final.get("fault_domain"), final.get("native_code"),
                                     final.get("application_discarded_chunks"),
                                     final.get("observed_queue_rejected_chunks")) or
            type(final.get("reason")) is not str or not 0 < len(final["reason"]) <= 1024):
        raise LiveClipError("invalid final observations")
    expected_final = {
        "schema": SCHEMA, "kind": "final", "plan_sha256": plan.sha256,
        "reason": final["reason"], "fault_domain": final["fault_domain"],
        "native_code": final["native_code"], "writer_closed": True,
        "committed_chunks": len(receipts), "committed_bytes": payload_bytes,
        "last_receipt_sha256": previous, "positions": positions, "integrity_error": None,
        "orphan_count": len(orphans), "orphan_names_first_64": list(orphans[:64]),
        "orphan_inventory_sha256": digest(canonical({"names": orphans})),
        "application_discarded_chunks": final["application_discarded_chunks"],
        "observed_queue_rejected_chunks": final["observed_queue_rejected_chunks"],
        "queue_rejection_coverage": "received-worker-reports-only; not-all-application-or-physical-loss",
        "physical_loss_units": None, "source_tail_units": {s.source_id: None for s in plan.sources},
        "planned_acquisition_complete": False, "clock_relation": None,
        "physical_uncertainty_ns": None, "utc_end": None,
        "device_access_occurred": False if plan.synthetic else None,
        "device_access_claim_scope": "see-per-source-configuration; failed-open-may-have-accessed-device",
    }
    if files["final.json"] != canonical(expected_final):
        raise LiveClipError("final prefix/claims mismatch")
    return _Journal(snapshot, plan, intent, final, tuple(receipts), orphans)


def _arguments(source_id, config, limits):
    if type(source_id) is not str or not 1 <= len(source_id) <= 64:
        raise LiveClipError("explicit source_id required")
    if type(config) is not DetectorConfig or type(limits) is not ClipLimits:
        raise LiveClipError("validated DetectorConfig and ClipLimits required")
    # Revalidate even frozen objects: Python callers can bypass dataclass guards.
    DetectorConfig(config.threshold, config.window_ms)
    ClipLimits(**asdict(limits))


def _detect(journal, source_id, config, limits):
    source = next((s for s in journal.plan.sources if s.source_id == source_id), None)
    if source is None or source.kind != "audio":
        raise LiveClipError("selected source must be journal PCM16 audio")
    rate, channels = source.sample_rate_hz, len(source.channels)
    config_bytes = canonical({**config.to_dict(rate), "detector_version": DETECTOR_VERSION,
                              "position_meaning": POSITION_MEANING})
    config_id = "livecfg_" + digest(config_bytes)
    hashes = journal.snapshot.hashes
    run_id = "liverun_" + digest(canonical({
        "journal_intent_sha256": hashes["intent.json"],
        "journal_final_sha256": hashes["final.json"], "source_id": source_id,
        "source_plan_sha256": source.sha256, "detector_config_id": config_id,
    }))
    window_frames = config.window_frames(rate)
    window = _WindowStats.empty(channels)
    active = None
    events = []
    position = 0
    window_start = 0

    def finish_event():
        nonlocal active
        if active is None:
            return
        if len(events) >= limits.max_events:
            raise LiveClipError("detector event count budget")
        event_id = "liveevt_" + digest(canonical({"run_id": run_id, "source_id": source_id,
                                                "start_frame": active.start_frame,
                                                "end_frame": active.end_frame}))
        events.append(LiveEvent(event_id, run_id, source_id, active.start_frame, active.end_frame,
                                max(active.peaks) / PCM16_SCALE,
                                max(math.sqrt(v / active.frame_count) / PCM16_SCALE
                                    for v in active.sums_of_squares)))
        active = None

    def finish_window():
        nonlocal active, window, window_start
        if not window.frame_count:
            return
        rms = max(math.sqrt(v / window.frame_count) / PCM16_SCALE for v in window.sums_of_squares)
        if rms >= config.threshold:
            if active is None:
                active = _EventStats.from_window(window_start, position, window)
            else:
                active.append_window(position, window)
        else:
            finish_event()
        window = _WindowStats.empty(channels)
        window_start = position

    for receipt in journal.receipts:
        if receipt["source_id"] != source_id:
            continue
        payload = journal.snapshot.files[receipt["payload_name"]]
        # Decode in bounded blocks; windows carry across chunks of this source,
        # never across another source or an invalid receipt/sequence/clock chain.
        block_bytes = 4096 * channels * 2
        for start in range(0, len(payload), block_bytes):
            samples = array("h")
            samples.frombytes(payload[start:start + block_bytes])
            if sys.byteorder != "little":
                samples.byteswap()
            for offset in range(0, len(samples), channels):
                for channel in range(channels):
                    sample = samples[offset + channel]
                    window.sums_of_squares[channel] += sample * sample
                    window.peaks[channel] = max(window.peaks[channel], abs(sample))
                position += 1
                window.frame_count += 1
                if window.frame_count == window_frames:
                    finish_window()
    finish_window()
    finish_event()
    return LiveDetectionResult(tuple(events), run_id, source_id, position, rate, source.channels,
                               hashes["intent.json"], hashes["final.json"], config_bytes, config_id)


def detect_live_journal(journal_path, source_id, config=DetectorConfig(), *, limits=ClipLimits()):
    """Return source-bound local events after two bounded, read-only byte passes."""
    with _refusals():
        _arguments(source_id, config, limits)
        snapshot = _Snapshot(journal_path, limits)
        try:
            result = _detect(_validate(snapshot), source_id, config, limits)
            snapshot.verify_again()
            return result
        finally:
            snapshot.close()


def _bounded_canonical(value, maximum):
    """Do not allocate an oversized serialized manifest before rejecting it."""
    result = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    for part in encoder.iterencode(value):
        if len(result) + len(part) + 1 > maximum:
            raise LiveClipError("manifest/aggregate output byte budget")
        result.extend(part.encode("ascii"))
    result.extend(b"\n")
    return bytes(result)


def _wav_header(payload_bytes, channels, sample_rate):
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + payload_bytes, b"WAVE", b"fmt ",
                       16, 1, channels, sample_rate, sample_rate * channels * 2,
                       channels * 2, 16, b"data", payload_bytes)


def _destination(source_path, output_dir):
    requested = Path(output_dir)
    if requested.name in ("", ".", ".."):
        raise LiveClipError("new named output directory required")
    parent = requested.parent.resolve(strict=True)
    output = parent / requested.name
    resolved = output.resolve(strict=False)
    if resolved == source_path or source_path in resolved.parents or resolved in source_path.parents:
        raise LiveClipError("output/source overlap, including symlink aliases")
    if os.path.lexists(output):
        raise LiveClipError("output already exists; overwrite refused")
    return output


def _write_new(fd, name, data):
    selected = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(selected, "wb", closefd=False) as stream:
            if stream.write(data) != len(data):
                raise LiveClipError("short output write")
            stream.flush()
            os.fsync(selected)
    finally:
        os.close(selected)


def _verify_output(fd, name, expected):
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_size != len(expected):
        raise LiveClipError("output bytes/type mismatch")
    selected = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        if _identity(os.fstat(selected)) != _identity(info):
            raise LiveClipError("output identity changed")
        with os.fdopen(selected, "rb", closefd=False) as stream:
            actual = stream.read(len(expected) + 1)
        if actual != expected or _identity(os.fstat(selected)) != _identity(info):
            raise LiveClipError("output bytes changed")
        return _identity(info)
    finally:
        os.close(selected)


def _assert_receipt_absent(fd):
    try:
        os.stat("manifest.json", dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise LiveClipError("manifest.json remains or was replaced; retained")


def _retract_owned_receipt(fd, parent_fd, owned_inode, manifest):
    """Retract only the verified inode/bytes we linked, never an unknown receipt.

    A successful unlink alone does not establish durable rollback. Sync both
    directories and confirm absence; any failure makes publication uncertain.
    Leave pending manifests, WAVs, and foreign evidence untouched.
    """
    try:
        current = os.stat("manifest.json", dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        current = None
    if current is not None:
        if not stat.S_ISREG(current.st_mode) or _identity(current)[:2] != owned_inode:
            raise LiveClipError("manifest.json replaced by an unknown receipt; retained")
        identity = _verify_output(fd, "manifest.json", manifest)
        if (identity[:2] != owned_inode or
                _identity(os.stat("manifest.json", dir_fd=fd, follow_symlinks=False)) != identity):
            raise LiveClipError("manifest.json changed during retraction check; retained")
        os.unlink("manifest.json", dir_fd=fd)
    _assert_receipt_absent(fd)
    os.fsync(fd)
    os.fsync(parent_fd)
    _assert_receipt_absent(fd)


def _publish(output, journal, wavs, manifest):
    parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    out_fd = None
    try:
        parent_identity = _identity(os.fstat(parent_fd))[:3]
        journal.snapshot.assert_inventory()
        if parent_identity[:2] == journal.snapshot.root[:2]:
            raise LiveClipError("output/source directory identity overlap")
        os.mkdir(output.name, mode=0o700, dir_fd=parent_fd)
        out_fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        output_identity = _identity(os.fstat(out_fd))[:3]
        if output_identity[:2] == journal.snapshot.root[:2]:
            raise LiveClipError("output/source directory identity overlap")
        journal.snapshot.assert_inventory()
        for name, data in wavs:
            _write_new(out_fd, name, data)
        # A pending manifest is not a success receipt. Only manifest.json commits.
        _write_new(out_fd, ".pending-manifest.json", manifest)
        verified = {name: _verify_output(out_fd, name, data) for name, data in wavs}
        verified[".pending-manifest.json"] = _verify_output(out_fd, ".pending-manifest.json", manifest)
        journal.snapshot.verify_again()
        if (_identity(os.stat(output.parent, follow_symlinks=False))[:3] != parent_identity or
                _identity(os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False))[:3] != output_identity):
            raise LiveClipError("output directory changed before publication")
        for name, identity in verified.items():
            if _identity(os.stat(name, dir_fd=out_fd, follow_symlinks=False)) != identity:
                raise LiveClipError("output artifact changed before publication")
        owned_inode = verified[".pending-manifest.json"][:2]
        try:
            os.link(".pending-manifest.json", "manifest.json", src_dir_fd=out_fd, dst_dir_fd=out_fd,
                    follow_symlinks=False)
            os.unlink(".pending-manifest.json", dir_fd=out_fd)
            os.fsync(out_fd)
            os.fsync(parent_fd)
        except BaseException as publication_error:
            try:
                _retract_owned_receipt(out_fd, parent_fd, owned_inode, manifest)
            except BaseException as cleanup_error:
                raise LiveClipPublicationUncertain(output, publication_error, cleanup_error) from publication_error
            raise
    finally:
        if out_fd is not None:
            os.close(out_fd)
        os.close(parent_fd)


def extract_live_clips(journal_path, output_dir, source_id, config=DetectorConfig(), *,
                       pre_frames=0, post_frames=0, event_ids=None, limits=ClipLimits()):
    """Generate detection internally and publish bounded WAVs plus manifest last.

    event_ids, when supplied, is a nonempty tuple selecting this exact run only.
    No caller-supplied event spans/results or replay manifests are accepted.
    Failure retains partial output and retracts only an owned success receipt.
    LiveClipPublicationUncertain means receipt absence/durability is unconfirmed.
    Prior output and foreign receipt replacements are never overwritten.
    """
    with _refusals():
        _arguments(source_id, config, limits)
        _int(pre_frames, "pre_frames", 0, limits.max_clip_frames)
        _int(post_frames, "post_frames", 0, limits.max_clip_frames)
        if event_ids is not None:
            if (type(event_ids) is not tuple or not 1 <= len(event_ids) <= limits.max_events or
                    any(type(item) is not str or len(item) != 72 or not item.startswith("liveevt_")
                        or any(c not in "0123456789abcdef" for c in item[8:]) for item in event_ids) or
                    len(set(event_ids)) != len(event_ids)):
                raise LiveClipError("event_ids must be a bounded unique tuple of local event IDs")
        snapshot = _Snapshot(journal_path, limits)
        try:
            output = _destination(snapshot.path, output_dir)
            journal = _validate(snapshot)
            detection = _detect(journal, source_id, config, limits)
            known = {event.event_id for event in detection.events}
            if event_ids is not None and not set(event_ids) <= known:
                raise LiveClipError("event selector does not belong to this source/journal/config run")
            events = [event for event in detection.events if event_ids is None or event.event_id in event_ids]
            align = len(detection.channels) * 2
            spans = []
            wav_total = 0
            for event in events:
                start = max(0, event.start_frame - pre_frames)
                end = min(detection.frame_count, event.end_frame + post_frames)
                size = (end - start) * align + 44
                if end - start > limits.max_clip_frames or size > limits.max_clip_bytes:
                    raise LiveClipError("excerpt frame/full WAV byte budget")
                wav_total += size
                if wav_total > limits.max_output_bytes:
                    raise LiveClipError("aggregate output byte budget")
                spans.append((event, start, end))
            manifest_bound = min(limits.max_manifest_bytes, limits.max_output_bytes - wav_total)
            segment_budget = manifest_bound
            wavs, clips = [], []
            source = next(s for s in journal.plan.sources if s.source_id == source_id)
            # Every excerpt is admitted before creating PCM/WAV buffers or output.
            for index, (event, start, end) in enumerate(spans):
                segments, parts = [], []
                for receipt in journal.receipts:
                    if receipt["source_id"] != source_id:
                        continue
                    left, right = max(start, receipt["position"]), min(end, receipt["position"] + receipt["units"])
                    if left >= right:
                        continue
                    offset, stop = (left - receipt["position"]) * align, (right - receipt["position"]) * align
                    data = snapshot.files[receipt["payload_name"]][offset:stop]
                    parts.append(data)
                    receipt_name = f"receipt-{receipt['index']:09d}.json"
                    segment = {
                        "receipt_index": receipt["index"], "receipt_name": receipt_name,
                        "receipt_sha256": snapshot.hashes[receipt_name],
                        "previous_receipt_sha256": receipt["previous_receipt_sha256"],
                        "payload_name": receipt["payload_name"], "payload_sha256": receipt["payload_sha256"],
                        "configuration_sha256": receipt["configuration_sha256"], "source_id": source_id,
                        "chunk_start_frame": receipt["position"], "chunk_end_frame": receipt["position"] + receipt["units"],
                        "source_start_frame": left, "source_end_frame": right,
                        "chunk_frame_start": left - receipt["position"], "chunk_frame_end": right - receipt["position"],
                        "clip_frame_start": left - start, "clip_frame_end": right - start,
                        "payload_byte_start": offset, "payload_byte_end": stop, "copied_pcm_sha256": digest(data),
                        "sequence": receipt["sequence"], "raw": receipt["raw"],
                        **{key: receipt[key] for key in ("clock_relation", "clock_quality", "physical_uncertainty_ns",
                                                        "utc_start", "utc_end", "exposure_start", "exposure_end",
                                                        "physical_loss_units")},
                    }
                    # Bound duplicated receipt metadata before retaining a segment
                    # per overlapping clip. The final streaming encode also counts
                    # all enclosing objects, hashes and coverage declarations.
                    segment_budget -= len(_bounded_canonical(segment, segment_budget))
                    segments.append(segment)
                pcm = b"".join(parts)
                if len(pcm) != (end - start) * align:
                    raise LiveClipError("excerpt nominal frame coverage mismatch")
                wav = _wav_header(len(pcm), len(detection.channels), detection.sample_rate_hz) + pcm
                name = f"clip-{index:03d}.wav"
                wavs.append((name, wav))
                clips.append({
                    "event": asdict(event), "wav_name": name, "wav_bytes": len(wav), "wav_sha256": digest(wav),
                    "pcm_bytes": len(pcm), "pcm_sha256": digest(pcm), "frame_count": end - start,
                    "source_start_frame": start, "source_end_frame": end,
                    "requested_pre_frames": pre_frames, "requested_post_frames": post_frames,
                    "included_pre_frames": event.start_frame - start, "included_post_frames": end - event.end_frame,
                    "pre_window_clipped_frames": max(0, pre_frames - event.start_frame),
                    "post_window_clipped_frames": max(0, event.end_frame + post_frames - detection.frame_count),
                    "window_clipping_meaning": "outside-committed-nominal-prefix; not-measured-physical-loss",
                    "segments": segments,
                })
            document = {
                "schema": MANIFEST_SCHEMA, "kind": "committed-live-event-clips", "source_id": source_id,
                "capture_id": journal.plan.capture_id, "plan_sha256": journal.plan.sha256,
                "source_plan_sha256": source.sha256, "source_plan": source.to_dict(),
                "journal_intent_sha256": snapshot.hashes["intent.json"],
                "journal_final_sha256": snapshot.hashes["final.json"],
                "journal_last_receipt_sha256": journal.final["last_receipt_sha256"],
                "journal_artifact_sha256": snapshot.hashes, "journal_final": journal.final,
                "orphan_names": journal.orphans, "orphan_bytes_adopted": False,
                "detector_version": DETECTOR_VERSION, "detector_config": parse_canonical(detection.detector_config_json),
                "detector_config_id": detection.detector_config_id, "run_id": detection.run_id,
                "detected_event_count": len(detection.events), "selected_event_count": len(events),
                "source_frame_count": detection.frame_count, "sample_rate_hz": detection.sample_rate_hz,
                "format": "PCM16_LE", "channels": source.channels, "channel_roles": source.channel_roles,
                "position_meaning": POSITION_MEANING, "clock_relation": journal.intent["clock_relation"],
                "physical_uncertainty_ns": journal.intent["physical_uncertainty_ns"],
                "utc_start": journal.intent["utc_start"], "utc_end": journal.final["utc_end"],
                "calibration_status": "uncalibrated", "amplitude_units": "normalized_pcm16_full_scale",
                "provenance": source.provenance, "extraction_device_access_occurred": False,
                "emission_enabled": False, "resampled": False, "mixed": False, "gap_filled": False,
                "limits": asdict(limits), "input_artifact_bytes": sum(map(len, snapshot.files.values())),
                "input_scan_byte_ceiling": limits.max_scan_bytes, "clips": clips,
            }
            manifest = _bounded_canonical(document, manifest_bound)
            _publish(output, journal, wavs, manifest)
            return LiveClipResult(output, digest(manifest), manifest, detection)
        finally:
            snapshot.close()
