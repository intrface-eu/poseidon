"""Local recorded MP4/H264 to source-bound PGM8, with an owned codec process.

PyAV is imported only by the worker. The existing PGM/session path stays stdlib.
All time attestations and clock relations come from an explicit declaration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from fractions import Fraction
import ctypes
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from poseidon_acoustic.session import (
    Channel, ClockMap, Session, SessionError, Source, canonical, finite, load_json,
    positive_int, publish, read_bounded, safe_name, sha256,
)
from .codec_mp4 import preflight
from .video import (
    FRAMES_SCHEMA, Observation, _separate_output, build_index, capture_frames, export_excerpt, file_frames,
)


DECLARATION_SCHEMA = "poseidon.nereid-codec-declaration.provisional.v1"
MAP_SCHEMA = "poseidon.nereid-codec-map.provisional.v1"
INDEX_SCHEMA = "poseidon.nereid-codec-index.provisional.v1"
EXCERPT_SCHEMA = "poseidon.nereid-codec-excerpt.provisional.v1"
MAP_NAME = "mapping.codec-v1.json"
MAX_METADATA = 2 * 1024 * 1024
PINNED_AV = "16.1.0"
TRANSFORM = {
    "version": "decoded-y-plane-to-pgm8.v1",
    "description": "Copy decoded 8-bit Y-prime plane rows, remove stride padding and discard chroma. "
                   "No range normalization, gamma correction, rotation, resize or color calibration.",
    "output": "canonical P5 PGM8; decoded luma codes, not original full-color bytes",
    "original_color_bytes": False,
    "display_transform_applied": False,
}


@dataclass(frozen=True)
class DecodeLimits:
    max_input_bytes: int = 16 * 1024 * 1024
    max_streams: int = 4
    max_frames: int = 128
    max_dimension: int = 1024
    max_pixels: int = 1024 * 1024
    max_duration_s: int = 60
    max_storage_bytes: int = 64 * 1024 * 1024
    timeout_s: float = 15.0
    max_rss_bytes: int = 512 * 1024 * 1024

    def __post_init__(self):
        caps = {"max_input_bytes": 32 * 1024 * 1024, "max_streams": 4, "max_frames": 256,
                "max_dimension": 2048, "max_pixels": 1024 * 1024, "max_duration_s": 120,
                "max_storage_bytes": 128 * 1024 * 1024, "max_rss_bytes": 1024 * 1024 * 1024}
        for name, cap in caps.items():
            positive_int(getattr(self, name), name, maximum=cap)
        if not 0 < finite(self.timeout_s, "decoder timeout") <= 30:
            raise SessionError("decoder timeout must be in (0, 30] seconds")


def rational(value, name: str, *, positive: bool = False) -> Fraction:
    if (not isinstance(value, list) or len(value) != 2 or any(type(n) is not int for n in value)
            or abs(value[0]) > 2**63 - 1 or not 0 < value[1] <= 2**63 - 1):
        raise SessionError(f"{name} requires a bounded [numerator, denominator]")
    result = Fraction(*value)
    if positive and result <= 0:
        raise SessionError(f"{name} must be positive")
    return result


def pair(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def _projection(value: Fraction) -> float:
    result = float(value)
    # Existing sessions use doubles. Retain exact rationals in the sidecar and
    # reject loss above one nanosecond, not just collapsed/negative intervals.
    if not math.isfinite(result) or abs(Fraction.from_float(result) - value) > Fraction(1, 10**9):
        raise SessionError("exact codec time is not representable by the session bridge within 1 ns")
    return result


def declaration(value: dict) -> dict:
    expected = {"schema", "source_id", "source_sha256", "stream_index", "provenance", "origin", "clock",
                "infer_intervals_from_next_pts", "max_frame_interval_s", "duration_attestations"}
    if not isinstance(value, dict) or set(value) != expected or value["schema"] != DECLARATION_SCHEMA:
        raise SessionError("explicit codec declaration fields/schema required")
    safe_name(value["source_id"])
    if not isinstance(value["source_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"]):
        raise SessionError("declaration must bind original source SHA256")
    if type(value["stream_index"]) is not int or not 0 <= value["stream_index"] < 4:
        raise SessionError("explicit absolute stream index required")
    if not isinstance(value["clock"], dict) or set(value["clock"]) != {f.name for f in fields(ClockMap)}:
        raise SessionError("every source/reference clock field and reference epoch must be explicit")
    try:
        clock = ClockMap(**value["clock"])
    except TypeError as exc:
        raise SessionError("invalid clock declaration") from exc
    Source(value["source_id"], "pgm8", value["provenance"], (Channel("gray", "derived luma"),),
           clock, origin=value["origin"], input_sha256=value["source_sha256"])
    if type(value["infer_intervals_from_next_pts"]) is not bool:
        raise SessionError("explicit display-interval inference choice required")
    if rational(value["max_frame_interval_s"], "maximum frame interval", positive=True) > 120:
        raise SessionError("frame interval bound exceeds duration cap")
    attestations = value["duration_attestations"]
    if not isinstance(attestations, list) or not 1 <= len(attestations) <= 256:
        raise SessionError("at least the final frame duration needs an explicit attestation")
    seen = set()
    for item in attestations:
        if not isinstance(item, dict) or set(item) != {"pts_s", "duration_s", "evidence_ref"}:
            raise SessionError("invalid frame duration attestation")
        pts = rational(item["pts_s"], "attested PTS")
        rational(item["duration_s"], "attested duration", positive=True)
        safe_name(item["evidence_ref"])
        if pts in seen:
            raise SessionError("repeated duration attestation")
        seen.add(pts)
    return value


def presentation_intervals(frames: list[dict], declared: dict, limits: DecodeLimits) -> list[dict]:
    """Strict presentation order. Never sort a damaged decoder output or invent FPS.

    An opted-in interior interval can use the next PTS, bounded by the caller.
    This is a display-hold inference, NOT an attested camera exposure duration.
    Final frames require an attestation. Attested gaps stay uncovered.
    """
    declaration(declared)
    if not 0 < len(frames) <= limits.max_frames:
        raise SessionError("empty or excessive decoded frame count")
    starts = []
    for frame in frames:
        pts = frame["pts"]
        if type(pts) is not int or abs(pts) > 2**63 - 1:
            raise SessionError("missing or unbounded frame PTS")
        starts.append(pts * rational(frame["time_base"], "frame time base", positive=True))
    if any(b <= a for a, b in zip(starts, starts[1:])):
        raise SessionError("repeated or backwards presentation timestamps; no sorting or deduplication")
    attested = {rational(a["pts_s"], "attested PTS"): a for a in declared["duration_attestations"]}
    if set(attested) - set(starts):
        raise SessionError("duration attestation references an absent frame PTS")
    bound = rational(declared["max_frame_interval_s"], "maximum frame interval", positive=True)
    clock = ClockMap(**declared["clock"])
    result = []
    previous_end = starts[0]
    for i, start in enumerate(starts):
        attestation = attested.get(start)
        if attestation:
            duration = rational(attestation["duration_s"], "attested duration", positive=True)
            basis, evidence = "operator_attested_unverified", attestation["evidence_ref"]
        elif declared["infer_intervals_from_next_pts"] and i + 1 < len(starts):
            duration = starts[i + 1] - start
            basis, evidence = "inferred_next_presentation_pts_not_exposure", None
        else:
            raise SessionError("unattested final/ambiguous frame duration; no FPS or container-duration fallback")
        end = start + duration
        if duration > bound or (i + 1 < len(starts) and end > starts[i + 1]):
            raise SessionError("overlapping or discontinuous frame interval exceeds declared bound")
        if end - starts[0] > limits.max_duration_s:
            raise SessionError("decoded presentation span exceeds duration budget")
        start_float, end_float = _projection(start), _projection(end)
        if end_float <= start_float or clock.at(end_float)[0] <= clock.at(start_float)[0]:
            raise SessionError("frame/reference interval loses positive duration in session bridge")
        result.append({"source_start_s": start_float, "source_end_s": end_float,
                       "source_start_exact_s": pair(start), "source_end_exact_s": pair(end),
                       "duration_exact_s": pair(duration), "duration_basis": basis,
                       "duration_evidence_ref": evidence,
                       "session_start_projection_error_s": pair(Fraction.from_float(start_float) - start),
                       "session_end_projection_error_s": pair(Fraction.from_float(end_float) - end),
                       "gap_reason": ("uncovered interval between attested presentation intervals; "
                                      "missing frame count unknown" if start > previous_end else "")})
        previous_end = end
    return result


def _resident_bytes(pid: int) -> int:
    if sys.platform == "darwin":
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        buffer = ctypes.create_string_buffer(4096)
        size = lib.proc_pidinfo(pid, 4, 0, buffer, len(buffer))  # PROC_PIDTASKINFO, resident_size at byte 8
        if size < 16:
            raise SessionError("cannot inspect owned codec process memory")
        return int.from_bytes(buffer.raw[8:16], sys.byteorder)
    if sys.platform.startswith("linux"):
        # Only the child PID, never a process-name sweep.
        with open(f"/proc/{pid}/statm", "r", encoding="ascii") as stream:
            return int(stream.read(256).split()[1]) * os.sysconf("SC_PAGE_SIZE")
    raise SessionError("codec supervisor supports Linux and macOS only")


def _supervise(command: list[str], limits: DecodeLimits) -> None:
    """Hard wall deadline; every started process is killed/reaped on every exit.

    Linux also uses worker RLIMIT_AS. macOS lacks that cap: RSS is sampled at
    10 ms, supplemented by native single-allocation and codec pixel limits.
    This is resource containment, not a hostile-native-code security sandbox.
    """
    started = time.monotonic()
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        while process.poll() is None:
            if time.monotonic() - started >= limits.timeout_s:
                raise SessionError("owned codec process exceeded hard wall timeout")
            try:
                rss = _resident_bytes(process.pid)
            except (OSError, ValueError, SessionError):
                # On macOS task info can disappear just before waitpid reports
                # exit. Reap that transition, but never run unmonitored alive.
                try:
                    process.wait(timeout=min(0.02, max(0.001, limits.timeout_s - (time.monotonic() - started))))
                    break
                except subprocess.TimeoutExpired:
                    raise SessionError("owned codec memory watchdog unavailable") from None
            if rss > limits.max_rss_bytes:
                raise SessionError("owned codec process exceeded RSS budget")
            time.sleep(0.01)
        if process.wait() != 0:
            raise SessionError(f"owned codec process failed (exit {process.returncode}); see bounded worker result")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def _worker(operation: str, directory: Path, limits: DecodeLimits, declared: dict | None = None) -> dict:
    # Transient request/results do not become source evidence or alter old reports.
    with tempfile.TemporaryDirectory(prefix=".codec-job-", dir=directory) as temporary:
        job = Path(temporary)
        publish(job, "request.json", canonical({"operation": operation, "directory": str(directory.resolve()),
                                               "limits": asdict(limits), "declaration": declared}))
        command = [sys.executable, "-m", "poseidon_nereid._codec_worker", str(job / "request.json")]
        try:
            _supervise(command, limits)
        except SessionError as exc:
            if (job / "result.json").exists():
                error = load_json(job / "result.json", MAX_METADATA).get("error", "codec process failed")
                raise SessionError(str(error)[:512]) from exc
            raise
        result = load_json(job / "result.json", MAX_METADATA)
        if "error" in result:
            raise SessionError(result["error"])
        return result


def _size(directory: Path) -> int:
    return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())


def _recorded_path(value: Path | str) -> Path:
    text = str(value)
    path = Path(value)
    absolute = Path(os.path.abspath(path))
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", text) or any(
            absolute == root or root in absolute.parents for root in (Path("/dev"), Path("/proc"), Path("/sys"))):
        raise SessionError("device paths, URLs and protocol inputs are not recorded regular files")
    return path


def decode_file(source_path: Path | str, declaration_path: Path | str, directory: Path | str,
                *, session_id: str, limits: DecodeLimits | None = None) -> dict:
    limits = DecodeLimits() if limits is None else limits
    if not isinstance(limits, DecodeLimits):
        raise SessionError("validated DecodeLimits required")
    safe_name(session_id)
    source_path, directory = _recorded_path(source_path), Path(directory)
    declared = declaration(load_json(_recorded_path(declaration_path), MAX_METADATA))
    original = read_bounded(source_path, limits.max_input_bytes)
    digest = sha256(original)
    if digest != declared["source_sha256"]:
        raise SessionError("original source SHA256 differs from explicit declaration")
    preflight(original, limits)
    if len(original) + len(canonical(declared)) + 3 * MAX_METADATA + 8192 > limits.max_storage_bytes:
        raise SessionError("storage budget cannot hold encoded input and bounded metadata/scratch reserve")
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(directory)
    directory.mkdir(parents=True, exist_ok=False)
    try:
        publish(directory, "source.mp4", original)
        publish(directory, "declaration.codec-v1.json", canonical(declared))
        decoded = _worker("decode", directory, limits, declared)
        intervals = presentation_intervals(decoded["frames"], declared, limits)
        if sha256(read_bounded(source_path, limits.max_input_bytes)) != digest:
            raise SessionError("original encoded source changed during decode")
        if read_bounded(directory / "source.mp4", limits.max_input_bytes) != original:
            raise SessionError("archived encoded source changed during decode")
        mapped = [dict(frame, **interval) for frame, interval in zip(decoded["frames"], intervals)]
        mapping = {"schema": MAP_SCHEMA, "source_container": {"path": "source.mp4", "sha256": digest,
                    "bytes": len(original), "media": "video/mp4; codecs=avc1", "original_bytes_preserved": True},
                   "declaration": declared, "declaration_sha256": sha256(canonical(declared)),
                   "decoder": decoded["decoder"], "stream": decoded["stream"], "container": decoded["container"],
                   "limits": asdict(limits), "transform": TRANSFORM, "frames": mapped,
                   "timestamp_semantics": "MOV demux PTS with edit list applied; raw sample-table PTS/DTS also retained. "
                                          "PTS are not reset to zero; no constant FPS assumption.",
                   "software_only": True, "hardware_verified": False, "biological_classifier": False,
                   "calibration": "none; decoded luma codes are not calibrated brightness or biological evidence"}
        metadata = canonical(mapping)
        if len(metadata) > MAX_METADATA:
            raise SessionError("codec mapping exceeds metadata budget")
        publish(directory, MAP_NAME, metadata)
        source = Source(declared["source_id"], "pgm8", declared["provenance"],
                        (Channel("gray", "derived H264 Y-prime plane; chroma discarded, not original color bytes"),),
                        ClockMap(**declared["clock"]), source_origin_s=intervals[0]["source_start_s"],
                        origin=f"Derived PGM8, not original color bytes; {MAP_NAME} SHA256={sha256(metadata)}",
                        input_sha256=digest)
        entries = [{"frame_index": f["frame_index"], "path": f["path"], "sha256": f["sha256"],
                    "source_start_s": f["source_start_s"], "source_end_s": f["source_end_s"],
                    "dropped_before": 0, "gap_reason": f["gap_reason"]} for f in mapped]
        publish(directory, "frames.json", canonical({"schema": FRAMES_SCHEMA, "source": asdict(source), "frames": entries}))
        pgm_source, frames = file_frames(directory / "frames.json", max_input_bytes=limits.max_storage_bytes)
        remaining = limits.max_storage_bytes - _size(directory)
        session = Session.create(directory / "session", session_id, (pgm_source,), max_bytes=remaining,
                                 max_chunks=len(mapped))
        capture_frames(session, pgm_source.source_id, frames)
        session.finalize()
        if _size(directory) > limits.max_storage_bytes:
            raise SessionError("codec bundle exceeds storage budget")
        # Review evidence is built on demand, not silently counted outside storage.
        return {"schema": MAP_SCHEMA, "frames": len(mapped), "stream_index": decoded["stream"]["index"],
                "source_sha256": digest, "mapping_sha256": sha256(metadata), "stored_bytes": _size(directory),
                "original_color_bytes_in_pgm": False, "software_only": True}
    finally:
        # Failure keeps only this run's new partial bundle for inspection. There
        # is no completed frame/session bridge on a decoder failure, no eviction.
        if sha256(read_bounded(source_path, limits.max_input_bytes)) != digest:
            raise SessionError("original encoded source changed; decode result is not valid")


def _bound_index(directory: Path | str) -> tuple[dict, dict, Session]:
    directory = Path(directory)
    mapping_bytes = read_bounded(directory / MAP_NAME, MAX_METADATA)
    mapping = load_json(directory / MAP_NAME, MAX_METADATA)
    if canonical(mapping) != mapping_bytes or mapping.get("schema") != MAP_SCHEMA:
        raise SessionError("noncanonical/unsupported codec mapping")
    declared = declaration(mapping["declaration"])
    if mapping["declaration_sha256"] != sha256(canonical(declared)) or load_json(
            directory / "declaration.codec-v1.json", MAX_METADATA) != declared:
        raise SessionError("codec declaration binding changed")
    limits = DecodeLimits(**mapping["limits"])
    source_bytes = read_bounded(directory / "source.mp4", limits.max_input_bytes)
    container = mapping["source_container"]
    if (container["path"] != "source.mp4" or len(source_bytes) != container["bytes"]
            or sha256(source_bytes) != container["sha256"] or container["sha256"] != declared["source_sha256"]):
        raise SessionError("encoded source binding/checksum changed")
    pgm_source, frames = file_frames(directory / "frames.json", max_input_bytes=limits.max_storage_bytes)
    input_frames = list(frames)
    expected_origin = f"Derived PGM8, not original color bytes; {MAP_NAME} SHA256={sha256(mapping_bytes)}"
    if pgm_source.origin != expected_origin:
        raise SessionError("frame manifest does not bind codec mapping")
    session = Session(directory / "session")
    if session.source(declared["source_id"]) != pgm_source:
        raise SessionError("session does not bind derived frame source")
    index = build_index(session, declared["source_id"])
    if len(index["frames"]) != len(mapping["frames"]) or len(input_frames) != len(mapping["frames"]):
        raise SessionError("codec/session frame count mismatch")
    intervals = presentation_intervals(mapping["frames"], declared, limits)
    for actual, source_frame, mapped, interval in zip(index["frames"], input_frames, mapping["frames"], intervals):
        if (any(actual[key] != mapped[key] for key in ("frame_index", "sha256", "source_start_s", "source_end_s"))
                or actual["frame_index"] != source_frame.frame_index or sha256(source_frame.pgm) != mapped["sha256"]
                or any(mapped[key] != value for key, value in interval.items())):
            raise SessionError("frame-to-source association changed")
    index.update({"schema": INDEX_SCHEMA, "source_container": container, "codec_mapping_sha256": sha256(mapping_bytes),
                  "frames_manifest_sha256": pgm_source.input_sha256, "transform": mapping["transform"],
                  "stream": mapping["stream"], "decoder": mapping["decoder"],
                  "codec_frame_mapping": mapping["frames"], "biological_classifier": False,
                  "source_origin": declared["origin"], "calibration": mapping["calibration"]})
    return index, mapping, session


def build_codec_index(directory: Path | str) -> dict:
    return _bound_index(directory)[0]


def export_codec_excerpt(directory: Path | str, observation: Observation, output: Path | str,
                         *, max_frames: int = 128, max_bytes: int = 16 * 1024 * 1024,
                         padding_s: float = 0.0) -> dict:
    _separate_output(directory, output)
    positive_int(max_bytes, "codec excerpt byte budget", maximum=128 * 1024 * 1024)
    index, mapping, session = _bound_index(directory)
    # Reserve an upper bound for codec metadata before the existing exporter
    # creates output; it retains and copies the original *derived PGM* bytes.
    extension = {key: value for key, value in index.items() if key not in {"frames", "codec_frame_mapping"}}
    extension.update({"schema": EXCERPT_SCHEMA, "codec_frame_mapping": mapping["frames"],
                      "source_container_included": False, "requires_source_bundle": True,
                      "observation": asdict(observation), "padding_s": padding_s,
                      "source_binding": "full encoded MP4 stays in source bundle; copied PGM frames are luma derivatives"})
    reserve = len(canonical(extension))
    if reserve >= max_bytes:
        raise SessionError("codec excerpt metadata exceeds byte budget")
    excerpt = export_excerpt(session, index["source_id"], observation, output, max_frames=max_frames,
                             max_bytes=max_bytes - reserve, padding_s=padding_s)
    selected = {frame["frame_index"] for frame in excerpt["frames"]}
    extension["codec_frame_mapping"] = [f for f in mapping["frames"] if f["frame_index"] in selected]
    publish(Path(output), "excerpt.codec-v1.json", canonical(extension))
    return extension


def synthetic_fixture(directory: Path | str, *, limits: DecodeLimits | None = None) -> dict:
    limits = DecodeLimits() if limits is None else limits
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    result = _worker("fixture", directory, limits)
    data = read_bounded(directory / "synthetic.mp4", limits.max_input_bytes)
    preflight(data, limits)
    declared = {"schema": DECLARATION_SCHEMA, "source_id": "synthetic-h264-camera", "source_sha256": sha256(data),
                "stream_index": 0, "provenance": "synthetic", "origin": "SYNTHETIC integer luma patterns; no farm/animal imagery",
                "clock": asdict(ClockMap("reference_seconds", "synthetic-codec-epoch", source_anchor_s=2.0,
                                        reference_anchor_s=10.0, anchor_uncertainty_s=0.02,
                                        source_domain="synthetic_h264_seconds")),
                "infer_intervals_from_next_pts": True, "max_frame_interval_s": [1, 10],
                "duration_attestations": [{"pts_s": [56, 25], "duration_s": [1, 50],
                                           "evidence_ref": "synthetic-timeline-recipe-v1"}]}
    declaration(declared)
    publish(directory, "declaration.codec-v1.json", canonical(declared))
    publish(directory, "synthetic-recipe.codec-v1.json", canonical(result))
    return {"source_sha256": sha256(data), "frames": 6, "provenance": "synthetic", "encoder": result["encoder"]}
