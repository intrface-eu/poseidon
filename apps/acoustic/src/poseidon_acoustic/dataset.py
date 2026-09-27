"""Provisional independent-observation datasets, separate from replay v1 records.

All intervals are half-open recording-relative seconds. Sealing is content-addressed,
not a permission or authenticity certificate. Loading always rechecks source bytes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any
import wave
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from poseidon_proto import RecordingManifest, canonical_json, parse_json_object

from .errors import InputError

FORMAT = "poseidon-independent-dataset-provisional-v1"
LABELS = {"observed_predation", "hard_negative", "unknown", "unusable"}
SPLITS = {"train", "validation", "holdout"}
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_RECORDINGS = 2000
MAX_INTERVALS = 10000
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def number(value: Any, name: str, minimum: float = 0) -> float:
    if type(value) not in (int, float):
        raise InputError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise InputError(f"{name} must be finite") from exc
    if not math.isfinite(result) or result < minimum:
        raise InputError(f"{name} must be finite and >= {minimum}")
    return result


def exact(data: Any, keys: set[str], name: str) -> None:
    if type(data) is not dict or set(data) != keys:
        raise InputError(f"{name} requires exactly {', '.join(sorted(keys))}")


def text(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 2048:
        raise InputError(f"{name} must be nonempty text of at most 2048 characters")
    return value


def identifier(value: Any, name: str) -> str:
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise InputError(f"{name} must be a short plain identifier")
    return value


def contained_file(root: Path, relative: Any) -> Path:
    if type(relative) is not str or not relative or "\\" in relative:
        raise InputError("source path must be relative POSIX text")
    rel = Path(relative)
    if rel.is_absolute() or any(part in {"..", "."} for part in relative.split("/")):
        raise InputError("source path must stay inside the dataset directory")
    root = root.resolve()
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise InputError("symlink sources are not supported")
    try:
        info = current.stat()
        current.resolve().relative_to(root)
    except (OSError, ValueError) as exc:
        raise InputError(f"missing or escaped source: {relative}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise InputError("only regular file sources are supported; devices are forbidden")
    return current


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise InputError("source changed while hashing")
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise InputError("JSON input must be a regular non-symlink file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise InputError("JSON input exceeds 8 MiB")
    try:
        return parse_json_object(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise InputError(f"invalid dataset JSON: {exc}") from exc


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    """Never overwrite evidence, including partial output from a failed attempt."""
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _wav_details(path: Path) -> tuple[int, int, int]:
    try:
        with wave.open(str(path), "rb") as stream:
            frames, rate, channels = stream.getnframes(), stream.getframerate(), stream.getnchannels()
            if (stream.getsampwidth() != 2 or stream.getcomptype() != "NONE"
                    or not 1 <= channels <= 8 or not 1 <= rate <= 384000 or frames <= 0):
                raise InputError("dataset requires nonempty PCM16 WAV, 1..8 channels, <=384000 Hz")
            remaining = frames
            while remaining:
                count = min(remaining, 8192)
                if len(stream.readframes(count)) != count * channels * 2:
                    raise InputError("dataset WAV is truncated")
                remaining -= count
            if stream.readframes(1):
                raise InputError("dataset WAV has incomplete trailing frames")
            return frames, rate, channels
    except (EOFError, wave.Error) as exc:
        raise InputError(f"invalid dataset WAV: {exc}") from exc


def _annotations(values: Any, duration: float) -> None:
    if type(values) is not list or len(values) > MAX_INTERVALS:
        raise InputError(f"observations must be a list of at most {MAX_INTERVALS} intervals")
    seen: set[str] = set()
    previous_end = 0.0
    for value in values:
        exact(value, {"observation_id", "start_s", "end_s", "label", "observer_id",
                      "evidence_ref", "confidence", "visibility", "timing_uncertainty_s"}, "observation")
        oid = identifier(value["observation_id"], "observation_id")
        if oid in seen:
            raise InputError("duplicate observation_id")
        seen.add(oid)
        start, end = number(value["start_s"], "start_s"), number(value["end_s"], "end_s")
        if not previous_end <= start < end <= duration:
            raise InputError("observations must be ordered, non-overlapping and inside recording")
        previous_end = end
        if type(value["label"]) is not str or value["label"] not in LABELS:
            raise InputError("invalid independent observation label")
        identifier(value["observer_id"], "observer_id")
        text(value["evidence_ref"], "evidence_ref")
        if value["confidence"] not in ("high", "medium", "low"):
            raise InputError("invalid observation confidence")
        if value["visibility"] not in ("visible", "limited", "not_visible", "not_applicable"):
            raise InputError("invalid observation visibility")
        number(value["timing_uncertainty_s"], "timing_uncertainty_s")


def _validate(data: dict[str, Any], root: Path, *, sealed: bool) -> dict[str, Any]:
    keys = {"format", "dataset_name", "protocol_ref", "license", "site_holdout", "recordings"}
    exact(data, keys | ({"dataset_id"} if sealed else set()), "dataset")
    if data["format"] != FORMAT:
        raise InputError("unsupported dataset format")
    identifier(data["dataset_name"], "dataset_name")
    text(data["protocol_ref"], "protocol_ref")
    text(data["license"], "license")
    if type(data["site_holdout"]) is not bool:
        raise InputError("site_holdout must be a boolean")
    rows = data["recordings"]
    if type(rows) is not list or not 1 <= len(rows) <= MAX_RECORDINGS:
        raise InputError(f"dataset requires 1..{MAX_RECORDINGS} recording entries")
    result = {key: data[key] for key in keys if key != "recordings"}
    result["recordings"] = []
    group_splits: dict[tuple[str, str], str] = {}
    recording_ids: set[str] = set()
    hashes: set[str] = set()
    for row in rows:
        row_keys = {"wav_path", "recording_manifest_path", "split", "recording_group",
                    "local_date", "timezone", "observations"}
        bound_keys = {"recording_id", "site_id", "provenance", "wav_sha256", "manifest_sha256",
                      "frame_count", "sample_rate_hz", "channel_count", "duration_s", "covered_dates"}
        if type(row) is dict and "observation_import_path" in row:
            row_keys.add("observation_import_path")
            bound_keys.add("observation_import_sha256")
        if type(row) is dict and "platform_snapshot_path" in row:
            if "observation_import_path" not in row:
                raise InputError("Platform snapshot requires its linked observation import")
            row_keys.add("platform_snapshot_path")
            bound_keys.add("platform_snapshot_sha256")
        exact(row, row_keys | (bound_keys if sealed else set()), "recording entry")
        if type(row["split"]) is not str or row["split"] not in SPLITS:
            raise InputError("split must be train, validation or holdout")
        identifier(row["recording_group"], "recording_group")
        wav = contained_file(root, row["wav_path"])
        manifest_path = contained_file(root, row["recording_manifest_path"])
        try:
            manifest = RecordingManifest.from_dict(read_json(manifest_path))
        except ValueError as exc:
            raise InputError(f"invalid recording manifest: {exc}") from exc
        manifest_hash = sha256_file(manifest_path)
        before_hash = sha256_file(wav)
        if before_hash != manifest.wav_sha256:
            raise InputError("WAV checksum differs from recording manifest")
        frames, rate, channels = _wav_details(wav)
        if sha256_file(wav) != before_hash:
            raise InputError("WAV changed during dataset validation")
        if manifest.recording_id in recording_ids or before_hash in hashes:
            raise InputError("duplicate recording identity or source checksum would inflate evaluation")
        recording_ids.add(manifest.recording_id)
        hashes.add(before_hash)
        duration = frames / rate
        try:
            zone = ZoneInfo(text(row["timezone"], "timezone"))
            start = datetime.fromisoformat(manifest.started_at.replace("Z", "+00:00"))
            first_day = start.astimezone(zone).date()
            # Intervals include each sample's duration, not just its start instant.
            last_day = (start + timedelta(seconds=duration) - timedelta(microseconds=1)).astimezone(zone).date()
            if type(row["local_date"]) is not str or date.fromisoformat(row["local_date"]) != first_day:
                raise InputError("local_date differs from recording timestamp and timezone")
        except (ZoneInfoNotFoundError, ValueError, OverflowError) as exc:
            raise InputError(f"invalid local recording date/timezone: {exc}") from exc
        if (last_day - first_day).days > 366:
            raise InputError("recording spans more than 366 local days")
        covered_dates = [(first_day + timedelta(days=i)).isoformat()
                         for i in range((last_day - first_day).days + 1)]
        groups = [("recording_group", row["recording_group"])]
        groups += [("day", day) for day in covered_dates]
        if data["site_holdout"]:
            groups.append(("site", manifest.site_id))
        for group in groups:
            if group in group_splits and group_splits[group] != row["split"]:
                raise InputError(f"split leakage for {group[0]} {group[1]}")
            group_splits[group] = row["split"]
        _annotations(row["observations"], duration)
        bound = {"recording_id": manifest.recording_id, "site_id": manifest.site_id,
                 "provenance": manifest.provenance, "wav_sha256": before_hash,
                 "manifest_sha256": manifest_hash, "frame_count": frames, "sample_rate_hz": rate,
                 "channel_count": channels, "duration_s": duration, "covered_dates": covered_dates}
        if "observation_import_path" in row:
            from .observation_import import validate_import

            import_path = contained_file(root, row["observation_import_path"])
            imported = validate_import(import_path, manifest.recording_id, before_hash, manifest.provenance)
            if imported["protocol_acceptance"]["protocol_id"] != data["protocol_ref"]:
                raise InputError("dataset protocol must match explicit observation import acceptance")
            if canonical_json({"observations": imported["observations"]}) != canonical_json({"observations": row["observations"]}):
                raise InputError("dataset observations differ from lossless Platform import")
            if any(obs["end_s"] > duration for obs in imported["source_export"]["observations"]):
                raise InputError("exported observation exceeds recording, including excluded masks")
            bound["observation_import_sha256"] = sha256_file(import_path)
            if "platform_snapshot_path" in row:
                from .platform_dataset import validate_snapshot

                snapshot_path = contained_file(root, row["platform_snapshot_path"])
                snapshot = read_json(snapshot_path)
                validate_snapshot(snapshot, imported)
                platform_recording = snapshot["scan"]["recording"]
                if RecordingManifest.from_dict({key: platform_recording[key] for key in RecordingManifest.FIELDS}) != manifest:
                    raise InputError("Platform snapshot identity differs from recording manifest")
                if (platform_recording["duration_s"] != duration
                        or platform_recording["sample_rate_hz"] != rate
                        or platform_recording["channel_count"] != channels):
                    raise InputError("Platform recording media metadata differs from verified source")
                bound["platform_snapshot_sha256"] = sha256_file(snapshot_path)
        if sealed:
            for key, value in bound.items():
                if type(row[key]) is not type(value) or row[key] != value:
                    raise InputError(f"sealed recording {key} differs from verified source")
        result["recordings"].append({**{key: row[key] for key in row_keys}, **bound})
    digest = hashlib.sha256(canonical_json(result).encode()).hexdigest()
    result["dataset_id"] = "dataset_" + digest
    if sealed and data["dataset_id"] != result["dataset_id"]:
        raise InputError("dataset content hash mismatch")
    return result


def seal_dataset(spec_path: Path, output_path: Path) -> dict[str, Any]:
    if spec_path.parent.resolve() != output_path.parent.resolve():
        raise InputError("sealed manifest must live beside specification for stable relative paths")
    result = _validate(read_json(spec_path), spec_path.parent, sealed=False)
    write_new_json(output_path, result)
    return result


def load_dataset(path: Path) -> dict[str, Any]:
    return _validate(read_json(path), path.parent, sealed=True)


def data_card(data: dict[str, Any]) -> str:
    rows = data["recordings"]
    counts = {label: sum(value["label"] == label for row in rows for value in row["observations"])
              for label in sorted(LABELS)}
    synthetic = all(row["provenance"] == "synthetic" for row in rows)
    return "\n".join([
        f"# Dataset card: {data['dataset_name']}", "",
        f"Content identity: `{data['dataset_id']}`", "",
        "Synthetic software fixture only; no biological performance evidence." if synthetic else
        "Contains declared field provenance; declaration does not verify permissions or label truth.", "",
        f"Protocol: {data['protocol_ref']}", f"License/data terms: {data['license']}",
        f"Recordings: {len(rows)}. Source hours: {sum(row['duration_s'] for row in rows) / 3600:.8f}.",
        f"Site-held-out validation required: {data['site_holdout']}.",
        "Labels: " + json.dumps(counts, sort_keys=True), "",
        "Observations are independent of candidates. Unreviewed, unknown, unusable and excessive",
        "timing-uncertainty intervals are excluded from scored exposure, not treated as absence.",
        "Content hashes detect changes, not false provenance, permission, observer bias or duplicate",
        "re-encoded media. Recording groups and local dates must identify those dependencies.",
        "No calibrated underwater level, species detector, efficacy or field-release claim.", "",
    ])
