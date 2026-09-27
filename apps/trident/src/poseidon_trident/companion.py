"""Single-export intake; acquisition's pure reader owns scientific validation."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import io
import json
import os
import secrets

from poseidon_proto import ModelValidationError
from poseidon_proto.companion import (
    COMPANION_SCHEMA_VERSION, DOCUMENT_ROLES, UPLOAD_ROLES, PART_LIMITS,
    MAX_COMPANION_BYTES, MAX_QUEUE_SLOTS, MAX_RETAINED_COMPANION_BYTES, validate_filenames,
)

from .companion_schema import companion_logical_bytes, occupied_queue_slots
from .companion_integrity import validate_retained_import
from .companion_storage import (
    abort_import_intent, checked_package, package_spec, capture_import_ownership, intent_evidence,
)
from .errors import HubError
from .media import create_import_package
from .platform import canonical, identifier, now_utc, public


class _Admission:
    def __init__(self, hub):
        self._hub = hub
        self._operation = hub._workspace.operation()
        self._operation.__enter__()
        self._released = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        if not self._released:
            self._released = True
            self._hub._companion_admissions.release()
            self._operation.__exit__(None, None, None)


def _bounded_wav(stream) -> bytes:
    if not callable(getattr(stream, "read", None)):
        raise HubError("invalid_request", "WAV must be a readable binary stream", 400)
    chunks, count = [], 0
    while True:
        try:
            chunk = stream.read(min(1024 * 1024, PART_LIMITS["wav"] + 1 - count))
        except Exception as exc:
            raise HubError("invalid_request", "cannot read the supplied WAV", 400) from exc
        if chunk == b"":
            break
        if type(chunk) is not bytes:
            raise HubError("invalid_request", "WAV stream must return bytes", 400)
        count += len(chunk)
        if count > PART_LIMITS["wav"]:
            raise HubError("request_too_large", "WAV exceeds the companion intake limit", 413)
        chunks.append(chunk)
    if not count:
        raise HubError("invalid_request", "WAV is empty", 400)
    return b"".join(chunks)


def _read_bundle(wav_stream, manifest_bytes, companions, filenames):
    """Mechanical bounds then the real scientific reader, never a local clone."""
    try:
        names = validate_filenames(filenames)
    except ModelValidationError as exc:
        raise HubError("invalid_request", "invalid companion role or export basename", 400) from exc
    if not isinstance(companions, Mapping) or set(companions) != set(DOCUMENT_ROLES):
        raise HubError("invalid_request", "exactly five companion JSON roles are required", 400)
    files = {"manifest": manifest_bytes, **dict(companions)}
    for role, data in files.items():
        if type(data) is not bytes or not data:
            raise HubError("invalid_request", "metadata files must contain bytes", 400)
        if len(data) > PART_LIMITS[role]:
            raise HubError("request_too_large", "metadata file exceeds its intake limit", 413)
    if sum(len(files[role]) for role in DOCUMENT_ROLES) > MAX_COMPANION_BYTES:
        raise HubError("request_too_large", "aggregate companion bytes exceed the intake limit", 413)
    files["wav"] = _bounded_wav(wav_stream)
    # This module is dependency-free. No exporter/session recovery or codec is
    # invoked on uploaded data. The selected WAV stays within its 8MiB cap.
    from poseidon_acoustic.legacy_export_reader import (
        ExportReadError, ExportReadLimits, file_map_resolver, validate_export_bundle,
    )
    resolver = file_map_resolver({names[role]: data for role, data in files.items() if role != "export_receipt"})
    try:
        validated = validate_export_bundle(files["export_receipt"], resolver, limits=ExportReadLimits())
    except (ExportReadError, ModelValidationError, RecursionError) as exc:
        # Scientific errors can contain submitted strings. Keep the HTTP error
        # stable and do not reflect a private document or a filesystem path.
        raise HubError("invalid_export", "export bundle failed acquisition validation", 400) from exc
    for role in UPLOAD_ROLES:
        item = validated.file_for_role(role)
        if (item.name != names[role] or item.data != files[role] or item.size != len(files[role])
                or item.sha256 != hashlib.sha256(files[role]).hexdigest()):
            raise HubError("invalid_export", "validated export does not match delivered role bytes", 400)
    return validated


class CompanionMixin:
    @public
    def companion_admission(self, session_id: str):
        """HTTP holds this context from authorization through upload closure."""
        with self._workspace.connect(read_only=True) as connection:
            self._authorize_companion_context(connection, session_id)
        if not self._companion_admissions.acquire(blocking=False):
            raise HubError("companion_admission_full", "two companion uploads are already admitted", 409)
        try:
            return _Admission(self)
        except BaseException:
            self._companion_admissions.release()
            raise

    def _authorize_companion_context(self, connection, session_id: str, validated=None):
        # At commit this runs under BEGIN IMMEDIATE. Principal refresh and the
        # session/device reads precede writes while competing writers are blocked.
        actor = self._require_role("admin")
        identifier("session_id", session_id)
        row = connection.execute("SELECT * FROM acquisition_sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise HubError("session_not_found", "acquisition session was not found", 404)
        self._require_site(row["site_id"], row["device_id"])
        session = json.loads(row["document_json"])
        device = connection.execute("SELECT * FROM devices WHERE id = ?", (row["device_id"],)).fetchone()
        if device is None or device["revoked_at"] is not None:
            raise HubError("companion_device_inactive", "session requires an active registered device", 409)
        device_body = json.loads(device["document_json"])
        if device["site_id"] != session["site_id"] or device_body["source_kind"] != session["provenance"]["source_kind"]:
            raise HubError("companion_context_mismatch", "session and registry source identity differ", 409)
        if validated is not None:
            manifest = validated.manifest
            if (session["site_id"] != manifest.site_id or session["device_id"] != manifest.device_id
                    or session["provenance"]["source_kind"] != manifest.provenance
                    or session["provenance"]["source_id"] != validated.source_id):
                raise HubError("companion_context_mismatch", "export source does not match the target session", 409)
        return actor, session

    def _check_companion_bindings(self, connection, session_id, validated) -> None:
        pin = connection.execute("SELECT * FROM acquisition_source_bindings WHERE session_id = ?", (session_id,)).fetchone()
        expected = (validated.capture_session_id, validated.source_id, validated.header_sha256, validated.final_sha256)
        if pin is not None and tuple(pin[key] for key in ("capture_session_id", "source_id", "header_sha256", "final_sha256")) != expected:
            raise HubError("companion_snapshot_conflict", "session is pinned to another source snapshot", 409)
        prior = connection.execute(
            "SELECT recording_id, session_id FROM recording_companion_imports WHERE capture_session_id = ? "
            "AND source_id = ? AND header_sha256 = ? AND final_sha256 = ? AND selected_index = ?",
            (*expected, validated.selected_index),
        ).fetchone()
        if prior is not None:
            self._recording_access(prior["recording_id"])
            if prior["recording_id"] != validated.manifest.recording_id or prior["session_id"] != session_id:
                raise HubError("companion_segment_conflict", "source segment is already bound to another recording or context", 409)

    def _companion_duplicate(self, connection, session_id, validated):
        recording_id = validated.manifest.recording_id
        source = connection.execute("SELECT * FROM sources WHERE recording_id = ?", (recording_id,)).fetchone()
        if source is None:
            return None
        self._recording_access(recording_id)
        retained = connection.execute("SELECT * FROM recording_companion_imports WHERE recording_id = ?", (recording_id,)).fetchone()
        if retained is not None:
            validate_retained_import(self._workspace, connection, recording_id)
        manifest_file, wav_file = validated.file_for_role("manifest"), validated.file_for_role("wav")
        if (retained is None or retained["session_id"] != session_id
                or source["manifest_fingerprint"] != validated.manifest.fingerprint()
                or source["manifest_json"] != validated.manifest.to_json()
                or source["wav_sha256"] != wav_file.sha256 or source["byte_count"] != wav_file.size
                or retained["manifest_sha256"] != manifest_file.sha256
                or retained["capture_session_id"] != validated.capture_session_id
                or retained["source_id"] != validated.source_id or retained["selected_index"] != validated.selected_index
                or retained["header_sha256"] != validated.header_sha256 or retained["final_sha256"] != validated.final_sha256
                or bytes(retained["projection_bytes"]) != validated.projection_bytes):
            raise HubError("companion_import_conflict", "recording already has different or absent companion evidence", 409)
        binding = connection.execute("SELECT session_id FROM recording_sessions WHERE recording_id = ?", (recording_id,)).fetchone()
        if binding is None or binding["session_id"] != session_id:
            raise HubError("companion_import_conflict", "recording session binding differs", 409)
        documents = connection.execute("SELECT * FROM recording_companion_documents WHERE recording_id = ?", (recording_id,)).fetchall()
        if {row["role"] for row in documents} != set(DOCUMENT_ROLES):
            raise HubError("companion_import_conflict", "recording companion role set differs", 409)
        for row in documents:
            actual = validated.file_for_role(row["role"])
            if (row["name"] != actual.name or row["sha256"] != actual.sha256
                    or row["byte_count"] != actual.size or bytes(row["body"]) != actual.data):
                raise HubError("companion_import_conflict", "recording companion bytes differ", 409)
        checked_package(self._workspace.recordings_dir / recording_id,
                        package_spec(wav_file.data, manifest_file.data), complete=True)
        return source["job_id"]

    @public
    def submit_recording_with_companions(self, wav_stream, manifest_bytes, companions_by_role,
                                        *, session_id: str, filenames_by_role) -> dict:
        with self._workspace.connect(read_only=True) as connection:
            self._authorize_companion_context(connection, session_id)
        validated = _read_bundle(wav_stream, manifest_bytes, companions_by_role, filenames_by_role)
        recording_id = identifier("recording_id", validated.manifest.recording_id)
        wav_file = validated.file_for_role("wav")
        manifest_file = validated.file_for_role("manifest")
        specification = package_spec(wav_file.data, manifest_file.data)
        reserved = sum(validated.file_for_role(role).size for role in DOCUMENT_ROLES)
        intent_id = None
        with self._submit_lock:
            try:
                with self._workspace.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    self._authorize_companion_context(connection, session_id, validated)
                    self._check_companion_bindings(connection, session_id, validated)
                    duplicate = self._companion_duplicate(connection, session_id, validated)
                    if duplicate is not None:
                        connection.commit()
                        return self.get_job(duplicate)
                    if occupied_queue_slots(connection) >= MAX_QUEUE_SLOTS:
                        raise HubError("companion_queue_full", "queued, running and preparing capacity is full", 409)
                    if companion_logical_bytes(connection) + reserved > MAX_RETAINED_COMPANION_BYTES:
                        raise HubError("companion_capacity_full", "retained and reserved companion capacity is full", 409)
                    target = self._workspace.recordings_dir / recording_id
                    if target.exists() or target.is_symlink():
                        raise HubError("unsafe_workspace", "recording target exists outside the catalog", 409)
                    intent_id = "intent_" + secrets.token_hex(16)
                    staging_name = "companion-" + secrets.token_hex(16)
                    connection.execute("INSERT INTO companion_import_intents VALUES (?, ?, ?, ?, 'receiving', ?, ?, ?, ?, ?, ?)",
                                       (intent_id, recording_id, session_id, staging_name, reserved, canonical(specification),
                                        canonical({"directory": None, "files": {}}), wav_file.data, manifest_file.data, now_utc()))
                    connection.commit()
                self._companion_failpoint("intent_reserved")
                self._workspace._require_directory(self._workspace.staging_dir, "staging directory")

                def checkpoint(event, path, opened_info):
                    capture_import_ownership(self._workspace, intent_id, event, path, opened_info)
                    self._companion_failpoint("directory_owned" if event == "directory" else event + "." + path.name)

                package, manifest, wav_info = create_import_package(
                    self._workspace.staging_dir, io.BytesIO(wav_file.data), manifest_file.data,
                    _owned_package_name=staging_name, _ownership_checkpoint=checkpoint,
                )
                self._companion_failpoint("staged")
                checked_package(package, specification, complete=True)
                with self._workspace.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    self._authorize_companion_context(connection, session_id, validated)
                    intent = connection.execute("SELECT * FROM companion_import_intents WHERE id = ?", (intent_id,)).fetchone()
                    ownership, expected_bytes = intent_evidence(intent)
                    checked_package(package, specification, complete=True, ownership=ownership, expected_bytes=expected_bytes)
                    connection.execute("UPDATE companion_import_intents SET state = 'ready' WHERE id = ?", (intent_id,))
                    connection.commit()
                self._companion_failpoint("ready")
                self._workspace._require_directory(self._workspace.recordings_dir, "recordings directory")
                if target.exists() or target.is_symlink():
                    raise HubError("unsafe_workspace", "recording target appeared before publication", 409)
                os.rename(package, target)
                self._sync_directory(self._workspace.recordings_dir)
                self._companion_failpoint("renamed")
                with self._workspace.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    actor, _session = self._authorize_companion_context(connection, session_id, validated)
                    self._check_companion_bindings(connection, session_id, validated)
                    reservation = connection.execute("SELECT * FROM companion_import_intents WHERE id = ? AND state = 'ready'", (intent_id,)).fetchone()
                    if reservation is None or reservation["reserved_bytes"] != reserved:
                        raise HubError("companion_reservation_conflict", "import reservation changed", 409)
                    if occupied_queue_slots(connection) > MAX_QUEUE_SLOTS or companion_logical_bytes(connection) > MAX_RETAINED_COMPANION_BYTES:
                        raise HubError("companion_capacity_full", "import capacity changed before commit", 409)
                    ownership, expected_bytes = intent_evidence(reservation)
                    checked_package(target, specification, complete=True, ownership=ownership, expected_bytes=expected_bytes)
                    now = now_utc()
                    job_id = "job_" + hashlib.sha256(("trident-import-v1\0" + manifest.fingerprint()).encode("utf-8")).hexdigest()
                    connection.execute(
                        "INSERT INTO jobs (id, recording_id, status, created_at, updated_at, error, run_id, event_count) "
                        "VALUES (?, ?, 'queued', ?, ?, NULL, NULL, NULL)", (job_id, recording_id, now, now),
                    )
                    connection.execute(
                        "INSERT INTO sources (recording_id, job_id, manifest_fingerprint, manifest_json, wav_sha256, duration_s, "
                        "sample_rate_hz, channel_count, frame_count, byte_count, imported_at, state, completed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL)",
                        (recording_id, job_id, manifest.fingerprint(), manifest.to_json(), wav_info.sha256, wav_info.duration_s,
                         wav_info.sample_rate_hz, wav_info.channel_count, wav_info.frame_count, wav_info.byte_count, now),
                    )
                    self._companion_failpoint("source_inserted")
                    connection.execute(
                        "INSERT OR IGNORE INTO acquisition_source_bindings VALUES (?, ?, ?, ?, ?)",
                        (session_id, validated.capture_session_id, validated.source_id, validated.header_sha256, validated.final_sha256),
                    )
                    connection.execute("INSERT INTO recording_sessions VALUES (?, ?, ?, ?)", (recording_id, session_id, now, actor["subject"]))
                    self._companion_failpoint("binding_inserted")
                    connection.execute(
                        "INSERT INTO recording_companion_imports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (recording_id, session_id, validated.capture_session_id, validated.source_id, validated.selected_index,
                         validated.header_sha256, validated.final_sha256, wav_file.sha256, manifest_file.sha256,
                         hashlib.sha256(validated.projection_bytes).hexdigest(), validated.projection_bytes,
                         now, actor["subject"], actor["auth_mode"]),
                    )
                    self._companion_failpoint("projection_inserted")
                    for role in DOCUMENT_ROLES:
                        document = validated.file_for_role(role)
                        connection.execute("INSERT INTO recording_companion_documents VALUES (?, ?, ?, ?, ?, ?)",
                                           (recording_id, role, document.name, document.size, document.sha256, document.data))
                        self._companion_failpoint("document_inserted." + role)
                    self._audit_recording(connection, "recording.import_companions", recording_id,
                                          {"session_id": session_id, "capture_session_id": validated.capture_session_id,
                                           "source_id": validated.source_id, "selected_index": validated.selected_index,
                                           "export_receipt_sha256": validated.export_receipt_sha256})
                    self._companion_failpoint("audit_inserted")
                    connection.execute("DELETE FROM companion_import_intents WHERE id = ?", (intent_id,))
                    self._companion_failpoint("before_commit")
                    connection.commit()
                self._companion_failpoint("after_commit")
                return self.get_job(job_id)
            except Exception as exc:
                if intent_id is not None:
                    abort_import_intent(self._workspace, intent_id)
                if isinstance(exc, HubError):
                    raise
                raise HubError("companion_storage_error", "companion import could not be committed", 500) from exc

    def _companion_failpoint(self, phase: str) -> None:
        """Test-only override point; no request/config enables fault injection."""

    @public
    def get_acquisition_companion(self, recording_id: str) -> dict:
        self._recording_access(recording_id)  # Includes pending/failed but never hidden sources.
        with self._workspace.connect(read_only=True) as connection:
            connection.execute("BEGIN")
            row = connection.execute("SELECT c.*, j.id AS job_id, j.status AS job_status FROM recording_companion_imports c "
                                     "JOIN sources s ON s.recording_id = c.recording_id JOIN jobs j ON j.id = s.job_id "
                                     "WHERE c.recording_id = ?", (recording_id,)).fetchone()
            if row is None:
                return {"schema_version": COMPANION_SCHEMA_VERSION, "state": "absent", "recording_id": recording_id}
            validate_retained_import(self._workspace, connection, recording_id)
            documents = connection.execute("SELECT * FROM recording_companion_documents WHERE recording_id = ?", (recording_id,)).fetchall()
        by_role = {document["role"]: document for document in documents}
        if set(by_role) != set(DOCUMENT_ROLES):
            raise HubError("companion_store_error", "retained companion role set is invalid", 500)
        for document in documents:
            self._check_stored_document(document)
        try:
            binding = json.loads(bytes(by_role["binding"]["body"]))
            validation = json.loads(bytes(row["projection_bytes"]))
        except (ValueError, TypeError, RecursionError) as exc:
            raise HubError("companion_store_error", "retained companion projection is invalid", 500) from exc
        return {
            "schema_version": COMPANION_SCHEMA_VERSION, "state": "retained", "recording_id": recording_id,
            "platform_session_id": row["session_id"], "capture_session_id": row["capture_session_id"],
            "source_id": row["source_id"], "selected_index": row["selected_index"],
            "source_header_sha256": row["header_sha256"], "source_final_sha256": row["final_sha256"],
            "wav_sha256": row["wav_sha256"], "manifest_sha256": row["manifest_sha256"],
            "imported_at": row["imported_at"], "actor_subject": row["actor_subject"], "auth_mode": row["auth_mode"],
            "job": {"id": row["job_id"], "status": row["job_status"]},
            "documents": [{"role": role, "name": by_role[role]["name"], "bytes": by_role[role]["byte_count"], "sha256": by_role[role]["sha256"]} for role in DOCUMENT_ROLES],
            "binding": binding, "validation": validation,
        }

    @staticmethod
    def _check_stored_document(document) -> None:
        data = bytes(document["body"])
        if len(data) != document["byte_count"] or hashlib.sha256(data).hexdigest() != document["sha256"]:
            raise HubError("companion_store_error", "retained companion bytes do not match their digest", 500)

    @public
    def get_companion_document(self, recording_id: str, role: str) -> dict:
        self._recording_access(recording_id)
        if type(role) is not str or role not in DOCUMENT_ROLES:
            raise HubError("invalid_request", "unsupported companion document role", 400)
        with self._workspace.connect(read_only=True) as connection:
            connection.execute("BEGIN")
            retained = connection.execute("SELECT 1 FROM recording_companion_imports WHERE recording_id = ?", (recording_id,)).fetchone()
            if retained is None:
                raise HubError("companion_document_not_found", "companion document was not retained", 404)
            validate_retained_import(self._workspace, connection, recording_id)
            row = connection.execute("SELECT * FROM recording_companion_documents WHERE recording_id = ? AND role = ?", (recording_id, role)).fetchone()
        if row is None:
            raise HubError("companion_store_error", "retained companion document is missing", 500)
        self._check_stored_document(row)
        return {"bytes": bytes(row["body"]), "name": row["name"], "sha256": row["sha256"]}
