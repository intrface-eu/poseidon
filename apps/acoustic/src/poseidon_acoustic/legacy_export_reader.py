"""Pure bounded reader for one committed legacy export; never opens a path/device.

The resolver supplies six immutable files. Delivered bytes are verified, not
unavailable originals, physical timing, origin, permissions or full acquisition.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields
import math
import re

from poseidon_proto import RecordingManifest

from .legacy_export import (
    SCHEMA as EXPORT_SCHEMA, COMMIT, HARD_MAX_BYTES, HARD_MAX_SEGMENTS,
    EpochDeclaration, FileOriginDeclaration, SegmentMapping,
    _binding_document, _export_document, _provenance, _time_binding,
)
from .session import SCHEMA as SESSION_SCHEMA, Session, Source, canonical, safe_name, sha256, _parse_json_bytes, _validate_payload

ROLE_ORDER = ("wav", "manifest", "binding", "source_receipt", "source_header", "source_final", "export_receipt")
PROJECTION_SCHEMA = "poseidon.validated-single-export.v1"


class ExportReadError(ValueError):
    """Malformed, unsupported, missing, oversized or inconsistent delivered export."""


@dataclass(frozen=True, slots=True)
class ExportReadLimits:
    wav_bytes: int = 8_388_608
    manifest_bytes: int = 16_384
    binding_bytes: int = 262_144
    source_receipt_bytes: int = 16_384
    source_header_bytes: int = 1_048_576
    source_final_bytes: int = 2_097_152
    export_receipt_bytes: int = 65_536
    aggregate_companion_bytes: int = 4_194_304

    def __post_init__(self):
        for item in fields(self):
            _integer(getattr(self, item.name), item.name, 1, item.default)


@dataclass(frozen=True, slots=True)
class VerifiedExportFile:
    role: str
    name: str
    size: int
    sha256: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ValidatedExport:
    manifest: RecordingManifest
    capture_session_id: str
    source_id: str
    selected_index: int
    header_sha256: str
    final_sha256: str
    export_receipt_sha256: str
    files: tuple[VerifiedExportFile, ...]
    projection_bytes: bytes

    def file_for_role(self, role: str) -> VerifiedExportFile:
        for item in self.files:
            if item.role == role:
                return item
        raise KeyError(role)


def _integer(value, name, low=0, high=2**53):
    if type(value) is not int or not low <= value <= high:
        raise ExportReadError(f"{name} must be an integer in {low}..{high}")
    return value


def _number(value, name, low=None):
    if type(value) not in (int, float):
        raise ExportReadError(f"{name} must be finite numeric data")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (low is not None and value < low):
        raise ExportReadError(f"invalid {name}")
    return value


def _keys(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise ExportReadError(f"invalid {name} fields")


def _hash(value, name):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ExportReadError(f"invalid {name} SHA256")
    return value


def _same(first, second, name):
    # Canonical comparison does not equate bool/int or int/float spellings.
    if canonical(first) != canonical(second):
        raise ExportReadError(f"{name} is inconsistent with verified evidence")


def _parse(data, cap, name):
    if type(data) is not bytes or not 0 < len(data) <= cap:
        raise ExportReadError(f"{name} requires nonempty immutable bytes within its limit")
    try:
        value = _parse_json_bytes(data)
        if type(value) is not dict:
            raise ExportReadError(f"{name} JSON root must be an object")
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 32:
                raise ExportReadError("JSON nesting exceeds limit")
            if type(item) is dict:
                for key, child in item.items():
                    key.encode("utf-8")
                    pending.append((child, depth + 1))
            elif type(item) is list:
                pending.extend((child, depth + 1) for child in item)
            elif type(item) is str:
                item.encode("utf-8")
        # The accepted writer copies final bytes verbatim and validates their
        # parsed semantics. Other roles are required/emitted canonical bytes.
        if name != "source_final" and canonical(value) != data:
            raise ExportReadError(f"{name} is not exact session-canonical JSON with newline")
        return value
    except ExportReadError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ExportReadError(f"invalid {name} JSON") from exc


def file_map_resolver(files: Mapping[str, bytes]) -> Callable[[str, int], bytes]:
    """Snapshot six provided files; later caller map mutation cannot change reads."""
    if not isinstance(files, Mapping) or len(files) != 6:
        raise ExportReadError("exactly six receipt-listed files are required")
    snapshot = []
    for name, data in files.items():
        try:
            safe_name(name)
        except ValueError as exc:
            raise ExportReadError("file-map key must be a safe plain basename") from exc
        if type(data) is not bytes:
            raise ExportReadError("file-map values must be immutable bytes")
        snapshot.append((name, data))
    frozen = tuple(snapshot)

    def resolve(name, max_bytes):
        for key, value in frozen:
            if key == name:
                if len(value) > max_bytes:
                    raise ExportReadError("resolved file exceeds role limit")
                return value
        raise ExportReadError("missing receipt-listed file")
    return resolve


def _reference(value, name, cap):
    _keys(value, {"path", "bytes", "sha256"}, "file reference")
    if value["path"] != name:
        raise ExportReadError("unexpected file role/name")
    _integer(value["bytes"], "file byte count", 1, cap)
    _hash(value["sha256"], "file")


def _header(value):
    _keys(value, {"schema", "session_id", "sources", "max_bytes", "max_chunks", "hardware_verified",
                  "calibration", "finalize_reserve_bytes"}, "source header")
    if value["schema"] != SESSION_SCHEMA or value["hardware_verified"] is not False or value["calibration"] != "unverified":
        raise ExportReadError("unsupported source header or hardware/calibration claim")
    safe_name(value["session_id"])
    _integer(value["max_chunks"], "source max_chunks", 1, 4096)
    _integer(value["max_bytes"], "source max_bytes", 1, 2**40)
    _integer(value["finalize_reserve_bytes"], "source reserve", 1, 2**40)
    if value["finalize_reserve_bytes"] != Session.reserve(value["max_chunks"]):
        raise ExportReadError("invalid source finalization reserve")
    if value["max_bytes"] < value["finalize_reserve_bytes"] + len(canonical(value)) + 1024:
        raise ExportReadError("source storage budget cannot hold its declared reserve")
    if type(value["sources"]) is not list or not 1 <= len(value["sources"]) <= 16:
        raise ExportReadError("source count outside bound")
    sources = []
    for raw in value["sources"]:
        source = Source.from_dict(raw)
        _same(raw, asdict(source), "explicit original source declaration")
        sources.append(source)
    Session._validate_sources(tuple(sources))  # Pure identity/domain validation, no Session instance.
    return {source.source_id: source for source in sources}


def _final(value, header, header_hash, sources):
    _keys(value, {"schema", "session_id", "header_sha256", "hardware_verified", "state", "capture_extent",
                  "halt", "uncommitted_files", "uncommitted_artifacts", "segments", "accounting"}, "source final")
    if (value["schema"] != SESSION_SCHEMA + ".segments" or value["session_id"] != header["session_id"]
            or value["header_sha256"] != header_hash or value["hardware_verified"] is not False
            or value["state"] != "finalized" or value["halt"] is not None
            or value["uncommitted_files"] != [] or value["uncommitted_artifacts"] != []
            or value["capture_extent"] != "stored_segments_only; trailing_extent_not_attested"):
        raise ExportReadError("normal finalized stored-prefix source required; no completeness upgrade")
    segments = value["segments"]
    if type(segments) is not list or not 1 <= len(segments) <= header["max_chunks"]:
        raise ExportReadError("invalid final segment count")
    for index, segment in enumerate(segments):
        _keys(segment, {"receipt", "receipt_sha256", "path", "sha256", "source_id"}, "final segment")
        if segment["source_id"] not in sources:
            raise ExportReadError("unknown source in final segment")
        extension = "wav" if sources[segment["source_id"]].media == "pcm16-wav" else "pgm"
        if segment["receipt"] != f"chunk-{index:06d}.json" or segment["path"] != f"chunk-{index:06d}.{extension}":
            raise ExportReadError("missing/reordered/unsafe final segment paths")
        _hash(segment["receipt_sha256"], "final receipt")
        _hash(segment["sha256"], "final payload")
    _keys(value["accounting"], sources, "source accounting identities")
    for source_id, accounting in value["accounting"].items():
        _keys(accounting, {"stored_units", "missing_units", "dropped_units", "gap_source_s"}, "source accounting")
        for name in ("stored_units", "missing_units", "dropped_units"):
            _integer(accounting[name], name)
        if accounting["dropped_units"] > accounting["missing_units"]:
            raise ExportReadError("source dropped count exceeds missing count")
        _number(accounting["gap_source_s"], "source time gaps", 0)
        if not any(segment["source_id"] == source_id for segment in segments):
            _same(accounting, {"stored_units": 0, "missing_units": 0, "dropped_units": 0, "gap_source_s": 0}, "unused source accounting")


def _selected_receipt(value, source, final, index, payload, header_hash):
    expected_keys = {"schema", "index", "header_sha256", "previous_receipt_sha256", "source_id", "path",
                     "sha256", "bytes", "unit_start", "units", "source_start_s", "source_end_s",
                     "reference_start_s", "reference_end_s", "start_uncertainty_s", "end_uncertainty_s",
                     "missing_units", "dropped_units", "unexplained_missing_units", "gap_source_s", "gap_reason"}
    _keys(value, expected_keys, "selected receipt")
    _integer(value["index"], "selected receipt index", 0, 4095)
    if (value["schema"] != SESSION_SCHEMA + ".chunk" or value["index"] != index
            or value["header_sha256"] != header_hash or value["source_id"] != source.source_id
            or value["path"] != f"chunk-{index:06d}.wav" or value["sha256"] != sha256(payload)):
        raise ExportReadError("selected receipt identity/hash mismatch")
    _integer(value["bytes"], "selected payload bytes", 1, 8_388_608)
    if value["bytes"] != len(payload):
        raise ExportReadError("selected payload size mismatch")
    predecessor = None if index == 0 else final["segments"][index - 1]["receipt_sha256"]
    if value["previous_receipt_sha256"] != predecessor:
        raise ExportReadError("previous receipt link differs from supplied final declaration")
    start_unit = _integer(value["unit_start"], "unit start")
    units = _integer(value["units"], "units", 1)
    if start_unit + units > 2**53:
        raise ExportReadError("selected unit extent exceeds bound")
    missing = _integer(value["missing_units"], "missing units", 0, start_unit)
    dropped = _integer(value["dropped_units"], "dropped units", 0, missing)
    if type(value["unexplained_missing_units"]) is not int or value["unexplained_missing_units"] != missing - dropped:
        raise ExportReadError("unexplained missing-unit accounting mismatch")
    start = _number(value["source_start_s"], "source start")
    end = _number(value["source_end_s"], "source end")
    gap = _number(value["gap_source_s"], "source gap", 0)
    if (end <= start or start < source.source_origin_s - 1e-9
            or gap > start - source.source_origin_s + 1e-9
            or not math.isclose(end - start, units / source.sample_rate_hz, rel_tol=1e-9, abs_tol=1e-9)):
        raise ExportReadError("selected source duration/gap disagrees with nominal samples")
    if type(value["gap_reason"]) is not str or len(value["gap_reason"]) > 256 or ((missing or gap > 1e-9) and not value["gap_reason"].strip()):
        raise ExportReadError("selected discontinuity requires bounded explicit reason")
    prior_same_source = any(segment["source_id"] == source.source_id for segment in final["segments"][:index])
    if not prior_same_source:
        if missing != start_unit or gap != max(0.0, start - source.source_origin_s):
            raise ExportReadError("first source receipt origin accounting mismatch")
    ref_start, start_u = source.clock.at(start)
    ref_end, end_u = source.clock.at(end)
    if ref_end <= ref_start:
        raise ExportReadError("selected reference interval collapses")
    _same({key: value[key] for key in ("reference_start_s", "reference_end_s", "start_uncertainty_s", "end_uncertainty_s")},
          {"reference_start_s": ref_start, "reference_end_s": ref_end,
           "start_uncertainty_s": start_u, "end_uncertainty_s": end_u}, "selected clock projection")
    _validate_payload(source, payload, units)  # Real shared PCM16 format/rate/channel/frame validation.
    accounting = final["accounting"][source.source_id]
    local = {"stored_units": units, "missing_units": missing, "dropped_units": dropped, "gap_source_s": gap}
    if any(accounting[key] < number for key, number in local.items()):
        raise ExportReadError("source accounting is smaller than its delivered selected receipt")
    if sum(segment["source_id"] == source.source_id for segment in final["segments"]) == 1:
        _same(accounting, local, "single-source-receipt accounting")


def validate_export_bundle(export_receipt_bytes: bytes,
                           bounded_read_only_file_resolver: Callable[[str, int], bytes], *,
                           limits: ExportReadLimits) -> ValidatedExport:
    """Validate one complete selected export with a caller-owned bounded resolver.

    Calls resolver(name, max_bytes) exactly once per six expected plain filenames.
    No filesystem, recovery, writer, codec, device, network or mutable output API.
    """
    try:
        return _validate(export_receipt_bytes, bounded_read_only_file_resolver, limits)
    except ExportReadError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ExportReadError("invalid or inconsistent delivered export") from exc


def _validate(export_receipt_bytes, resolver, limits):
    if type(limits) is not ExportReadLimits or not callable(resolver):
        raise ExportReadError("explicit ExportReadLimits and bounded file resolver required")
    document = _parse(export_receipt_bytes, limits.export_receipt_bytes, "export receipt")
    if document.get("schema") != EXPORT_SCHEMA + ".receipt" or document.get("state") != "export_committed":
        raise ExportReadError("committed accepted export receipt required")
    exports = document.get("exports")
    if type(exports) is not list or len(exports) != 1 or type(document.get("selected_segments")) is not int or document["selected_segments"] != 1:
        raise ExportReadError("exactly one selected export is supported")
    entry = exports[0]
    _keys(entry, {"segment_index", "recording_id", "wav", "manifest", "binding"}, "selected export")
    index = _integer(entry["segment_index"], "selected index", 0, 4095)
    safe_name(entry["recording_id"])
    names = {"wav": f"chunk-{index:06d}.wav", "manifest": f"recording-{index:06d}.v1.json",
             "binding": f"binding-{index:06d}.json", "source_receipt": f"source-receipt-{index:06d}.json",
             "source_header": "source-header.json", "source_final": "source-final.json"}
    file_records = document.get("files")
    if type(file_records) is not list or len(file_records) != 6:
        raise ExportReadError("receipt must list exactly six files")
    if {item.get("path") for item in file_records if type(item) is dict} != set(names.values()):
        raise ExportReadError("receipt file set does not match six fixed roles")
    refs, raw, objects = {}, {}, {}
    for role, name in names.items():
        reference = next(item for item in file_records if item["path"] == name)
        cap = getattr(limits, role + "_bytes")
        _reference(reference, name, cap)
        refs[role] = reference
    companion_bytes = len(export_receipt_bytes) + sum(refs[role]["bytes"] for role in names if role not in ("wav", "manifest"))
    if companion_bytes > limits.aggregate_companion_bytes:
        raise ExportReadError("aggregate companion limit exceeded")
    for role, name in names.items():
        try:
            data = resolver(name, getattr(limits, role + "_bytes"))
        except Exception as exc:
            raise ExportReadError("cannot resolve required bounded file") from exc
        if type(data) is not bytes or len(data) != refs[role]["bytes"] or sha256(data) != refs[role]["sha256"]:
            raise ExportReadError(f"{role} raw byte/hash/size mismatch")
        raw[role] = data
        if role != "wav":
            objects[role] = _parse(data, getattr(limits, role + "_bytes"), role)
    header, final, record, binding = (objects[role] for role in ("source_header", "source_final", "source_receipt", "binding"))
    sources = _header(header)
    _final(final, header, refs["source_header"]["sha256"], sources)
    if sum(len(raw[role]) for role in ("source_header", "source_final", "source_receipt", "wav")) > header["max_bytes"]:
        raise ExportReadError("delivered original source bytes exceed source storage budget")
    source_id = document["source_id"]
    safe_name(source_id)
    if source_id not in sources or index >= len(final["segments"]):
        raise ExportReadError("selected source/segment absent from final")
    source = sources[source_id]
    if source.media != "pcm16-wav" or len(source.channels) > 8 or source.sample_rate_hz > 384000:
        raise ExportReadError("selected source is outside legacy PCM16 limits")
    selected = final["segments"][index]
    _same(selected, {"receipt": f"chunk-{index:06d}.json", "receipt_sha256": refs["source_receipt"]["sha256"],
                     "path": names["wav"], "sha256": refs["wav"]["sha256"], "source_id": source_id}, "selected final entry")
    _selected_receipt(record, source, final, index, raw["wav"], refs["source_header"]["sha256"])
    mapping = SegmentMapping(**binding["mapping"])
    if mapping.segment_index != index or mapping.recording_id != entry["recording_id"]:
        raise ExportReadError("selected recording mapping mismatch")
    epoch = EpochDeclaration(**binding["time"]["epoch_declaration"])
    if (epoch.source_id, epoch.reference_domain, epoch.reference_epoch) != (source_id, source.clock.reference_domain, source.clock.reference_epoch):
        raise ExportReadError("epoch identity differs from original source clock")
    declared_origin = binding["provenance"]["file_origin_declaration"]
    origin = None if declared_origin is None else FileOriginDeclaration(**declared_origin)
    kind, provenance = _provenance(asdict(source), origin)
    timing = _time_binding(epoch, record, asdict(source))
    manifest = RecordingManifest.from_dict(objects["manifest"])
    expected_manifest = RecordingManifest.from_dict({"schema_version": 1, "recording_id": mapping.recording_id,
        "site_id": mapping.site_id, "zone_id": mapping.zone_id, "device_id": mapping.device_id,
        "started_at": timing["started_at"], "provenance": kind, "wav_sha256": refs["wav"]["sha256"],
        "calibration_status": "uncalibrated"})
    if manifest != expected_manifest or raw["manifest"] != (expected_manifest.to_json() + "\n").encode():
        raise ExportReadError("legacy manifest differs from accepted source/time/origin mapping")
    expected_binding = _binding_document(final=final, source=asdict(source), receipt=record, mapping=mapping,
        header_ref=refs["source_header"], final_ref=refs["source_final"], receipt_ref=refs["source_receipt"],
        wav_ref=refs["wav"], manifest_ref=refs["manifest"], timing=timing, provenance_binding=provenance)
    _same(binding, expected_binding, "binding projection")
    _keys(document["limits"], {"max_bytes", "max_segments"}, "export producer limits")
    max_bytes = _integer(document["limits"]["max_bytes"], "producer max bytes", 1, HARD_MAX_BYTES)
    max_segments = _integer(document["limits"]["max_segments"], "producer max segments", 1, HARD_MAX_SEGMENTS)
    bytes_used = sum(len(data) for data in raw.values())
    if bytes_used + len(export_receipt_bytes) > max_bytes:
        raise ExportReadError("export bytes exceed producer's declared limit")
    expected_entry = {"segment_index": index, "recording_id": mapping.recording_id,
                      "wav": refs["wav"], "manifest": refs["manifest"], "binding": refs["binding"]}
    expected_document = _export_document(final=final, source_id=source_id, header_ref=refs["source_header"],
        final_ref=refs["source_final"], exports=[expected_entry], max_bytes=max_bytes, max_segments=max_segments,
        file_records=sorted(refs.values(), key=lambda item: item["path"]), bytes_used=bytes_used)
    _same(document, expected_document, "export receipt projection")
    verified = tuple(VerifiedExportFile(role, names.get(role, COMMIT), len(raw[role]) if role in raw else len(export_receipt_bytes),
                      refs[role]["sha256"] if role in refs else sha256(export_receipt_bytes),
                      raw[role] if role in raw else export_receipt_bytes) for role in ROLE_ORDER)
    coverage = {"delivered_file_bytes_verified": True, "selected_segment_bytes_verified": True,
                "selected_projection_consistency_verified": True, "upstream_hash_links_consistent": True,
                "full_original_session_bytes_verified": False, "original_input_bytes_verified": False,
                "unselected_segment_bytes_verified": False, "predecessor_receipt_bytes_verified": False,
                "acquisition_completeness_verified": False, "clock_relation_verified": False,
                "epoch_declaration_verified": False, "origin_verified": False, "authorization_verified": False,
                "hardware_verified": False, "calibration_verified": False}
    projection = {"schema": PROJECTION_SCHEMA, "manifest": manifest.to_dict(), "recording_id": manifest.recording_id,
        "capture_session_id": final["session_id"], "source_id": source_id, "selected_index": index, "source_kind": kind,
        "header_sha256": refs["source_header"]["sha256"], "final_sha256": refs["source_final"]["sha256"],
        "export_receipt_sha256": sha256(export_receipt_bytes), "source": asdict(source), "mapping": asdict(mapping),
        "selected_receipt": record, "time": timing, "provenance": provenance,
        "acquisition_state": final["state"], "capture_extent": final["capture_extent"],
        "source_accounting": final["accounting"][source_id], "verification": coverage,
        "files": [{"role": item.role, "name": item.name, "size": item.size, "sha256": item.sha256} for item in verified]}
    return ValidatedExport(manifest, final["session_id"], source_id, index, refs["source_header"]["sha256"],
                           refs["source_final"]["sha256"], sha256(export_receipt_bytes), verified, canonical(projection))
