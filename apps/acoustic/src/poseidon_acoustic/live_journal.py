"""Append-only live evidence, separate from Session/ClockMap and legacy formats.

Payload publication precedes a chained receipt. Only the receipt commits a chunk.
Runtime state is incremental; recovery/finalization each perform one bounded scan.
"""
from __future__ import annotations
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import secrets
import stat

from .live_models import (SCHEMA, MAX_METADATA_BYTES, CapturePlanV1, CapturedBlockV1,
                          LiveValidationError, canonical, digest, parse_canonical)


class JournalFault(RuntimeError):
    pass


def _valid_fault_observations(domain, native_code, discarded, rejected):
    return ((domain is None or (type(domain) is str and 0 < len(domain) <= 128)) and
            (native_code is None or (type(native_code) is int and -(2**63) <= native_code < 2**63)) and
            all(value is None or (type(value) is int and 0 <= value < 2**63) for value in (discarded, rejected)))


def _open_owner(path: Path, *, create: bool = False) -> int:
    """Hold one exclusive file description; duplicates release ownership by close only."""
    root = os.lstat(path)
    if not stat.S_ISDIR(root.st_mode):
        raise JournalFault("journal directory required")
    selected = path / ".owner.lock"
    before = None if create else os.lstat(selected)
    if before is not None and (not stat.S_ISREG(before.st_mode) or before.st_size != 0):
        raise JournalFault("invalid journal ownership artifact before open")
    flags = os.O_RDWR if create else os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(selected, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size != 0 or
                (before is not None and (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino))):
            raise JournalFault("journal ownership artifact changed")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise JournalFault("journal has an active owner; recovery refused") from exc
        current_root, current_lock = os.lstat(path), os.lstat(selected)
        if (not stat.S_ISDIR(current_root.st_mode) or
                (current_root.st_dev, current_root.st_ino) != (root.st_dev, root.st_ino) or
                not stat.S_ISREG(current_lock.st_mode) or current_lock.st_size != 0 or
                (current_lock.st_dev, current_lock.st_ino) != (info.st_dev, info.st_ino)):
            raise JournalFault("journal directory/ownership artifact replaced during acquisition")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish(path: Path, name: str, data: bytes) -> None:
    """No replacement. Failed temporaries remain evidence rather than being adopted."""
    temporary = path / (".pending-" + secrets.token_hex(12))
    with temporary.open("xb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.link(temporary, path / name, follow_symlinks=False)
    temporary.unlink()
    _sync_dir(path)


def _read(path: Path, name: str, maximum: int) -> bytes:
    if "/" in name or name in (".", ".."):
        raise JournalFault("invalid local journal name")
    before = os.lstat(path / name)
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise JournalFault("journal file type/size bound before open")
    fd = os.open(path / name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > maximum or
                (info.st_dev, info.st_ino, info.st_size) != (before.st_dev, before.st_ino, before.st_size)):
            raise JournalFault("journal file type/size/identity changed")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise JournalFault("journal read bound")
        return data
    finally:
        os.close(fd)


def _reserve_identity(path: Path, plan: CapturePlanV1):
    """Recognize only the expected regular, exact-size zero-filled reserve."""
    try:
        before = os.lstat(path / ".reserve")
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode) or before.st_size != plan.limits.reserve_bytes:
        raise JournalFault("unknown reserve replacement; retained without opening or deletion")
    data = _read(path, ".reserve", plan.limits.reserve_bytes)
    after = os.lstat(path / ".reserve")
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if (len(data) != plan.limits.reserve_bytes or any(data) or not stat.S_ISREG(after.st_mode) or
            identity(before) != identity(after)):
        raise JournalFault("reserve content/identity mismatch; replacement retained")
    return identity(after)


def _configuration(plan, source_id, raw):
    config = parse_canonical(raw)
    source = next((s for s in plan.sources if s.source_id == source_id), None)
    if source is None or (config.get("source_id"), config.get("source_plan_sha256"), config.get("format")) != (source_id, source.sha256, source.format):
        raise JournalFault("configuration/source mismatch")
    if config.get("synthetic") is not plan.synthetic or config.get("device_access_occurred") is not (not plan.synthetic):
        raise JournalFault("configuration provenance mismatch")
    return config


def _validate_block(source, limits, block, previous_sequence, previous_clock):
    if type(block) is not CapturedBlockV1 or len(block.payload) > limits.max_chunk_bytes:
        raise JournalFault("invalid/oversize block")
    if source.kind == "audio":
        if block.units > limits.chunk_frames or len(block.payload) != block.units * len(source.channels) * 2:
            raise JournalFault("PCM short-read frame/byte mismatch")
    elif block.units != 1 or len(block.payload) != source.width * source.height * 2:
        raise JournalFault("YUYV active-frame byte mismatch")
    if source.kind == "video" and block.sequence is None:
        raise JournalFault("video sequence unknown")
    if previous_sequence is not None and block.sequence != (previous_sequence + 1) % 2**32:
        raise JournalFault("sequence discontinuity")
    raw = parse_canonical(block.raw_metadata_json)
    clock = tuple(raw.get(key) for key in ("clock_domain", "clock_generation", "timestamp_type"))
    if previous_clock is not None and clock != previous_clock:
        raise JournalFault("clock domain/generation/type changed")
    return raw, clock


@dataclass(frozen=True)
class CommittedChunkReceipt:
    index: int
    source_id: str
    payload_sha256: str
    receipt_sha256: str
    canonical_bytes: bytes


@dataclass(frozen=True)
class VerifiedLiveJournalView:
    capture_id: str
    plan_sha256: str
    committed_chunks: int
    committed_bytes: int
    last_receipt_sha256: str | None
    positions: tuple[tuple[str, int], ...]
    orphan_names: tuple[str, ...]
    integrity_error: str | None
    closed: bool
    final_json: bytes | None


def verify_live_journal(path: str | Path) -> VerifiedLiveJournalView:
    """File-only local-directory verifier; never loads a driver or adopts artifacts."""
    path = Path(path)
    header = parse_canonical(_read(path, "intent.json", MAX_METADATA_BYTES))
    if header.get("schema") != SCHEMA:
        raise JournalFault("wrong journal family")
    plan = CapturePlanV1.from_bytes(canonical(header["plan"]))
    if canonical(header) != canonical(_intent(plan)):
        raise JournalFault("intent mismatch")
    # Enumerate only this admitted journal, never device paths. Bound retained names.
    names = []
    total_size = 0
    with os.scandir(path) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > plan.limits.max_chunks * 3 + 64:
                raise JournalFault("journal artifact-count bound")
            total_size += entry.stat(follow_symlinks=False).st_size
            if total_size > plan.limits.output_bytes + plan.limits.max_chunk_bytes + MAX_METADATA_BYTES:
                raise JournalFault("journal storage bound")
    available = set(names)
    if _read(path, ".owner.lock", 0) != b"":
        raise JournalFault("invalid journal ownership artifact")
    consumed = {"intent.json", ".owner.lock"}
    if ".reserve" in available:
        if _reserve_identity(path, plan) is None:
            raise JournalFault("reserve disappeared during verification")
        consumed.add(".reserve")
    configurations = {}
    error = None
    for source in plan.sources:
        name = f"config-{source.source_id}.json"
        if name in available:
            try:
                data = _read(path, name, MAX_METADATA_BYTES)
                _configuration(plan, source.source_id, data)
                configurations[source.source_id] = digest(data)
                consumed.add(name)
            except (OSError, ValueError, JournalFault) as exc:
                error = "configuration integrity: " + str(exc)
    if "start-request.json" in available:
        request = parse_canonical(_read(path, "start-request.json", MAX_METADATA_BYTES))
        if request != {"kind": "start-request", "plan_sha256": plan.sha256}:
            raise JournalFault("start request mismatch")
        consumed.add("start-request.json")
    starts = set()
    for source in plan.sources:
        name = f"start-{source.source_id}.json"
        if name in available:
            start = parse_canonical(_read(path, name, MAX_METADATA_BYTES))
            if (start.get("kind") != "start-return" or start.get("source_id") != source.source_id or
                    source.source_id not in configurations or "start-request.json" not in consumed or
                    type(start.get("host_monotonic_ns")) is not int or start["host_monotonic_ns"] < 0 or
                    set(start) != {"kind", "source_id", "host_monotonic_ns"}):
                raise JournalFault("start return mismatch")
            starts.add(source.source_id)
            consumed.add(name)
    positions = {s.source_id: 0 for s in plan.sources}
    sequences = {s.source_id: None for s in plan.sources}
    clocks = {s.source_id: None for s in plan.sources}
    previous, count, payload_bytes = None, 0, 0
    for index in range(plan.limits.max_chunks):
        name = f"receipt-{index:09d}.json"
        if name not in available:
            if any(n.startswith("receipt-") and n > name for n in available):
                error = error or "missing receipt in committed chain"
            break
        if error:
            break
        try:
            raw = _read(path, name, MAX_METADATA_BYTES)
            record = parse_canonical(raw)
            sid = record["source_id"]
            source = next(s for s in plan.sources if s.source_id == sid)
            payload_name = f"payload-{index:09d}.bin"
            payload = _read(path, payload_name, plan.limits.max_chunk_bytes)
            block = CapturedBlockV1(payload, record["units"], canonical(record["raw"]), record["sequence"])
            _, clock = _validate_block(source, plan.limits, block, sequences[sid], clocks[sid])
            expected = _receipt(plan, index, previous, source.source_id, configurations[sid],
                                positions[sid], block)
            if raw != canonical(expected) or sid not in starts:
                raise JournalFault("receipt binding/chain/position mismatch")
            consumed.update((name, payload_name))
            previous = digest(raw)
            positions[sid] += block.units
            sequences[sid], clocks[sid] = block.sequence, clock
            count += 1
            payload_bytes += len(payload)
        except (OSError, ValueError, KeyError, StopIteration, JournalFault) as exc:
            error = "receipt integrity: " + str(exc)
            break
    final_json = None
    closed = False
    if "final.json" in available:
        final_json = _read(path, "final.json", MAX_METADATA_BYTES)
        final = parse_canonical(final_json)
        expected_orphans = tuple(sorted(available - consumed - {"final.json"}))
        final_keys = {"schema", "kind", "plan_sha256", "reason", "fault_domain", "native_code", "writer_closed",
                      "committed_chunks", "committed_bytes", "last_receipt_sha256", "positions", "integrity_error",
                      "orphan_count", "orphan_names_first_64", "orphan_inventory_sha256", "application_discarded_chunks",
                      "observed_queue_rejected_chunks", "queue_rejection_coverage",
                      "physical_loss_units", "source_tail_units", "planned_acquisition_complete", "clock_relation",
                      "physical_uncertainty_ns", "utc_end", "device_access_occurred", "device_access_claim_scope"}
        if (set(final) != final_keys or
                not _valid_fault_observations(final.get("fault_domain"), final.get("native_code"),
                                              final.get("application_discarded_chunks"), final.get("observed_queue_rejected_chunks")) or
                final.get("queue_rejection_coverage") != "received-worker-reports-only; not-all-application-or-physical-loss" or
                type(final.get("committed_chunks")) is not int or
                type(final.get("committed_bytes")) is not int or type(final.get("reason")) is not str or
                not 0 < len(final["reason"]) <= 1024 or final.get("writer_closed") is not True or
                final.get("clock_relation") is not None or final.get("physical_uncertainty_ns") is not None or
                final.get("utc_end") is not None or final.get("device_access_occurred") is not (False if plan.synthetic else None) or
                final.get("integrity_error") != error or
                final.get("orphan_count") != len(expected_orphans) or
                final.get("orphan_names_first_64") != list(expected_orphans[:64]) or
                final.get("orphan_inventory_sha256") != digest(canonical({"names": expected_orphans})) or
                final.get("schema") != SCHEMA or final.get("kind") != "final" or
                final.get("plan_sha256") != plan.sha256 or final.get("committed_chunks") != count or
                final.get("committed_bytes") != payload_bytes or final.get("last_receipt_sha256") != previous or
                final.get("positions") != positions or final.get("physical_loss_units") is not None or
                final.get("planned_acquisition_complete") is not False or
                final.get("source_tail_units") != {s.source_id: None for s in plan.sources}):
            error = error or "final prefix/claims mismatch"
        else:
            closed = True
            consumed.add("final.json")
    orphans = tuple(sorted(available - consumed))
    return VerifiedLiveJournalView(plan.capture_id, plan.sha256, count, payload_bytes, previous,
                                   tuple(sorted(positions.items())), orphans, error, closed, final_json)


def _intent(plan):
    return {"schema": SCHEMA, "kind": "intent", "plan": plan.to_dict(), "plan_sha256": plan.sha256,
            "ingest_mode": "synthetic" if plan.synthetic else "live_device",
            "device_access_occurred": False, "device_access_claim_scope": "intent-before-worker-open",
            "origin_verified": False, "permission_verified": False, "calibration_status": "uncalibrated",
            "hardware_qualification_established": False, "clock_quality": "unknown", "clock_relation": None,
            "utc_start": None, "utc_end": None, "physical_uncertainty_ns": None}


def _receipt(plan, index, previous, sid, config_hash, position, block):
    return {"schema": SCHEMA, "kind": "chunk", "index": index, "previous_receipt_sha256": previous,
            "plan_sha256": plan.sha256, "source_id": sid, "configuration_sha256": config_hash,
            "payload_name": f"payload-{index:09d}.bin", "payload_bytes": len(block.payload),
            "payload_sha256": digest(block.payload), "position": position, "units": block.units,
            "position_meaning": "nominal-stored-units-not-physical-time", "sequence": block.sequence,
            "raw": parse_canonical(block.raw_metadata_json), "quality": "unqualified",
            "physical_loss_units": None, "utc_start": None, "utc_end": None,
            "exposure_start": None, "exposure_end": None, "physical_uncertainty_ns": None,
            "clock_quality": "unknown", "clock_relation": None,
            "provenance": next(s.provenance for s in plan.sources if s.source_id == sid),
            "device_access_occurred": not plan.synthetic}


class LiveJournal:
    def __init__(self, path: Path, plan: CapturePlanV1, *, owner_fd: int | None = None):
        self.path, self.plan = Path(path), plan
        root = os.lstat(self.path)
        self._root_identity = (root.st_dev, root.st_ino)
        self._owner_fd = owner_fd
        self._transferred = False
        self.used_bytes = 0
        self.count = 0
        self.payload_bytes = 0
        self.previous = None
        self.positions = {s.source_id: 0 for s in plan.sources}
        self.sequences = {s.source_id: None for s in plan.sources}
        self.clocks = {s.source_id: None for s in plan.sources}
        self.configurations = {}
        self.starts = set()
        self.requested = False
        self.failed = False
        self.closed = False
        self.integrity_scans = 0

    def _assert_owner(self, *, allow_final=False):
        if self._owner_fd is None or self._transferred:
            raise JournalFault("writer ownership absent or transferred; mutation refused")
        root, selected, held = os.lstat(self.path), os.lstat(self.path / ".owner.lock"), os.fstat(self._owner_fd)
        if (not stat.S_ISDIR(root.st_mode) or (root.st_dev, root.st_ino) != self._root_identity or
                not stat.S_ISREG(selected.st_mode) or selected.st_size != 0 or
                (selected.st_dev, selected.st_ino) != (held.st_dev, held.st_ino)):
            raise JournalFault("journal directory/ownership artifact replaced; mutation refused")
        if allow_final:
            return
        try:
            os.lstat(self.path / "final.json")
        except FileNotFoundError:
            return
        raise JournalFault("journal already finalized; mutation refused")

    def close_owner(self):
        """Close only: LOCK_UN would also unlock a still-live transferred duplicate."""
        fd, self._owner_fd = self._owner_fd, None
        if fd is not None:
            os.close(fd)

    def __getstate__(self):
        from multiprocessing.context import get_spawning_popen
        from multiprocessing.reduction import DupFd
        if get_spawning_popen() is None:
            raise JournalFault("writer ownership transfer requires registered process spawn")
        self._assert_owner()
        state = self.__dict__.copy()
        # Burn parent mutation authority even if descriptor reduction fails.
        # The duplicate carries the *same* locked file description, not a reopen.
        self._transferred = True
        state["_owner_transfer"] = DupFd(state.pop("_owner_fd"))
        return state

    def __setstate__(self, state):
        transfer = state.pop("_owner_transfer")
        self.__dict__.update(state)
        self._owner_fd = transfer.detach()

    def __del__(self):
        if getattr(self, "_owner_fd", None) is not None:
            try:
                self.close_owner()
            except (OSError, AttributeError):
                pass

    @classmethod
    def create(cls, path: str | Path, plan: CapturePlanV1):
        path = Path(path)
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        fd = _open_owner(path, create=True)
        journal = None
        try:
            journal = cls(path, plan, owner_fd=fd)
            reserve = path / ".reserve"
            with reserve.open("xb") as out:
                remaining = plan.limits.reserve_bytes
                zeros = bytes(min(65536, remaining))
                while remaining:
                    written = out.write(zeros[:min(remaining, len(zeros))])
                    remaining -= written
                out.flush()
                os.fsync(out.fileno())
            journal._metadata("intent.json", _intent(plan))
            _sync_dir(path.parent)
            return journal
        except BaseException:
            if journal is None:
                os.close(fd)
            else:
                journal.close_owner()
            raise

    def _metadata(self, name, value):
        self._assert_owner()
        data = canonical(value)
        if len(data) > MAX_METADATA_BYTES or self.used_bytes + len(data) > self.plan.limits.output_bytes - self.plan.limits.reserve_bytes:
            raise JournalFault("metadata/storage budget")
        _publish(self.path, name, data)
        self.used_bytes += len(data)
        return digest(data)

    def record_configuration(self, source_id: str, canonical_metadata: bytes):
        if self.requested or self.failed or self.closed or source_id in self.configurations:
            raise JournalFault("configuration cannot change or follow start")
        config = _configuration(self.plan, source_id, canonical_metadata)
        self.configurations[source_id] = self._metadata(f"config-{source_id}.json", config)

    def record_start_request(self):
        if self.requested or self.failed or self.closed or len(self.configurations) != len(self.plan.sources):
            raise JournalFault("all configuration evidence must precede start")
        self._metadata("start-request.json", {"kind": "start-request", "plan_sha256": self.plan.sha256})
        self.requested = True

    def record_started(self, source_id: str, host_monotonic_ns: int):
        if not self.requested or self.failed or self.closed or source_id not in self.configurations or source_id in self.starts or type(host_monotonic_ns) is not int or host_monotonic_ns < 0:
            raise JournalFault("invalid start return")
        self._metadata(f"start-{source_id}.json", {"kind": "start-return", "source_id": source_id,
                                                "host_monotonic_ns": host_monotonic_ns})
        self.starts.add(source_id)

    def append_payload(self, source_id: str, block: CapturedBlockV1) -> CommittedChunkReceipt:
        self._assert_owner()
        if self.failed or self.closed or source_id not in self.starts:
            raise JournalFault("journal not writable/started")
        try:
            source = next(s for s in self.plan.sources if s.source_id == source_id)
            _, clock = _validate_block(source, self.plan.limits, block, self.sequences[source_id], self.clocks[source_id])
            record = _receipt(self.plan, self.count, self.previous, source_id,
                              self.configurations[source_id], self.positions[source_id], block)
            data = canonical(record)
            if (self.count >= self.plan.limits.max_chunks or len(data) > MAX_METADATA_BYTES or
                    self.used_bytes + len(block.payload) + len(data) > self.plan.limits.output_bytes - self.plan.limits.reserve_bytes):
                raise JournalFault("chunk/output budget exhausted")
            _publish(self.path, record["payload_name"], block.payload)
            self.used_bytes += len(block.payload)
            _publish(self.path, f"receipt-{self.count:09d}.json", data)
            self.used_bytes += len(data)
            result = CommittedChunkReceipt(self.count, source_id, record["payload_sha256"], digest(data), data)
            self.previous = result.receipt_sha256
            self.count += 1
            self.payload_bytes += len(block.payload)
            self.positions[source_id] += block.units
            self.sequences[source_id], self.clocks[source_id] = block.sequence, clock
            return result
        except BaseException:
            self.failed = True
            raise

    def finalize(self, reason: str, *, fault_domain: str | None = None,
                 native_code: int | None = None, application_discarded_chunks: int | None = None,
                 observed_queue_rejected_chunks: int | None = None) -> VerifiedLiveJournalView:
        if self.closed:
            raise JournalFault("already finalized")
        self._assert_owner()
        self.integrity_scans += 1
        view = verify_live_journal(self.path)
        return self._seal(view, reason, fault_domain, native_code, application_discarded_chunks,
                          observed_queue_rejected_chunks)

    def _seal(self, view, reason, fault_domain, native_code, application_discarded_chunks,
              observed_queue_rejected_chunks=None):
        self._assert_owner()
        if not _valid_fault_observations(fault_domain, native_code, application_discarded_chunks, observed_queue_rejected_chunks):
            raise JournalFault("invalid final fault/count observations")
        if type(reason) is not str or not reason or len(reason) > 1024:
            raise JournalFault("bounded final reason required")
        inventory = canonical({"names": view.orphan_names})
        final = {"schema": SCHEMA, "kind": "final", "plan_sha256": self.plan.sha256,
                 "reason": reason, "fault_domain": fault_domain, "native_code": native_code,
                 "writer_closed": True, "committed_chunks": view.committed_chunks,
                 "committed_bytes": view.committed_bytes, "last_receipt_sha256": view.last_receipt_sha256,
                 "positions": dict(view.positions), "integrity_error": view.integrity_error,
                 "orphan_count": len(view.orphan_names), "orphan_names_first_64": view.orphan_names[:64],
                 "orphan_inventory_sha256": digest(inventory),
                 "application_discarded_chunks": application_discarded_chunks,
                 "observed_queue_rejected_chunks": observed_queue_rejected_chunks,
                 "queue_rejection_coverage": "received-worker-reports-only; not-all-application-or-physical-loss",
                 "physical_loss_units": None, "source_tail_units": {s.source_id: None for s in self.plan.sources},
                 "planned_acquisition_complete": False, "clock_relation": None,
                 "physical_uncertainty_ns": None, "utc_end": None,
                 "device_access_occurred": False if self.plan.synthetic else None,
                 "device_access_claim_scope": "see-per-source-configuration; failed-open-may-have-accessed-device"}
        data = canonical(final)
        if len(data) > self.plan.limits.reserve_bytes or len(data) > MAX_METADATA_BYTES:
            raise JournalFault("final record exceeds reserved capacity")
        reserve = self.path / ".reserve"
        identity = _reserve_identity(self.path, self.plan)
        if identity is not None:
            current = os.lstat(reserve)
            if (not stat.S_ISREG(current.st_mode) or
                    (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) != identity):
                raise JournalFault("reserve replaced before release; replacement retained")
            reserve.unlink()
            _sync_dir(self.path)
        self._assert_owner()
        _publish(self.path, "final.json", data)
        self.closed = True
        self.close_owner()
        return VerifiedLiveJournalView(view.capture_id, view.plan_sha256, view.committed_chunks,
                                       view.committed_bytes, view.last_receipt_sha256, view.positions,
                                       view.orphan_names, view.integrity_error, True, data)

    @classmethod
    def recover(cls, path: str | Path) -> VerifiedLiveJournalView:
        """Seal a stopped prefix once. Recovery never resumes capture or rewrites bytes."""
        path = Path(path)
        root = os.lstat(path)
        fd = _open_owner(path)
        journal = None
        try:
            header = parse_canonical(_read(path, "intent.json", MAX_METADATA_BYTES))
            journal = cls(path, CapturePlanV1.from_bytes(canonical(header["plan"])), owner_fd=fd)
            if journal._root_identity != (root.st_dev, root.st_ino):
                raise JournalFault("journal directory replaced during recovery")
            journal._assert_owner(allow_final=True)
            view = verify_live_journal(path)
            journal.integrity_scans = 1
            journal._assert_owner(allow_final=True)
            if view.closed:
                return view
            return journal._seal(view, "recovery-incomplete", "process-interruption", None, None)
        finally:
            if journal is None:
                os.close(fd)
            else:
                journal.close_owner()
