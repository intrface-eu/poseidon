"""Synthetic fixtures made by the actual acquisition session/exporter/reader."""
from __future__ import annotations

from dataclasses import replace
import io
import json
from pathlib import Path
import struct

from poseidon_acoustic.legacy_export import EpochDeclaration, SegmentMapping, export_segments
from poseidon_acoustic.legacy_export_reader import ExportReadLimits, file_map_resolver, validate_export_bundle
from poseidon_acoustic.session import Channel, ClockMap, Session, Source, canonical, pcm16_wav, sha256
from poseidon_proto.companion import DOCUMENT_ROLES, UPLOAD_ROLES


def make_exports(root: Path, *, capture_id="synthetic-capture", site="synthetic-site", device="synthetic-device", first_id="synthetic-first", later_id="synthetic-later", epoch_operator="synthetic-operator", final_encoding=None):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = Source("audio", "pcm16-wav", "synthetic",
                    (Channel("right", "synthetic right"), Channel("left", "synthetic left")),
                    ClockMap("reference_seconds", "synthetic-epoch", reference_anchor_s=0.25,
                             drift_ppm=1000, anchor_uncertainty_s=0.01, drift_uncertainty_ppm=20),
                    sample_rate_hz=8000, origin="Synthetic companion backend test fixture")
    capture = Session.create(root / "capture", capture_id, (source,))
    for index, start in enumerate((0, 8000)):
        units = 160
        sample = struct.pack("<hh", 20000, -20000) if index == 0 else b"\0" * 4
        capture.append("audio", pcm16_wav(sample * units, 8000, 2), unit_start=start, units=units,
                       source_start_s=start / 8000, source_end_s=(start + units) / 8000,
                       dropped_units=100 if index else 0, gap_reason="synthetic missing interval" if index else "")
    capture.finalize()
    if final_encoding is not None:
        final_path = capture.directory / "segments.acquisition-v1.json"
        final_object = json.loads(final_path.read_bytes())
        final_path.chmod(0o600)
        final_path.write_bytes(json.dumps(final_object, indent=2, sort_keys=True).encode(final_encoding))
        final_path.chmod(0o400)
    epoch = EpochDeclaration("audio", "reference_seconds", "synthetic-epoch", "2026-01-01T00:00:00Z",
                             0.005, epoch_operator, "synthetic-epoch-convention")
    mapping = SegmentMapping(0, first_id, site, "synthetic-zone", device)
    values = []
    for index, recording_id in ((0, first_id), (1, later_id)):
        directory = root / f"export-{index}"
        export_segments(capture.directory, directory, source_id="audio",
                        mappings=(replace(mapping, segment_index=index, recording_id=recording_id),), epoch=epoch)
        values.append(load_export(directory))
    return tuple(values)


def load_export(directory: Path):
    receipt = (directory / "export.receipt.json").read_bytes()
    files = {entry["path"]: (directory / entry["path"]).read_bytes() for entry in json.loads(receipt)["files"]}
    validated = validate_export_bundle(receipt, file_map_resolver(files), limits=ExportReadLimits())
    return {"directory": directory, "validated": validated,
            "bytes": {role: validated.file_for_role(role).data for role in UPLOAD_ROLES},
            "names": {role: validated.file_for_role(role).name for role in UPLOAD_ROLES}}


def context(hub, *, session_id="platform-context", site="synthetic-site", device="synthetic-device"):
    if hub.list_devices()["total"] == 0 or not any(row["id"] == device for row in hub.list_devices(limit=200)["items"]):
        hub.create_device({"id": device, "site_id": site, "label": "Synthetic companion import device", "kind": "hub",
                           "hardware_revision": "synthetic-r1", "source_kind": "synthetic"})
    return hub.create_session({"schema_version": "poseidon.acquisition-session.v1", "id": session_id,
                               "site_id": site, "device_id": device, "started_at": None, "ended_at": None,
                               "clock_quality": {"status": "unknown", "method": "unknown", "uncertainty_ms": None, "offset_ms": None, "reference": None},
                               "provenance": {"source_kind": "synthetic", "source_id": "audio", "transport": "import"},
                               "operator": "Synthetic manual context operator", "notes": "Manual scope only, not imported timing."})


def submit(hub, bundle, session_id="platform-context"):
    return hub.submit_recording_with_companions(io.BytesIO(bundle["bytes"]["wav"]), bundle["bytes"]["manifest"],
                                               {role: bundle["bytes"][role] for role in DOCUMENT_ROLES},
                                               session_id=session_id, filenames_by_role=bundle["names"])


def multipart(bundle):
    return [(role, (bundle["names"][role], bundle["bytes"][role], "audio/wav" if role == "wav" else "application/json")) for role in UPLOAD_ROLES]


def rewrite_binding(bundle, change):
    """Negative fixture: change a binding, honestly rewrite outer byte hashes."""
    result = {**bundle, "bytes": dict(bundle["bytes"]), "names": dict(bundle["names"])}
    binding = json.loads(result["bytes"]["binding"])
    change(binding)
    result["bytes"]["binding"] = canonical(binding)
    receipt = json.loads(result["bytes"]["export_receipt"])
    reference = {"path": result["names"]["binding"], "bytes": len(result["bytes"]["binding"]), "sha256": sha256(result["bytes"]["binding"])}
    receipt["exports"][0]["binding"] = reference
    receipt["files"] = [reference if item["path"] == reference["path"] else item for item in receipt["files"]]
    receipt["bytes_excluding_receipt"] = sum(len(data) for role, data in result["bytes"].items() if role != "export_receipt")
    result["bytes"]["export_receipt"] = canonical(receipt)
    return result
