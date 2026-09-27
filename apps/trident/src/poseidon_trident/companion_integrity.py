"""Recheck retained bytes against the actual acquisition reader, without repair."""
from __future__ import annotations

import hashlib
import io
import json
import os
import stat

from poseidon_proto.companion import DOCUMENT_ROLES, PART_LIMITS, MAX_COMPANION_BYTES

from .companion_storage import checked_package, package_spec
from .errors import HubError
from .media import inspect_wav
from .platform import identifier


def _corrupt():
    return HubError("companion_store_error", "retained acquisition evidence failed integrity validation", 500)


def _stored_bytes(path, maximum):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
        raise _corrupt()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_nlink) != (info.st_dev, info.st_ino, info.st_size, 1):
            raise _corrupt()
        data = stream.read(maximum + 1)
        if len(data) > maximum or len(data) != info.st_size:
            raise _corrupt()
        return data


def validate_retained_import(workspace, connection, recording_id):
    """Validate one complete retained import and return its frozen reader result.

    Callers authorize the recording first. Historical readers do not require the
    original importing principal or device credential to remain active.
    """
    try:
        identifier("recording_id", recording_id)
        from .retention import expired_guard
        expired_guard(connection, recording_id, "media", "companions")
        row = connection.execute("SELECT * FROM recording_companion_imports WHERE recording_id = ?", (recording_id,)).fetchone()
        if row is None:
            raise _corrupt()
        source = connection.execute("SELECT * FROM sources WHERE recording_id = ?", (recording_id,)).fetchone()
        if source is None or connection.execute("SELECT 1 FROM jobs WHERE id = ? AND recording_id = ?", (source["job_id"], recording_id)).fetchone() is None:
            raise _corrupt()
        documents = connection.execute("SELECT * FROM recording_companion_documents WHERE recording_id = ?", (recording_id,)).fetchall()
        if {item["role"] for item in documents} != set(DOCUMENT_ROLES) or len(documents) != len(DOCUMENT_ROLES):
            raise _corrupt()
        data, names, total = {}, {}, 0
        for item in documents:
            role = item["role"]
            raw = bytes(item["body"])
            if (not raw or len(raw) > PART_LIMITS[role] or len(raw) != item["byte_count"]
                    or hashlib.sha256(raw).hexdigest() != item["sha256"]):
                raise _corrupt()
            data[role], names[role] = raw, item["name"]
            total += len(raw)
        if total > MAX_COMPANION_BYTES:
            raise _corrupt()
        projection = bytes(row["projection_bytes"])
        if hashlib.sha256(projection).hexdigest() != row["projection_sha256"]:
            raise _corrupt()
        workspace._require_directory(workspace.recordings_dir, "recordings directory")
        directory = workspace.recordings_dir / recording_id
        workspace._require_directory(directory, "recording directory")
        wav = _stored_bytes(directory / "source.wav", PART_LIMITS["wav"])
        manifest_bytes = _stored_bytes(directory / "manifest.json", PART_LIMITS["manifest"])
        if (hashlib.sha256(wav).hexdigest() != row["wav_sha256"]
                or hashlib.sha256(manifest_bytes).hexdigest() != row["manifest_sha256"]):
            raise _corrupt()
        checked_package(directory, package_spec(wav, manifest_bytes), complete=True)
        # These are the fixed transport basenames, not scientific field inference.
        names["wav"] = f"chunk-{row['selected_index']:06d}.wav"
        names["manifest"] = f"recording-{row['selected_index']:06d}.v1.json"
        from .companion import _read_bundle
        validated = _read_bundle(io.BytesIO(wav), manifest_bytes, data, names)
        expected = (validated.capture_session_id, validated.source_id, validated.header_sha256, validated.final_sha256)
        if (validated.manifest.recording_id != recording_id or validated.selected_index != row["selected_index"]
                or tuple(row[key] for key in ("capture_session_id", "source_id", "header_sha256", "final_sha256")) != expected
                or validated.projection_bytes != projection
                or source["manifest_json"] != validated.manifest.to_json()
                or source["manifest_fingerprint"] != validated.manifest.fingerprint()
                or source["wav_sha256"] != row["wav_sha256"] or source["byte_count"] != len(wav)):
            raise _corrupt()
        info = inspect_wav(directory / "source.wav")
        if any(source[key] != getattr(info, key) for key in ("duration_s", "sample_rate_hz", "channel_count", "frame_count")):
            raise _corrupt()
        binding = connection.execute("SELECT session_id FROM recording_sessions WHERE recording_id = ?", (recording_id,)).fetchone()
        pin = connection.execute("SELECT * FROM acquisition_source_bindings WHERE session_id = ?", (row["session_id"],)).fetchone()
        if (binding is None or binding["session_id"] != row["session_id"] or pin is None
                or tuple(pin[key] for key in ("capture_session_id", "source_id", "header_sha256", "final_sha256")) != expected):
            raise _corrupt()
        context = connection.execute("SELECT * FROM acquisition_sessions WHERE id = ?", (row["session_id"],)).fetchone()
        if context is None:
            raise _corrupt()
        session = json.loads(context["document_json"])
        device = connection.execute("SELECT * FROM devices WHERE id = ?", (context["device_id"],)).fetchone()
        manifest = validated.manifest
        if (device is None or context["site_id"] != manifest.site_id or context["device_id"] != manifest.device_id
                or session["site_id"] != manifest.site_id or session["device_id"] != manifest.device_id
                or session["provenance"]["source_id"] != validated.source_id
                or session["provenance"]["source_kind"] != manifest.provenance
                or device["site_id"] != manifest.site_id or json.loads(device["document_json"])["source_kind"] != manifest.provenance):
            raise _corrupt()
        return validated
    except Exception as exc:
        if isinstance(exc, HubError) and exc.code in {"companion_store_error", "evidence_expired"}:
            raise
        raise _corrupt() from exc


def validate_companion_catalog(workspace) -> None:
    """Reopen/backup/restore check; no source bytes or hashes are normalized."""
    with workspace.connect(read_only=True) as connection:
        if connection.execute(
            "SELECT 1 FROM recording_companion_documents d LEFT JOIN recording_companion_imports i "
            "ON i.recording_id = d.recording_id WHERE i.recording_id IS NULL LIMIT 1"
        ).fetchone():
            raise _corrupt()
        if connection.execute(
            "SELECT 1 FROM acquisition_source_bindings b WHERE NOT EXISTS "
            "(SELECT 1 FROM recording_companion_imports i WHERE i.session_id = b.session_id) LIMIT 1"
        ).fetchone():
            raise _corrupt()
        for row in connection.execute("SELECT recording_id FROM recording_companion_imports ORDER BY recording_id").fetchall():
            from .retention import validate_expired_import
            if not validate_expired_import(workspace, connection, row["recording_id"]):
                validate_retained_import(workspace, connection, row["recording_id"])
