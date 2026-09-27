"""Offline PGM8 observation evidence. No species or fouling classifier."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import re
from typing import Iterator

from poseidon_acoustic.session import (
    Channel, ClockMap, MAX_PGM_PIXELS, Session, SessionError, Source, canonical, capture_guard, decode_pgm8, finite,
    load_json, positive_int, publish, read_bounded, safe_name, sha256,
)


FRAMES_SCHEMA = "poseidon.nereid-frames.provisional.v1"
INDEX_SCHEMA = "poseidon.nereid-index.provisional.v1"
EXCERPT_SCHEMA = "poseidon.nereid-excerpt.provisional.v1"
MAX_PIXELS = MAX_PGM_PIXELS
MAX_FRAMES = 4096


def encode_pgm(width: int, height: int, pixels: bytes) -> bytes:
    positive_int(width, "image width", maximum=MAX_PIXELS)
    positive_int(height, "image height", maximum=MAX_PIXELS)
    if width * height > MAX_PIXELS or not isinstance(pixels, bytes) or len(pixels) != width * height:
        raise SessionError("invalid image dimensions or pixel budget")
    return f"P5\n{width} {height}\n255\n".encode("ascii") + pixels


def decode_pgm(data: bytes) -> tuple[int, int, bytes]:
    """Bounded canonical P5/255 decoder; comments, P2 and other depths unsupported."""
    return decode_pgm8(data)


@dataclass(frozen=True)
class Frame:
    frame_index: int
    source_start_s: float
    source_end_s: float
    pgm: bytes
    dropped_before: int = 0
    gap_reason: str = ""


def synthetic_frames(*, count: int = 8, width: int = 16, height: int = 12,
                     period_s: float = 0.25) -> Iterator[Frame]:
    positive_int(count, "frame count", maximum=MAX_FRAMES)
    positive_int(width, "width", maximum=MAX_PIXELS)
    positive_int(height, "height", maximum=MAX_PIXELS)
    if width * height > MAX_PIXELS:
        raise SessionError("image pixel budget exceeded")
    if finite(period_s, "frame period") <= 0:
        raise SessionError("frame period must be positive")
    for index in range(count):
        # Fixed rule cases, not scenes or a biological reference dataset.
        pixels = (bytes([8]) * (width * height) if index % 4 == 0 else
                  bytes([128]) * (width * height) if index % 4 == 2 else
                  bytes((x * 17 + y * 11 + index * 31) % 256
                        for y in range(height) for x in range(width)))
        yield Frame(index, index * period_s, (index + 1) * period_s, encode_pgm(width, height, pixels))


def write_fixture(directory: Path | str, *, count: int = 8) -> Path:
    """Reproducible file input including clock/source identity and checksums."""
    positive_int(count, "frame count", maximum=MAX_FRAMES)
    directory = Path(directory)
    source = Source("synthetic-camera", "pgm8", "synthetic", (Channel("gray", "synthetic grayscale"),),
                    ClockMap("reference_seconds", "synthetic-session-start", reference_anchor_s=0.35,
                             drift_ppm=25.0, anchor_uncertainty_s=0.02, drift_uncertainty_ppm=5.0),
                    origin="integer-pattern PGM fixture v1; not field evidence")
    directory.mkdir(parents=True, exist_ok=False)
    entries = []
    for frame in synthetic_frames(count=count):
        name = f"frame-{frame.frame_index:06d}.pgm"
        publish(directory, name, frame.pgm)
        entries.append({"frame_index": frame.frame_index, "path": name, "sha256": sha256(frame.pgm),
                        "source_start_s": frame.source_start_s, "source_end_s": frame.source_end_s,
                        "dropped_before": 0, "gap_reason": ""})
    publish(directory, "frames.json", canonical({"schema": FRAMES_SCHEMA, "source": asdict(source), "frames": entries}))
    return directory / "frames.json"


def file_frames(manifest_path: Path | str, *, max_frames: int = MAX_FRAMES,
                max_input_bytes: int = 64 * 1024 * 1024) -> tuple[Source, Iterator[Frame]]:
    """Checksummed timestamped PGM files, streamed one image at a time."""
    positive_int(max_frames, "frame input budget", maximum=MAX_FRAMES)
    positive_int(max_input_bytes, "byte input budget", maximum=2**40)
    manifest_path = Path(manifest_path)
    original_manifest = read_bounded(manifest_path, 2 * 1024 * 1024)
    value = load_json(manifest_path, 2 * 1024 * 1024)
    if not isinstance(value, dict) or set(value) != {"schema", "source", "frames"} or value["schema"] != FRAMES_SCHEMA:
        raise SessionError("unsupported frame source manifest")
    if canonical(value) != original_manifest:
        raise SessionError("frame manifest must be canonical and stable")
    source = replace(Source.from_dict(value["source"]), input_sha256=sha256(original_manifest))
    if source.media != "pgm8":
        raise SessionError("frame manifest must bind a PGM source")
    entries = value["frames"]
    if not isinstance(entries, list) or not 0 < len(entries) <= max_frames:
        raise SessionError("empty or oversized frame index")
    total = len(original_manifest)
    previous_end, previous_index = source.source_origin_s, -1
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"frame_index", "path", "sha256", "source_start_s",
                                                        "source_end_s", "dropped_before", "gap_reason"}:
            raise SessionError("invalid frame index fields")
        name = safe_name(entry["path"])
        index, dropped = entry["frame_index"], entry["dropped_before"]
        start, end = finite(entry["source_start_s"], "frame start"), finite(entry["source_end_s"], "frame end")
        if (type(index) is not int or not previous_index < index <= 2**53
                or type(dropped) is not int or not 0 <= dropped <= index - previous_index - 1
                or start < previous_end - 1e-9 or end <= start or name in seen):
            raise SessionError("invalid frame order, duration, repeated path or drop count")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise SessionError("invalid frame checksum")
        reason = entry["gap_reason"]
        if not isinstance(reason, str) or len(reason) > 256 or (
                (index > previous_index + 1 or start > previous_end + 1e-9) and not reason.strip()):
            raise SessionError("frame gap requires an explicit bounded reason")
        seen.add(name)
        previous_index, previous_end = index, end

    def frames():
        nonlocal total
        for entry in entries:
            data = read_bounded(manifest_path.parent / entry["path"], min(MAX_PIXELS + 128, max_input_bytes - total))
            total += len(data)
            if total > max_input_bytes:
                raise SessionError("frame input byte budget exceeded")
            if sha256(data) != entry["sha256"]:
                raise SessionError("frame checksum mismatch")
            decode_pgm(data)
            yield Frame(entry["frame_index"], entry["source_start_s"], entry["source_end_s"], data,
                        entry["dropped_before"], entry["gap_reason"])
        if read_bounded(manifest_path, 2 * 1024 * 1024) != original_manifest:
            raise SessionError("frame source manifest changed during capture")

    if total >= max_input_bytes:
        raise SessionError("frame manifest exceeds input byte budget")
    return source, frames()


def capture_frames(session: Session, source_id: str, frames: Iterator[Frame]) -> int:
    if session.source(source_id).media != "pgm8":
        raise SessionError("video source required")
    count = 0
    with capture_guard(session):
        for frame in frames:
            decode_pgm(frame.pgm)
            session.append(source_id, frame.pgm, unit_start=frame.frame_index, units=1,
                           source_start_s=frame.source_start_s, source_end_s=frame.source_end_s,
                           dropped_units=frame.dropped_before, gap_reason=frame.gap_reason)
            count += 1
    return count


@dataclass(frozen=True)
class ROI:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self):
        if type(self.x) is not int or type(self.y) is not int or min(self.x, self.y) < 0:
            raise SessionError("ROI origin must contain nonnegative integers")
        positive_int(self.width, "ROI width", maximum=MAX_PIXELS)
        positive_int(self.height, "ROI height", maximum=MAX_PIXELS)

    def pixels(self, width: int, height: int, pixels: bytes) -> bytes:
        if self.x + self.width > width or self.y + self.height > height:
            raise SessionError("ROI exceeds frame dimensions")
        return b"".join(pixels[y * width + self.x:y * width + self.x + self.width]
                        for y in range(self.y, self.y + self.height))


@dataclass(frozen=True)
class QualityPolicy:
    dark_mean_below: float = 0.10
    bright_mean_above: float = 0.90
    contrast_below: float = 0.10
    clipped_fraction_above: float = 0.10

    def __post_init__(self):
        for name, value in asdict(self).items():
            if not 0 <= finite(value, name) <= 1:
                raise SessionError("quality thresholds must be in [0, 1]")
        if self.dark_mean_below >= self.bright_mean_above:
            raise SessionError("dark threshold must be below bright threshold")


def quality(pixels: bytes, policy: QualityPolicy, *, operator_occluded: bool = False) -> dict:
    if not pixels or not isinstance(pixels, bytes) or type(operator_occluded) is not bool:
        raise SessionError("invalid image quality input")
    mean = sum(pixels) / (255 * len(pixels))
    contrast = (max(pixels) - min(pixels)) / 255
    clipped = sum(v in (0, 255) for v in pixels) / len(pixels)
    flags = []
    if mean < policy.dark_mean_below:
        flags.append("dark_rule")
    if mean > policy.bright_mean_above:
        flags.append("bright_rule")
    if contrast < policy.contrast_below:
        flags.append("low_contrast_rule")
    if clipped > policy.clipped_fraction_above:
        flags.append("clipping_rule")
    if operator_occluded:
        flags.append("operator_declared_occlusion")
    return {"mean_normalized": mean, "range_contrast_normalized": contrast,
            "clipped_fraction": clipped, "flags": flags,
            "occlusion": "operator_declared" if operator_occluded else "not_assessed",
            "biological_classifier": False}


def build_index(session: Session, source_id: str, *, roi: ROI | None = None,
                policy: QualityPolicy | None = None,
                operator_occluded_frames: tuple[int, ...] = ()) -> dict:
    source = session.source(source_id)
    if source.media != "pgm8":
        raise SessionError("PGM video source required")
    if roi is not None and not isinstance(roi, ROI):
        raise SessionError("ROI object required")
    policy = QualityPolicy() if policy is None else policy
    if not isinstance(policy, QualityPolicy):
        raise SessionError("quality policy required")
    if not isinstance(operator_occluded_frames, tuple) or any(type(v) is not int or v < 0 for v in operator_occluded_frames):
        raise SessionError("operator occlusions must name nonnegative frame indexes")
    recovery = session.recover()
    if not recovery["finalized"]:
        raise SessionError("finalize acquisition before building review evidence")
    records = [r for r in recovery["receipts"] if r["source_id"] == source_id]
    if set(operator_occluded_frames) - {r["unit_start"] for r in records}:
        raise SessionError("operator occlusion references an absent frame")
    frames = []
    for record in records:
        data = read_bounded(session.directory / record["path"], MAX_PIXELS + 128)
        if sha256(data) != record["sha256"]:
            raise SessionError("frame changed after session verification")
        width, height, pixels = decode_pgm(data)
        region = ROI(0, 0, width, height) if roi is None else roi
        frames.append({"frame_index": record["unit_start"], "path": record["path"], "sha256": record["sha256"],
                       "width": width, "height": height, "roi": asdict(region),
                       "source_start_s": record["source_start_s"], "source_end_s": record["source_end_s"],
                       "reference_start_s": record["reference_start_s"], "reference_end_s": record["reference_end_s"],
                       "start_uncertainty_s": record["start_uncertainty_s"], "end_uncertainty_s": record["end_uncertainty_s"],
                       "gap_source_s": record["gap_source_s"], "missing_frames": record["missing_units"],
                       "dropped_frames": record["dropped_units"],
                       "quality": quality(region.pixels(width, height, pixels), policy,
                                          operator_occluded=record["unit_start"] in operator_occluded_frames)})
    return {"schema": INDEX_SCHEMA, "session_id": recovery["manifest"]["session_id"],
            "session_header_sha256": recovery["manifest"]["header_sha256"], "source_id": source_id,
            "reference_domain": source.clock.reference_domain, "reference_epoch": source.clock.reference_epoch,
            "provenance": source.provenance, "hardware_verified": False,
            "session_state": recovery["manifest"]["state"],
            "uncommitted_files": recovery["manifest"]["uncommitted_files"],
            "quality_policy": asdict(policy), "frames": frames}


@dataclass(frozen=True)
class Observation:
    observation_id: str
    reference_domain: str
    reference_epoch: str
    reference_start_s: float
    reference_end_s: float
    uncertainty_s: float
    label: str
    observer: str

    def __post_init__(self):
        safe_name(self.observation_id)
        finite(self.reference_start_s, "observation start")
        finite(self.reference_end_s, "observation end")
        finite(self.uncertainty_s, "observation uncertainty", nonnegative=True)
        if self.reference_end_s <= self.reference_start_s:
            raise SessionError("observation interval must have positive duration")
        if self.label not in {"observed_event", "hard_negative", "unknown", "unusable"}:
            raise SessionError("unsupported independent observation label")
        for value in (self.reference_domain, self.reference_epoch, self.observer):
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise SessionError("explicit reference domain, epoch and observer required")


def _uncovered(start: float, end: float, frames: list[dict]) -> list[list[float]]:
    cursor = start
    gaps = []
    for frame in frames:
        lo, hi = max(start, frame["reference_start_s"]), min(end, frame["reference_end_s"])
        if hi <= lo:
            continue
        if lo > cursor:
            gaps.append([cursor, lo])
        cursor = max(cursor, hi)
    if cursor < end:
        gaps.append([cursor, end])
    return gaps


def _separate_output(source_directory: Path | str, output: Path | str) -> None:
    """Do not add review artifacts inside immutable source evidence, even via aliases."""
    source = Path(source_directory).resolve()
    destination = Path(output).resolve()
    if destination == source or source in destination.parents:
        raise SessionError("review output must be outside the source evidence directory")


def export_excerpt(session: Session, source_id: str, observation: Observation, directory: Path | str,
                   *, padding_s: float = 0.0, max_frames: int = 128, max_bytes: int = 16 * 1024 * 1024,
                   roi: ROI | None = None, policy: QualityPolicy | None = None,
                   operator_occluded_frames: tuple[int, ...] = ()) -> dict:
    """Independent interval, even with zero candidates/frames. Copy original PGM evidence.

    Intervals are half-open. Include frames whose uncertainty envelopes overlap
    the observation envelope plus padding. This is not verified synchronization.
    """
    _separate_output(session.directory, directory)
    if not isinstance(observation, Observation):
        raise SessionError("independent observation required")
    finite(padding_s, "excerpt padding", nonnegative=True)
    positive_int(max_frames, "excerpt frame budget", maximum=MAX_FRAMES)
    positive_int(max_bytes, "excerpt byte budget", maximum=2**40)
    index = build_index(session, source_id, roi=roi, policy=policy, operator_occluded_frames=operator_occluded_frames)
    if (observation.reference_domain, observation.reference_epoch) != (index["reference_domain"], index["reference_epoch"]):
        raise SessionError("observation and video reference domains/epochs differ")
    start = finite(observation.reference_start_s - observation.uncertainty_s - padding_s, "excerpt start")
    end = finite(observation.reference_end_s + observation.uncertainty_s + padding_s, "excerpt end")
    selected = [f for f in index["frames"]
                if finite(f["reference_end_s"] + f["end_uncertainty_s"], "frame envelope end") > start
                and finite(f["reference_start_s"] - f["start_uncertainty_s"], "frame envelope start") < end]
    if len(selected) > max_frames:
        raise SessionError("excerpt frame budget exceeded")
    manifest = {key: value for key, value in index.items() if key != "frames"}
    manifest.update({"schema": EXCERPT_SCHEMA, "observation": asdict(observation), "padding_s": padding_s,
                     "selection": "half-open uncertainty-envelope overlap; operator clock model, not verified sync",
                     "nominal_uncovered_intervals": _uncovered(observation.reference_start_s,
                                                               observation.reference_end_s, selected),
                     "frames": selected, "biological_validation": False})
    metadata = canonical(manifest)
    total = len(metadata)
    # Preflight all bytes before creating output; only bounded selected files enter memory.
    payloads = []
    for frame in selected:
        data = read_bounded(session.directory / safe_name(frame["path"]), min(MAX_PIXELS + 128, max_bytes - total))
        total += len(data)
        if total > max_bytes or sha256(data) != frame["sha256"]:
            raise SessionError("excerpt byte budget exceeded or source changed")
        payloads.append((frame["path"], data))
    if total > max_bytes:
        raise SessionError("excerpt byte budget exceeded")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for name, data in payloads:
        publish(directory, name, data)
    publish(directory, "excerpt.nereid-v1.json", metadata)
    return manifest
