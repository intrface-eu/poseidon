"""Bounded canonical Platform export -> independent dataset -> evaluation.

Only GET requests use the caller's authenticated client. Two complete matching
scans and revision histories detect changes; they are not a server-atomic snapshot.
No candidate filter or synthesized negative coverage is used.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import time
from typing import Any

from poseidon_proto import RecordingManifest, canonical_json, parse_json_object

from .dataset import (
    FORMAT, contained_file, data_card, exact, identifier, number, read_json,
    seal_dataset, sha256_file, text, write_new_json,
)
from .errors import InputError
from .evaluation import compare_thresholds
from .observation_import import EXPORT_FORMAT, convert_observations

SNAPSHOT_FORMAT = "poseidon-platform-observation-snapshot-v1"
PLAN_FORMAT = "poseidon-platform-dataset-plan-v1"


def digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise InputError(f"{name} must be an integer in {low}..{high}")
    return value


@dataclass(frozen=True)
class ExportLimits:
    page_size: int = 50
    max_observations: int = 1000
    max_revisions: int = 100
    max_requests: int = 5000
    max_page_bytes: int = 1024 * 1024
    max_total_json_bytes: int = 6 * 1024 * 1024
    max_source_bytes: int = 64 * 1024 * 1024
    max_recordings: int = 32
    max_elapsed_s: float = 120.0
    request_timeout_s: float = 10.0

    def __post_init__(self):
        for name, high in (("page_size", 200), ("max_observations", 10000), ("max_revisions", 10000),
                           ("max_requests", 20000), ("max_page_bytes", 8 * 1024 * 1024),
                           ("max_total_json_bytes", 32 * 1024 * 1024),
                           ("max_source_bytes", 1024 * 1024 * 1024), ("max_recordings", 2000)):
            _integer(getattr(self, name), name, 1, high)
        for name in ("max_elapsed_s", "request_timeout_s"):
            if not 0 < number(getattr(self, name), name) <= 3600:
                raise InputError(f"{name} must be positive and <=3600")


class ApiReader:
    """Works with httpx.Client or real FastAPI TestClient; neither is created here.

    Credentials belong to the client and are never serialized. Client closure and
    server ownership stay with the caller. Failed/oversized responses stop export.
    """
    def __init__(self, client, limits: ExportLimits | None = None):
        self.client = client
        self.limits = ExportLimits() if limits is None else limits
        if not isinstance(self.limits, ExportLimits):
            raise InputError("Platform export requires an ExportLimits configuration")
        self.started = time.monotonic()
        self.requests = 0
        self.received_bytes = 0

    def _budget(self):
        if time.monotonic() - self.started > self.limits.max_elapsed_s:
            raise InputError("Platform export elapsed-time budget exceeded")
        if self.requests >= self.limits.max_requests:
            raise InputError("Platform export request budget exceeded")

    def get(self, path: str, params: dict[str, int] | None = None) -> dict[str, Any]:
        if not path.startswith("/api/v1/") or "?" in path or "#" in path:
            raise InputError("only fixed local Platform API paths are allowed")
        self._budget()
        self.requests += 1
        chunks = []
        received = 0
        try:
            with self.client.stream("GET", path, params=params, timeout=self.limits.request_timeout_s,
                                    follow_redirects=False) as response:
                if response.status_code != 200:
                    raise InputError(f"Platform GET rejected with HTTP {response.status_code}")
                for chunk in response.iter_bytes(chunk_size=65536):
                    received += len(chunk)
                    self.received_bytes += len(chunk)
                    if received > self.limits.max_page_bytes or self.received_bytes > self.limits.max_total_json_bytes:
                        raise InputError("Platform export response byte budget exceeded")
                    if time.monotonic() - self.started > self.limits.max_elapsed_s:
                        raise InputError("Platform export elapsed-time budget exceeded")
                    chunks.append(chunk)
        except InputError:
            raise
        except Exception as exc:
            # Do not echo transport exception strings that may contain credentials.
            raise InputError("Platform GET transport failed; export incomplete") from exc
        try:
            return parse_json_object(b"".join(chunks).decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise InputError("Platform response is not strict JSON") from exc


def _page_scan(reader: ApiReader, path: str, maximum: int) -> tuple[list[dict], list[dict]]:
    pages, rows = [], []
    total = None
    offset = 0
    while True:
        page = reader.get(path, {"limit": reader.limits.page_size, "offset": offset})
        exact(page, {"items", "total", "limit", "offset"}, "Platform page")
        _integer(page["total"], "page total", 0, maximum)
        if (type(page["limit"]) is not int or page["limit"] != reader.limits.page_size
                or type(page["offset"]) is not int or page["offset"] != offset):
            raise InputError("Platform pagination offset/limit mismatch")
        if total is None:
            total = page["total"]
        if page["total"] != total:
            raise InputError("Platform population changed during pagination")
        expected = min(reader.limits.page_size, max(0, total - offset))
        if type(page["items"]) is not list or len(page["items"]) != expected:
            raise InputError("Platform page is truncated or omits declared items")
        if any(type(row) is not dict for row in page["items"]):
            raise InputError("Platform items must be objects")
        pages.append(page)
        rows.extend(page["items"])
        if offset == total:
            break
        offset += len(page["items"])
    return rows, pages


def _validated_recording(recording: dict[str, Any]) -> RecordingManifest:
    additional = {"duration_s", "sample_rate_hz", "channel_count", "event_count", "reviewed_count", "imported_at", "video"}
    exact(recording, RecordingManifest.FIELDS | additional, "Platform recording")
    manifest = RecordingManifest.from_dict({key: recording[key] for key in RecordingManifest.FIELDS})
    if number(recording["duration_s"], "recording duration") <= 0:
        raise InputError("recording must have positive duration")
    _integer(recording["sample_rate_hz"], "recording sample rate", 1, 384000)
    _integer(recording["channel_count"], "recording channels", 1, 8)
    _integer(recording["event_count"], "event count", 0, 2**53)
    _integer(recording["reviewed_count"], "reviewed count", 0, recording["event_count"])
    return manifest


def _scan(reader: ApiReader, recording_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    base = f"/api/v1/recordings/{recording_id}"
    recording = reader.get(base)
    manifest = _validated_recording(recording)
    if manifest.recording_id != recording_id:
        raise InputError("Platform returned another recording identity")
    rows, pages = _page_scan(reader, base + "/observations", reader.limits.max_observations)
    export = {"format": EXPORT_FORMAT, "recording_id": recording_id,
              "recording_sha256": manifest.wav_sha256, "source_kind": manifest.provenance,
              "observations": rows}
    convert_observations(export, policy)  # Canonical row/protocol/mask/duplicate validation.
    histories = []
    for row in rows:
        if row["end_s"] > recording["duration_s"]:
            raise InputError("Platform observation exceeds recording duration")
        identity = identifier(row["id"], "observation id")
        history, history_pages = _page_scan(reader, base + f"/observations/{identity}/history", reader.limits.max_revisions)
        if len(history) != row["revision"] or not history or canonical_json(history[-1]) != canonical_json(row):
            raise InputError("Platform current observation differs from complete revision history")
        for revision, old in enumerate(history, 1):
            if old.get("id") != identity or old.get("revision") != revision:
                raise InputError("Platform history is missing, duplicated or reordered")
            if old.get("created_at") != row["created_at"]:
                raise InputError("Platform creation identity changed across revisions")
            convert_observations({**export, "observations": [old]}, policy)
            if old["end_s"] > recording["duration_s"]:
                raise InputError("Platform historical observation exceeds recording duration")
        histories.append({"id": identity, "pages": history_pages})
    # Recording/source context must stay fixed through the complete history walk.
    if canonical_json(reader.get(base)) != canonical_json(recording):
        raise InputError("Platform recording changed during export")
    return {"recording": recording, "pages": pages, "histories": histories, "export": export}


def capture_snapshot(reader: ApiReader, recording_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    identifier(recording_id, "recording_id")
    identity = reader.get("/api/v1/identity")
    exact(identity, {"subject", "role", "site_ids", "device_id", "auth_mode"}, "API identity")
    text(identity["subject"], "authenticated subject")
    if identity["role"] not in ("viewer", "reviewer", "admin") or identity["device_id"] is not None:
        raise InputError("a human-scoped export identity is required")
    first = _scan(reader, recording_id, policy)
    second = _scan(reader, recording_id, policy)
    if canonical_json(first) != canonical_json(second):
        raise InputError("Platform observations/revisions changed between complete scans; retry explicitly")
    if canonical_json(reader.get("/api/v1/identity")) != canonical_json(identity):
        raise InputError("Platform identity changed during export")
    value = {"format": SNAPSHOT_FORMAT, "identity": identity, "limits": asdict(reader.limits),
             "scan": first, "matching_second_scan_sha256": digest(second),
             "protocol_acceptance_sha256": digest(policy),
             "scope": "all observation rows/histories for this explicitly selected recording, not all workspace recordings",
             "consistency": "two matching complete scans; no server-atomic snapshot token",
             "server_atomic_snapshot": False, "permissions_verified": False,
             "no_candidate_filter": True}
    value["snapshot_id"] = "platform_snapshot_" + digest(value)
    return value


def validate_snapshot(value: dict[str, Any], imported: dict[str, Any]) -> None:
    expected = {"format", "identity", "limits", "scan", "matching_second_scan_sha256",
                "protocol_acceptance_sha256", "scope", "consistency", "server_atomic_snapshot",
                "permissions_verified", "no_candidate_filter", "snapshot_id"}
    exact(value, expected, "Platform snapshot")
    if (value["format"] != SNAPSHOT_FORMAT or value["server_atomic_snapshot"] is not False
            or value["permissions_verified"] is not False or value["no_candidate_filter"] is not True):
        raise InputError("unsupported Platform snapshot claims")
    payload = {key: item for key, item in value.items() if key != "snapshot_id"}
    if value["snapshot_id"] != "platform_snapshot_" + digest(payload):
        raise InputError("Platform snapshot content hash mismatch")
    if value["matching_second_scan_sha256"] != digest(value["scan"]):
        raise InputError("Platform snapshot stable scan digest mismatch")
    if value["protocol_acceptance_sha256"] != digest(imported["protocol_acceptance"]):
        raise InputError("Platform snapshot protocol acceptance mismatch")
    if canonical_json(value["scan"]["export"]) != canonical_json(imported["source_export"]):
        raise InputError("Platform snapshot/import source mismatch")
    # Re-run page and history completeness logic against the preserved responses.
    source = _SnapshotReplay(value)
    scanned = _scan(source, imported["source_export"]["recording_id"], imported["protocol_acceptance"])
    if canonical_json(scanned) != canonical_json(value["scan"]):
        raise InputError("Platform snapshot response reconstruction mismatch")


class _SnapshotReplay:
    def __init__(self, snapshot):
        self.limits = ExportLimits(**snapshot["limits"])
        self.snapshot = snapshot

    def get(self, path, params=None):
        scan = self.snapshot["scan"]
        base = "/api/v1/recordings/" + scan["recording"]["recording_id"]
        if path == base:
            return scan["recording"]
        pages = scan["pages"] if path == base + "/observations" else None
        if pages is None:
            for history in scan["histories"]:
                if path == base + f"/observations/{history['id']}/history":
                    pages = history["pages"]
                    break
        if pages is None:
            raise InputError("missing captured Platform endpoint")
        matching = [page for page in pages if page["offset"] == params["offset"]]
        if len(matching) != 1:
            raise InputError("missing or duplicate captured Platform page")
        return matching[0]


def _copy_source(source: Path, destination: Path, expected_sha: str, budget: int) -> int:
    source = contained_file(source.parent, source.name)
    if source.stat().st_size > budget:
        raise InputError("source byte budget exceeded")
    digestor = hashlib.sha256()
    count = 0
    with source.open("rb") as stream, destination.open("xb") as output:
        while chunk := stream.read(65536):
            count += len(chunk)
            if count > budget:
                raise InputError("source byte budget exceeded during copy")
            digestor.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if digestor.hexdigest() != expected_sha or sha256_file(source) != expected_sha:
        raise InputError("source changed or differs from Platform recording")
    return count


def _publish_complete(output: Path, receipt: dict[str, Any]) -> None:
    pending = output / ".export-complete.pending"
    final = output / "export-complete.json"
    identity = None

    def sync_directory():
        fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    try:
        with pending.open("xb") as stream:
            identity = os.fstat(stream.fileno())
            stream.write((canonical_json(receipt) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, final, follow_symlinks=False)
        sync_directory()
        pending.unlink()
        sync_directory()
    except BaseException:
        try:
            if identity is not None and final.exists() and os.path.samestat(identity, final.lstat()):
                final.unlink()
                sync_directory()
        except OSError as cleanup_error:
            raise InputError("export completion failed and receipt retraction failed; do not use output") from cleanup_error
        raise


def build_dataset(reader: ApiReader, plan_path: Path, policy_path: Path, output: Path, *,
                  thresholds: list[float], window_ms: float = 20.0, min_iou: float = 0.1,
                  evaluation_split: str = "validation") -> dict[str, Any]:
    plan, policy = read_json(plan_path), read_json(policy_path)
    exact(plan, {"format", "dataset_name", "protocol_ref", "license", "site_holdout", "recordings"}, "export plan")
    if plan["format"] != PLAN_FORMAT:
        raise InputError("unsupported Platform dataset plan")
    if plan["protocol_ref"] != policy.get("protocol_id"):
        raise InputError("plan protocol must match explicit accepted protocol")
    if type(plan["recordings"]) is not list or not 1 <= len(plan["recordings"]) <= reader.limits.max_recordings:
        raise InputError("recording selection exceeds export budget")
    plans, seen = [], set()
    for row in plan["recordings"]:
        exact(row, {"recording_id", "wav_path", "recording_manifest_path", "recording_group", "local_date", "timezone", "split"}, "planned recording")
        rid = identifier(row["recording_id"], "recording_id")
        if rid in seen:
            raise InputError("duplicate selected recording")
        seen.add(rid)
        manifest_path = contained_file(plan_path.parent, row["recording_manifest_path"])
        manifest = RecordingManifest.from_dict(read_json(manifest_path))
        if manifest.recording_id != rid:
            raise InputError("planned recording differs from original manifest")
        wav_path = contained_file(plan_path.parent, row["wav_path"])
        plans.append((row, manifest, manifest_path, wav_path))
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    rows = []
    remaining = reader.limits.max_source_bytes
    for index, (row, manifest, manifest_path, wav_path) in enumerate(plans):
        snapshot = capture_snapshot(reader, row["recording_id"], policy)
        platform_manifest = _validated_recording(snapshot["scan"]["recording"])
        if platform_manifest != manifest:
            raise InputError("local manifest differs from authenticated Platform recording")
        imported = convert_observations(snapshot["scan"]["export"], policy)
        validate_snapshot(snapshot, imported)
        prefix = f"recording-{index:04d}"
        remaining -= _copy_source(wav_path, output / f"{prefix}.wav", manifest.wav_sha256, remaining)
        write_new_json(output / f"{prefix}.recording.json", manifest.to_dict())
        write_new_json(output / f"{prefix}.platform-snapshot.json", snapshot)
        write_new_json(output / f"{prefix}.observation-import.json", imported)
        rows.append({key: row[key] for key in ("recording_group", "local_date", "timezone", "split")} | {
            "wav_path": f"{prefix}.wav", "recording_manifest_path": f"{prefix}.recording.json",
            "observations": imported["observations"], "observation_import_path": f"{prefix}.observation-import.json",
            "platform_snapshot_path": f"{prefix}.platform-snapshot.json"})
    specification = {key: plan[key] for key in ("dataset_name", "protocol_ref", "license", "site_holdout")}
    specification.update(format=FORMAT, recordings=rows)
    write_new_json(output / "spec.json", specification)
    dataset = seal_dataset(output / "spec.json", output / "dataset.json")
    evaluation = compare_thresholds(output / "dataset.json", thresholds, window_ms=window_ms, min_iou=min_iou,
                                    max_timing_uncertainty_s=policy["max_sync_uncertainty_s"], split=evaluation_split)
    write_new_json(output / "evaluation.json", evaluation)
    with (output / "DATA_CARD.md").open("x", encoding="utf-8") as stream:
        stream.write(data_card(dataset))
    receipt = {"format": "poseidon-platform-dataset-export-complete-v1", "dataset_id": dataset["dataset_id"],
               "evaluation_id": evaluation["report_id"], "selected_recordings": len(rows),
               "no_candidate_filter": True, "biological_performance_claim": False,
               "request_count": reader.requests, "received_json_bytes": reader.received_bytes,
               "files": {path.name: sha256_file(path) for path in sorted(output.iterdir())}}
    _publish_complete(output, receipt)
    return receipt
