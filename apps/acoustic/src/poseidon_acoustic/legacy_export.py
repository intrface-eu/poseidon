"""Bound finalized acquisition segments to unchanged RecordingManifest v1 replay.

This is a local, uncalibrated export, not session ingestion or verified UTC/field
provenance. The companion binding is required to interpret v1's lossy metadata.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import os
from pathlib import Path
import re
import stat

from poseidon_proto import RecordingManifest

from .session import (
    FINAL, HEADER, MAX_CHUNK_BYTES, Session, SessionError, canonical, finite,
    load_json, positive_int, publish, read_bounded, safe_name, sha256,
)


SCHEMA = "poseidon.legacy-segment-export.provisional.v1"
COMMIT = "export.receipt.json"
DEFAULT_MAX_BYTES = 16 * 1024 * 1024
HARD_MAX_BYTES = 256 * 1024 * 1024
HARD_MAX_SEGMENTS = 256
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)\Z")


class ExportError(SessionError):
    """An export cannot preserve the stated identity, time or format contract."""


def _text(value: str, name: str, limit: int = 1024) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ExportError(f"explicit bounded {name} required")


def _utc(value: str) -> datetime:
    # -00:00 means an unknown local offset, not an accepted UTC relation.
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ExportError("epoch_utc must be RFC3339 UTC (Z or +00:00), with at most six fractional digits")
    if int(value[11:13]) > 23 or int(value[14:16]) > 59 or int(value[17:19]) > 59:
        raise ExportError("invalid epoch_utc time; 24:00 and leap-second normalization are not accepted")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExportError("invalid or out-of-range epoch_utc date") from exc


@dataclass(frozen=True)
class EpochDeclaration:
    """Operator claim: reference_s=0 for this named source/domain/epoch is UTC."""

    source_id: str
    reference_domain: str
    reference_epoch: str
    epoch_utc: str
    uncertainty_s: float
    declared_by: str
    evidence_ref: str

    def __post_init__(self):
        safe_name(self.source_id)
        safe_name(self.reference_domain)
        _text(self.reference_epoch, "reference_epoch", 256)
        _utc(self.epoch_utc)
        finite(self.uncertainty_s, "epoch uncertainty", nonnegative=True)
        _text(self.declared_by, "epoch declarant", 256)
        _text(self.evidence_ref, "epoch evidence reference")


@dataclass(frozen=True)
class FileOriginDeclaration:
    """Independent origin claim for an original input checksum, never a permit."""

    source_id: str
    input_sha256: str
    origin: str
    declared_by: str
    evidence_ref: str

    def __post_init__(self):
        safe_name(self.source_id)
        if not isinstance(self.input_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.input_sha256):
            raise ExportError("file origin requires the original input SHA-256")
        if not isinstance(self.origin, str) or self.origin not in {"field", "bench"}:
            raise ExportError("file origin must be explicitly field or bench")
        _text(self.declared_by, "origin declarant", 256)
        _text(self.evidence_ref, "origin evidence reference")


@dataclass(frozen=True)
class SegmentMapping:
    segment_index: int
    recording_id: str
    site_id: str
    zone_id: str
    device_id: str

    def __post_init__(self):
        if type(self.segment_index) is not int or not 0 <= self.segment_index < 4096:
            raise ExportError("invalid segment index")
        for name in ("recording_id", "site_id", "zone_id", "device_id"):
            safe_name(getattr(self, name))


def _real_directory(path: Path | str) -> Path:
    """Reject symlinks in supplied paths, including directory components."""
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ExportError("parent traversal is not allowed")
    for item in (*reversed(path.parents), path):
        if not stat.S_ISDIR(item.lstat().st_mode):
            raise ExportError(f"directory must be real, not a symlink or device: {item}")
    return path


def _new_output(path: Path | str) -> Path:
    path = Path(path).absolute()
    _real_directory(path.parent)
    if path.name in {"", ".", ".."}:
        raise ExportError("new output directory required")
    try:
        path.lstat()
    except FileNotFoundError:
        return path
    raise ExportError("output path already exists; nothing will be overwritten")


def _time_at(epoch: datetime, seconds: Decimal) -> tuple[datetime, Decimal]:
    # Check before Decimal quantization/timedelta construction, including huge
    # finite inputs. datetime supports only Gregorian years 1 through 9999.
    if not seconds.is_finite() or abs(seconds) > Decimal(315537897600):
        raise ExportError("UTC relation is out of datetime range")
    with localcontext() as context:
        context.prec = 80
        lower = datetime.min.replace(tzinfo=epoch.tzinfo) - epoch
        upper = datetime.max.replace(tzinfo=epoch.tzinfo) - epoch
        limits = [Decimal((bound.days * 86400 + bound.seconds) * 1000000 + bound.microseconds) / 1000000
                  for bound in (lower, upper)]
        if not limits[0] <= seconds <= limits[1]:
            raise ExportError("UTC relation or uncertainty envelope is out of datetime range")
        micros = (seconds * 1000000).to_integral_value(rounding=ROUND_HALF_EVEN)
        rounding = micros / 1000000 - seconds
    try:
        result = epoch + timedelta(microseconds=int(micros))
    except (OverflowError, ValueError) as exc:
        raise ExportError("UTC relation is out of datetime range") from exc
    return result, rounding


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _time_binding(epoch: EpochDeclaration, receipt: dict, source: dict) -> dict:
    base = _utc(epoch.epoch_utc)
    with localcontext() as context:
        context.prec = 80
        start = Decimal(str(receipt["reference_start_s"]))
        end = Decimal(str(receipt["reference_end_s"]))
        start_dt, rounding = _time_at(base, start)
        end_dt, end_rounding = _time_at(base, end)
        if end_dt <= start_dt:
            raise ExportError("reference interval is ambiguous at v1 microsecond resolution")
        start_u = Decimal(str(receipt["start_uncertainty_s"])) + Decimal(str(epoch.uncertainty_s))
        end_u = Decimal(str(receipt["end_uncertainty_s"])) + Decimal(str(epoch.uncertainty_s))
        # Refuse dates whose stated uncertainty envelope cannot be represented.
        _time_at(base, start - start_u)
        _time_at(base, start + start_u)
        _time_at(base, end - end_u)
        _time_at(base, end + end_u)
        nominal_duration = Decimal(receipt["units"]) / Decimal(source["sample_rate_hz"])
        nominal_end, _ = _time_at(start_dt, nominal_duration)
        if nominal_end <= start_dt:
            raise ExportError("nominal WAV interval is ambiguous at v1 microsecond resolution")
        return {
            "epoch_declaration": asdict(epoch),
            "epoch_declaration_verified": False,
            "epoch_relation": "UTC = epoch_utc + reference_s seconds; reference_s=0 at named epoch",
            "started_at": _stamp(start_dt),
            "reference_ended_at": _stamp(end_dt),
            "nominal_wav_ended_at": _stamp(nominal_end),
            "started_at_rounding_error_s": str(rounding),
            "reference_end_rounding_error_s": str(end_rounding),
            "combined_start_uncertainty_s": str(start_u + abs(rounding)),
            "combined_end_uncertainty_s": str(end_u + abs(end_rounding)),
            "uncertainty_combination": "sum of declared bounds plus timestamp rounding; not statistically validated",
            "clock_relation_verified": False,
            "v1_candidate_offsets": "segment-local nominal WAV seconds (frame/sample_rate_hz), not drift-corrected UTC",
            "candidate_reference_mapping": "source.clock.at(receipt.source_start_s + candidate_frame/sample_rate_hz)",
            "nominal_duration_s": str(nominal_duration),
            "reference_duration_s": str(end - start),
            "resampled_for_clock_drift": False,
        }


def _provenance(source: dict, declaration: FileOriginDeclaration | None) -> tuple[str, dict]:
    if source["provenance"] == "synthetic":
        if declaration is not None:
            raise ExportError("synthetic source cannot take a file-origin declaration or be relabeled")
        return "synthetic", {"original_provenance": "synthetic", "file_origin_declaration": None,
                             "origin_verified": False, "authorization_verified": False}
    if source["provenance"] != "file":
        raise ExportError("unknown source provenance")
    if not isinstance(declaration, FileOriginDeclaration):
        raise ExportError("file provenance is unresolved; independent field/bench origin declaration required")
    if (declaration.source_id != source["source_id"] or not source["input_sha256"]
            or declaration.input_sha256 != source["input_sha256"]):
        raise ExportError("file origin declaration disagrees with source identity or original input SHA-256")
    if declaration.origin != "field":
        raise ExportError("bench origin is not supported by RecordingManifest v1; cannot relabel as field")
    return "field", {"original_provenance": "file", "file_origin_declaration": asdict(declaration),
                     "origin_verified": False, "authorization_verified": False}


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _commit(directory: Path, data: bytes) -> None:
    """Publish last; roll back only our receipt link on a reported I/O failure."""
    pending = directory / ".export-receipt.pending"
    target = directory / COMMIT
    identity = None
    linked = False
    try:
        with pending.open("xb") as stream:
            identity = os.fstat(stream.fileno())
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, target, follow_symlinks=False)
        linked = True
        _sync_directory(directory)
        pending.unlink()
        _sync_directory(directory)
    except BaseException as exc:
        if linked:
            try:
                if os.path.samestat(identity, target.lstat()):
                    target.unlink()
                    _sync_directory(directory)
            except OSError as cleanup_error:
                exc.add_note(f"cannot retract export receipt: {cleanup_error}; do not use this failed output")
        raise


def _binding_document(*, final, source, receipt, mapping, header_ref, final_ref,
                      receipt_ref, wav_ref, manifest_ref, timing, provenance_binding) -> dict:
    """Pure accepted projection shared by the writer and delivered-bundle reader."""
    segment = final["segments"][mapping.segment_index]
    return {
        "schema": SCHEMA + ".binding", "session_id": final["session_id"],
        "source_id": source["source_id"], "mapping": asdict(mapping), "source": source,
        "original_header": {"path": HEADER, "exported_copy": header_ref},
        "original_final": {"path": FINAL, "exported_copy": final_ref},
        "original_receipt": {"path": segment["receipt"], "exported_copy": receipt_ref, "record": receipt},
        "original_segment": {"path": receipt["path"], "sha256": receipt["sha256"], "bytes": receipt["bytes"]},
        "exported_wav": wav_ref, "recording_manifest": manifest_ref,
        "bytes_transformed": False,
        "copy_operation": "byte-identical entire segment WAV; no trimming, synthesis, mixing, rate change or calibration",
        "time": timing, "provenance": provenance_binding,
        "acquisition_state": final["state"], "capture_extent": final["capture_extent"],
        "source_accounting": final["accounting"][source["source_id"]],
        "acquisition_completeness_verified": False, "calibration_status": "uncalibrated",
        "hardware_verified": False, "authorization_verified": False,
        "metadata_loss_in_v1": ["source/channel identities", "clock relation/epoch/uncertainty",
                                "session extent/gaps/drops", "origin declarations and evidence references"],
    }


def _export_document(*, final, source_id, header_ref, final_ref, exports, max_bytes,
                     max_segments, file_records, bytes_used) -> dict:
    """Pure receipt shape; verification of supplied bytes belongs to its caller."""
    return {
        "schema": SCHEMA + ".receipt", "state": "export_committed",
        "session_id": final["session_id"], "source_id": source_id,
        "original_header": header_ref, "original_final": final_ref,
        "acquisition_state": final["state"], "capture_extent": final["capture_extent"],
        "acquisition_completeness_verified": False,
        "selected_segments": len(exports), "session_segments": len(final["segments"]),
        "source_segments": sum(item["source_id"] == source_id for item in final["segments"]),
        "exports": exports, "limits": {"max_bytes": max_bytes, "max_segments": max_segments},
        "files": file_records, "bytes_excluding_receipt": bytes_used,
        "interpretation": "retain companion bindings; v1 alone omits acquisition identity, timing and provenance claims",
    }


def export_segments(
    session_directory: Path | str,
    output_directory: Path | str,
    *,
    source_id: str,
    mappings: tuple[SegmentMapping, ...],
    epoch: EpochDeclaration,
    file_origin: FileOriginDeclaration | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_segments: int = 128,
) -> dict:
    """Export one source's explicitly selected, finalized PCM16 segments.

    All abnormal final states are refused. A normal finalized session still only
    attests its stored segments, never completion of an intended acquisition.
    Output parent must exist. Failure preserves evidence and partial output;
    only export.receipt.json commits the entire selected export set.
    """
    positive_int(max_bytes, "export byte budget", maximum=HARD_MAX_BYTES)
    positive_int(max_segments, "export segment budget", maximum=HARD_MAX_SEGMENTS)
    safe_name(source_id)
    if (not isinstance(mappings, tuple) or not 0 < len(mappings) <= max_segments
            or any(not isinstance(item, SegmentMapping) for item in mappings)):
        raise ExportError("nonempty explicit segment mappings within export segment budget required")
    if (len({m.segment_index for m in mappings}) != len(mappings)
            or len({m.recording_id for m in mappings}) != len(mappings)):
        raise ExportError("duplicate segment selection or recording destination identity")
    if not isinstance(epoch, EpochDeclaration):
        raise ExportError("explicit UTC epoch declaration required")
    directory = _real_directory(session_directory)
    output = _new_output(output_directory)
    if directory == output or directory in output.parents:
        raise ExportError("export must be outside the immutable source workspace")
    original_header = read_bounded(directory / HEADER)
    original_final = read_bounded(directory / FINAL)  # Unfinalized sessions fail before output creation.
    session = Session(directory)
    recovered = session.recover()  # The real receipt, media and final-state validator.
    final = recovered["manifest"]
    if not recovered["finalized"] or final["state"] != "finalized":
        raise ExportError("normal finalized state required; source_failed/capacity_halted/recovered_incomplete exports are refused")
    header = load_json(directory / HEADER)
    if (read_bounded(directory / HEADER) != original_header or read_bounded(directory / FINAL) != original_final
            or canonical(load_json(directory / FINAL)) != canonical(final)):
        raise ExportError("source header/final changed during validation")
    source_object = session.source(source_id)
    source = next(item for item in header["sources"] if item["source_id"] == source_id)
    if canonical(source) != canonical(asdict(source_object)):
        raise ExportError("source metadata fields missing or inconsistent; defaults cannot replace original declarations")
    if source["media"] != "pcm16-wav":
        raise ExportError("only PCM16 WAV segments can be exported; no media conversion")
    if not 1 <= len(source["channels"]) <= 8 or not 1 <= source["sample_rate_hz"] <= 384000:
        raise ExportError("v1 limit is 8 channels / 384000 Hz; no mixing or downsampling")
    clock = source["clock"]
    if (epoch.source_id != source_id or epoch.reference_domain != clock["reference_domain"]
            or epoch.reference_epoch != clock["reference_epoch"]):
        raise ExportError("epoch declaration does not match source/reference domain/reference epoch")
    provenance, provenance_binding = _provenance(source, file_origin)
    files: dict[str, bytes] = {}
    bytes_used = 0

    def add(name: str, data: bytes) -> dict:
        nonlocal bytes_used
        if name in files:
            raise ExportError("duplicate output path")
        bytes_used += len(data)
        if bytes_used > max_bytes:
            raise ExportError("export byte budget exceeded before output creation")
        files[name] = data
        return {"path": name, "sha256": sha256(data), "bytes": len(data)}

    header_ref = add("source-header.json", original_header)
    final_ref = add("source-final.json", original_final)
    exports = []
    for mapping in sorted(mappings, key=lambda item: item.segment_index):
        index = mapping.segment_index
        if index >= len(recovered["receipts"]):
            raise ExportError("selected segment is not committed in finalized session")
        receipt = recovered["receipts"][index]
        if receipt["source_id"] != source_id:
            raise ExportError("selected segment belongs to a different source")
        segment = final["segments"][index]
        receipt_bytes = read_bounded(directory / segment["receipt"], 16384)
        if sha256(receipt_bytes) != segment["receipt_sha256"] or receipt_bytes != canonical(receipt):
            raise ExportError("source receipt changed during export")
        if bytes_used + receipt["bytes"] > max_bytes:
            raise ExportError("export byte budget exceeded before output creation")
        wav = read_bounded(directory / receipt["path"], MAX_CHUNK_BYTES)
        if sha256(wav) != receipt["sha256"] or len(wav) != receipt["bytes"]:
            raise ExportError("source segment changed during export")
        wav_ref = add(receipt["path"], wav)
        receipt_ref = add(f"source-receipt-{index:06d}.json", receipt_bytes)
        timing = _time_binding(epoch, receipt, source)
        manifest = RecordingManifest.from_dict({
            "schema_version": 1, "recording_id": mapping.recording_id,
            "site_id": mapping.site_id, "zone_id": mapping.zone_id, "device_id": mapping.device_id,
            "started_at": timing["started_at"], "provenance": provenance,
            "wav_sha256": receipt["sha256"], "calibration_status": "uncalibrated",
        })
        manifest_bytes = (manifest.to_json() + "\n").encode()
        manifest_name = f"recording-{index:06d}.v1.json"
        manifest_ref = {"path": manifest_name, "sha256": sha256(manifest_bytes), "bytes": len(manifest_bytes)}
        binding = _binding_document(final=final, source=source, receipt=receipt, mapping=mapping,
                                    header_ref=header_ref, final_ref=final_ref, receipt_ref=receipt_ref,
                                    wav_ref=wav_ref, manifest_ref=manifest_ref, timing=timing,
                                    provenance_binding=provenance_binding)
        binding_ref = add(f"binding-{index:06d}.json", canonical(binding))
        add(manifest_name, manifest_bytes)  # Each standalone manifest follows its WAV and companion.
        exports.append({"segment_index": index, "recording_id": mapping.recording_id,
                        "wav": wav_ref, "manifest": manifest_ref, "binding": binding_ref})
    commit = _export_document(
        final=final, source_id=source_id, header_ref=header_ref, final_ref=final_ref,
        exports=exports, max_bytes=max_bytes, max_segments=max_segments,
        file_records=[{"path": name, "bytes": len(data), "sha256": sha256(data)}
                      for name, data in sorted(files.items())], bytes_used=bytes_used,
    )
    commit_bytes = canonical(commit)
    if bytes_used + len(commit_bytes) > max_bytes:
        raise ExportError("export byte budget including commit receipt exceeded before output creation")
    output.mkdir(mode=0o700, exist_ok=False)
    _sync_directory(output.parent)
    for name, data in files.items():
        publish(output, name, data)
    # Recheck all original evidence, not just copied segments, before committing.
    if (session.recover() != recovered or read_bounded(directory / HEADER) != original_header
            or read_bounded(directory / FINAL) != original_final):
        raise ExportError("source changed before export commit; partial output is not committed")
    if set(item.name for item in output.iterdir()) != set(files):
        raise ExportError("unexpected output artifacts; export is not committed")
    for name, data in files.items():
        if read_bounded(output / name, max_bytes) != data:
            raise ExportError("output changed before export commit")
    _commit(output, commit_bytes)
    return commit
