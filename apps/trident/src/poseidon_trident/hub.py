"""Public local monitor hub."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
from typing import BinaryIO, Iterable

from poseidon_acoustic import DetectorConfig, replay_to_store
from poseidon_acoustic.errors import AcousticError, InputError, StoreError
from poseidon_proto import AcousticCandidateEvent, ModelValidationError

from .errors import HubError
from .media import (
    WAVEFORM_MAX_POINTS,
    WAVEFORM_MIN_POINTS,
    WavInfo,
    create_import_package,
    demo_inputs,
    remove_owned_package,
    stage_video,
    waveform_envelope,
)
from .workspace import Workspace
from .platform import PlatformMixin, public as _public_method
from .companion import CompanionMixin
from .operating import OperatingMixin
from .control import ControlMixin
from .retention import RetentionMixin, expired_guard
from .companion_schema import occupied_queue_slots
from poseidon_proto.companion import MAX_ADMISSIONS


MAX_ACTIVE_JOBS = 32
MAX_PAGE_SIZE = 200
_REVIEW_LABELS = {"confirmed_feeding", "non_feeding", "uncertain"}
_REVIEW_FILTERS = _REVIEW_LABELS | {"unreviewed"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise HubError(
            "invalid_pagination",
            f"limit must be an integer from 1 through {MAX_PAGE_SIZE}",
            400,
        )
    if type(offset) is not int or not 0 <= offset <= 2**63 - 1:
        raise HubError("invalid_pagination", "offset must be a nonnegative signed 64-bit integer", 400)


def _validate_identifier(name: str, value: str, prefix: str | None = None) -> str:
    if type(value) is not str or not value or len(value) > 128:
        raise HubError("invalid_identifier", f"{name} is not a valid identifier", 400)
    if not value[0].isalnum() or any(
        not (character.isascii() and (character.isalnum() or character in "._-"))
        for character in value
    ):
        raise HubError("invalid_identifier", f"{name} is not a valid identifier", 400)
    if prefix is not None and not value.startswith(prefix):
        raise HubError("invalid_identifier", f"{name} is not a valid identifier", 400)
    return value


def _job_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "recording_id": row["recording_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "error": row["error"],
    }


def _review_json(row: sqlite3.Row | None) -> dict | None:
    if row is None or row["review_revision"] is None:
        return None
    return {
        "label": row["review_label"],
        "notes": row["review_notes"],
        "reviewer": row["review_reviewer"],
        "revision": row["review_revision"],
        "updated_at": row["review_updated_at"],
    }


class Hub(RetentionMixin, ControlMixin, OperatingMixin, CompanionMixin, PlatformMixin):
    """Durable, monitor-only workspace for bounded offline replay evidence."""

    def __init__(self, data_dir: Path | str) -> None:
        self._started = time.monotonic()
        self._workspace = Workspace(data_dir)
        self._submit_lock = threading.Lock()
        self._video_lock = threading.Lock()
        self._companion_admissions = threading.BoundedSemaphore(MAX_ADMISSIONS)
        try:
            self._start_operating()
            self._workspace.before_close = self._close_operating
        except BaseException:
            self._workspace.close()
            raise

    def __enter__(self) -> Hub:
        self._workspace.check_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._workspace.close()

    @_public_method
    def access_token(self) -> str:
        return self._workspace.access_token()

    @_public_method
    def status(self) -> dict:
        scope, parameters = self._recording_scope_sql("visible.recording_id")
        with self._workspace.connect(read_only=True) as connection:
            try:
                row = connection.execute(
                    "SELECT "
                    f"(SELECT COUNT(*) FROM sources visible WHERE state = 'available' AND {scope}) AS recordings, "
                    f"(SELECT COUNT(*) FROM event_index visible WHERE {scope}) AS events, "
                    f"(SELECT COUNT(*) FROM jobs visible WHERE status = 'queued' AND {scope}) AS queued, "
                    f"(SELECT COUNT(*) FROM jobs visible WHERE status = 'running' AND {scope}) AS running, "
                    f"(SELECT COUNT(*) FROM jobs visible WHERE status = 'failed' AND {scope}) AS failed",
                    parameters * 5,
                ).fetchone()
            except sqlite3.Error as exc:
                raise HubError("workspace_unavailable", "cannot read hub status", 500) from exc
        return {
            "mode": "monitor_only",
            "emission_enabled": False,
            "state": "ready",
            "uptime_s": max(0.0, time.monotonic() - self._started),
            "recordings": row["recordings"],
            "events": row["events"],
            "jobs": {
                "queued": row["queued"],
                "running": row["running"],
                "failed": row["failed"],
            },
        }

    @_public_method
    def submit_recording(self, wav_stream: BinaryIO, manifest_bytes: bytes) -> dict:
        with self._submit_lock:
            package, manifest, wav_info = create_import_package(
                self._workspace.staging_dir, wav_stream, manifest_bytes
            )
            published: Path | None = None
            try:
                existing = self._source_identity(manifest.recording_id)
                if existing is not None:
                    if not self._same_source(existing, manifest.fingerprint(), manifest.to_json(), wav_info):
                        raise HubError(
                            "recording_conflict",
                            "recording_id is already bound to different source evidence",
                            409,
                        )
                    return self.get_job(existing["job_id"])

                with self._workspace.connect(read_only=True) as connection:
                    try:
                        active = occupied_queue_slots(connection)
                    except sqlite3.Error as exc:
                        raise HubError(
                            "workspace_unavailable", "cannot inspect the job queue", 500
                        ) from exc
                if active >= MAX_ACTIVE_JOBS:
                    raise HubError(
                        "queue_full",
                        f"job queue already has {MAX_ACTIVE_JOBS} active jobs",
                        429,
                    )

                target = self._workspace.recordings_dir / manifest.recording_id
                if target.exists() or target.is_symlink():
                    raise HubError(
                        "unsafe_workspace",
                        "recording target already exists outside the catalog",
                        409,
                    )
                try:
                    os.rename(package, target)
                    published = target
                    self._sync_directory(self._workspace.recordings_dir)
                except OSError as exc:
                    raise HubError(
                        "workspace_unavailable", "cannot publish recording source evidence", 500
                    ) from exc

                now = _utc_now()
                job_id = "job_" + hashlib.sha256(
                    ("trident-import-v1\0" + manifest.fingerprint()).encode("utf-8")
                ).hexdigest()
                try:
                    with self._workspace.connect() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        active = occupied_queue_slots(connection)
                        if active >= MAX_ACTIVE_JOBS:
                            connection.rollback()
                            raise HubError(
                                "queue_full",
                                f"job queue already has {MAX_ACTIVE_JOBS} active jobs",
                                429,
                            )
                        connection.execute(
                            "INSERT INTO jobs "
                            "(id, recording_id, status, created_at, updated_at, error, run_id, event_count) "
                            "VALUES (?, ?, 'queued', ?, ?, NULL, NULL, NULL)",
                            (job_id, manifest.recording_id, now, now),
                        )
                        connection.execute(
                            "INSERT INTO sources "
                            "(recording_id, job_id, manifest_fingerprint, manifest_json, wav_sha256, "
                            "duration_s, sample_rate_hz, channel_count, frame_count, byte_count, "
                            "imported_at, state, completed_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL)",
                            (
                                manifest.recording_id,
                                job_id,
                                manifest.fingerprint(),
                                manifest.to_json(),
                                manifest.wav_sha256,
                                wav_info.duration_s,
                                wav_info.sample_rate_hz,
                                wav_info.channel_count,
                                wav_info.frame_count,
                                wav_info.byte_count,
                                now,
                            ),
                        )
                        self._audit_recording(connection, "recording.import", manifest.recording_id)
                        connection.commit()
                        published = None
                except HubError:
                    raise
                except sqlite3.Error as exc:
                    raise HubError(
                        "workspace_unavailable", "cannot add the recording job", 500
                    ) from exc
                return self.get_job(job_id)
            finally:
                if published is not None:
                    remove_owned_package(published)
                else:
                    remove_owned_package(package)

    @_public_method
    def submit_demo(self) -> dict:
        wav_stream, manifest_bytes = demo_inputs()
        try:
            return self.submit_recording(wav_stream, manifest_bytes)
        finally:
            wav_stream.close()

    @_public_method
    def process_next_job(self) -> bool:
        claimed = self._claim_job()
        if claimed is None:
            return False
        job_id, recording_id = claimed
        wav_path = self._workspace.recordings_dir / recording_id / "source.wav"
        manifest_path = self._workspace.recordings_dir / recording_id / "manifest.json"
        try:
            self._workspace._require_regular(wav_path, "recording WAV")
            self._workspace._require_regular(manifest_path, "recording manifest")
            result, _outcome = replay_to_store(
                wav_path,
                manifest_path,
                self._workspace.evidence_database,
                DetectorConfig(),
            )
        except Exception as exc:
            message = self._processing_error_message(exc)
            self._fail_job(job_id, recording_id, message)
            return True
        try:
            self._finish_job(job_id, recording_id, result)
        except Exception:
            # A completed evidence transaction is retried idempotently instead of
            # being mislabeled as a failed replay.
            self._requeue_job(job_id)
        return True

    def _claim_job(self) -> tuple[str, str] | None:
        now = _utc_now()
        try:
            with self._workspace.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT id, recording_id FROM jobs WHERE status = 'queued' "
                    "ORDER BY created_at, id LIMIT 1"
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                changed = connection.execute(
                    "UPDATE jobs SET status = 'running', updated_at = ?, error = NULL "
                    "WHERE id = ? AND status = 'queued'",
                    (now, row["id"]),
                ).rowcount
                if changed != 1:
                    connection.rollback()
                    return None
                connection.commit()
                return row["id"], row["recording_id"]
        except HubError:
            raise
        except sqlite3.Error as exc:
            raise HubError("workspace_unavailable", "cannot claim a queued job", 500) from exc

    def _finish_job(self, job_id: str, recording_id: str, result) -> None:
        now = _utc_now()
        try:
            with self._workspace.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT status FROM jobs WHERE id = ? AND recording_id = ?",
                    (job_id, recording_id),
                ).fetchone()
                if row is None or row["status"] != "running":
                    raise HubError(
                        "job_state_conflict", "claimed job is no longer running", 409
                    )
                connection.executemany(
                    "INSERT INTO event_index (event_id, recording_id, run_id, start_frame) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        (event.event_id, recording_id, result.run_id, event.start_frame)
                        for event in result.events
                    ),
                )
                connection.execute(
                    "UPDATE sources SET state = 'available', completed_at = ? "
                    "WHERE recording_id = ? AND state = 'pending'",
                    (now, recording_id),
                )
                changed = connection.execute(
                    "UPDATE jobs SET status = 'succeeded', updated_at = ?, error = NULL, "
                    "run_id = ?, event_count = ? WHERE id = ? AND status = 'running'",
                    (now, result.run_id, len(result.events), job_id),
                ).rowcount
                if changed != 1:
                    raise HubError(
                        "job_state_conflict", "claimed job is no longer running", 409
                    )
                connection.commit()
        except HubError:
            raise
        except sqlite3.Error as exc:
            raise HubError("workspace_unavailable", "cannot store replay job results", 500) from exc

    def _requeue_job(self, job_id: str) -> None:
        now = _utc_now()
        try:
            with self._workspace.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE jobs SET status = 'queued', updated_at = ?, error = NULL "
                    "WHERE id = ? AND status = 'running'",
                    (now, job_id),
                )
                connection.commit()
        except (HubError, sqlite3.Error):
            # Startup recovery reclaims a running job if storage is unavailable now.
            return

    def _fail_job(self, job_id: str, recording_id: str, message: str) -> None:
        now = _utc_now()
        try:
            with self._workspace.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE sources SET state = 'failed', completed_at = ? "
                    "WHERE recording_id = ? AND state = 'pending'",
                    (now, recording_id),
                )
                connection.execute(
                    "UPDATE jobs SET status = 'failed', updated_at = ?, error = ?, "
                    "run_id = NULL, event_count = NULL "
                    "WHERE id = ? AND status = 'running'",
                    (now, message, job_id),
                )
                self._transition(connection, "fault", "unrecoverable-job-failure", reason="job " + job_id + " failed")
                binding = self._binding(connection, authorize=False)
                if binding:
                    self._alarm_condition(connection, source="hub", site_id=binding["site_id"], device_id=binding["device_id"], condition="job." + job_id,
                                          failed=True, severity="critical", reason="unrecoverable job failure")
                connection.commit()
        except (HubError, sqlite3.Error):
            # Leave the durable running claim for startup recovery if failure recording fails.
            return

    @staticmethod
    def _processing_error_message(exc: Exception) -> str:
        if isinstance(exc, InputError):
            return "Stored WAV or manifest failed replay validation; inspect the preserved source evidence."
        if isinstance(exc, StoreError):
            return "Evidence database rejected the replay; inspect workspace storage integrity."
        if isinstance(exc, HubError) and exc.code == "job_state_conflict":
            return "Job state changed during replay; restart the workspace worker."
        if isinstance(exc, AcousticError):
            return "Acoustic replay failed; inspect the preserved source evidence."
        return "Replay processing failed; inspect local workspace health and retry after restart."

    @_public_method
    def get_job(self, job_id: str) -> dict:
        _validate_identifier("job_id", job_id, "job_")
        with self._workspace.connect(read_only=True) as connection:
            try:
                row = connection.execute(
                    "SELECT id, recording_id, status, created_at, updated_at, error "
                    "FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise HubError("workspace_unavailable", "cannot read the job", 500) from exc
        if row is None:
            raise HubError("job_not_found", "job was not found", 404)
        return _job_json(row)

    @_public_method
    def list_jobs(self, limit: int = 20, offset: int = 0) -> dict:
        _validate_page(limit, offset)
        scope, parameters = self._recording_scope_sql("j.recording_id")
        with self._workspace.connect(read_only=True) as connection:
            try:
                total = connection.execute("SELECT COUNT(*) FROM jobs j WHERE " + scope, parameters).fetchone()[0]
                rows = connection.execute(
                    "SELECT id, recording_id, status, created_at, updated_at, error "
                    "FROM jobs j WHERE " + scope + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                    [*parameters, limit, offset],
                ).fetchall()
            except sqlite3.Error as exc:
                raise HubError("workspace_unavailable", "cannot list jobs", 500) from exc
        return {
            "items": [_job_json(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @_public_method
    def list_recordings(self, limit: int = 50, offset: int = 0) -> dict:
        _validate_page(limit, offset)
        scope, parameters = self._recording_scope_sql("s.recording_id")
        scope += " AND NOT EXISTS (SELECT 1 FROM retention_tombstones t WHERE t.resource_id=s.recording_id AND t.data_class='media')"
        with self._workspace.connect(read_only=True) as connection:
            try:
                total = connection.execute(
                    "SELECT COUNT(*) FROM sources s WHERE state = 'available' AND " + scope, parameters
                ).fetchone()[0]
                rows = connection.execute(
                    self._recording_select()
                    + " WHERE s.state = 'available' AND " + scope
                    + " ORDER BY s.imported_at DESC, s.recording_id DESC LIMIT ? OFFSET ?",
                    [*parameters, limit, offset],
                ).fetchall()
            except sqlite3.Error as exc:
                raise HubError("workspace_unavailable", "cannot list recordings", 500) from exc
        return {
            "items": [self._recording_json(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @_public_method
    def get_recording(self, recording_id: str) -> dict:
        _validate_identifier("recording_id", recording_id)
        with self._workspace.connect(read_only=True) as connection:
            expired_guard(connection, recording_id, "media")
            try:
                row = connection.execute(
                    self._recording_select()
                    + " WHERE s.recording_id = ? AND s.state = 'available'",
                    (recording_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise HubError("workspace_unavailable", "cannot read the recording", 500) from exc
        if row is None:
            raise HubError("recording_not_found", "recording was not found", 404)
        return self._recording_json(row)

    @staticmethod
    def _recording_select() -> str:
        return (
            "SELECT s.recording_id, s.manifest_json, s.duration_s, s.sample_rate_hz, "
            "s.channel_count, s.imported_at, "
            "(SELECT COUNT(*) FROM event_index ei WHERE ei.recording_id = s.recording_id) "
            "AS event_count, "
            "(SELECT COUNT(*) FROM event_index ei WHERE ei.recording_id = s.recording_id "
            "AND EXISTS (SELECT 1 FROM review_history rh WHERE rh.event_id = ei.event_id)) "
            "AS reviewed_count, "
            "v.sha256 AS video_sha256, v.offset_s AS video_offset_s, "
            "v.uploaded_at AS video_uploaded_at "
            "FROM sources s LEFT JOIN videos v ON v.recording_id = s.recording_id"
        )

    @staticmethod
    def _recording_json(row: sqlite3.Row) -> dict:
        try:
            result = json.loads(row["manifest_json"])
        except (TypeError, ValueError) as exc:
            raise HubError(
                "workspace_corrupt", "stored recording manifest is invalid", 500
            ) from exc
        result.update(
            {
                "duration_s": row["duration_s"],
                "sample_rate_hz": row["sample_rate_hz"],
                "channel_count": row["channel_count"],
                "event_count": row["event_count"],
                "reviewed_count": row["reviewed_count"],
                "imported_at": row["imported_at"],
                "video": None,
            }
        )
        if row["video_sha256"] is not None:
            result["video"] = {
                "sha256": row["video_sha256"],
                "offset_s": row["video_offset_s"],
                "uploaded_at": row["video_uploaded_at"],
                "alignment": "operator_declared",
            }
        return result

    @_public_method
    def list_events(
        self,
        recording_id: str | None = None,
        review: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        _validate_page(limit, offset)
        if recording_id is not None:
            _validate_identifier("recording_id", recording_id)
        if review is not None and (type(review) is not str or review not in _REVIEW_FILTERS):
            raise HubError("invalid_review_filter", "review filter is not supported", 400)

        scope, scope_parameters = self._recording_scope_sql("s.recording_id")
        conditions = ["s.state = 'available'", scope]
        parameters: list[object] = list(scope_parameters)
        if recording_id is not None:
            conditions.append("ei.recording_id = ?")
            parameters.append(recording_id)
        if review == "unreviewed":
            conditions.append("lr.revision IS NULL")
        elif review is not None:
            conditions.append("lr.label = ?")
            parameters.append(review)
        where = " AND ".join(conditions)
        latest = (
            "WITH latest_reviews AS ("
            "SELECT rh.event_id, rh.revision, rh.label, rh.notes, rh.reviewer, rh.updated_at "
            "FROM review_history rh WHERE rh.revision = "
            "(SELECT MAX(newer.revision) FROM review_history newer "
            "WHERE newer.event_id = rh.event_id)) "
        )
        selection = (
            latest
            + "SELECT ei.event_id, lr.revision AS review_revision, "
            "lr.label AS review_label, lr.notes AS review_notes, "
            "lr.reviewer AS review_reviewer, lr.updated_at AS review_updated_at "
            "FROM event_index ei JOIN sources s ON s.recording_id = ei.recording_id "
            "LEFT JOIN latest_reviews lr ON lr.event_id = ei.event_id "
            f"WHERE {where} "
        )
        try:
            with self._workspace.connect(read_only=True) as connection:
                total = connection.execute(
                    latest
                    + "SELECT COUNT(*) FROM event_index ei "
                    "JOIN sources s ON s.recording_id = ei.recording_id "
                    "LEFT JOIN latest_reviews lr ON lr.event_id = ei.event_id "
                    f"WHERE {where}",
                    parameters,
                ).fetchone()[0]
                rows = connection.execute(
                    selection
                    + "ORDER BY ei.recording_id, ei.start_frame, ei.event_id LIMIT ? OFFSET ?",
                    [*parameters, limit, offset],
                ).fetchall()
        except sqlite3.Error as exc:
            raise HubError("workspace_unavailable", "cannot list events", 500) from exc
        ids = [row["event_id"] for row in rows]
        events = self._fetch_events(ids)
        items: list[dict] = []
        for row in rows:
            event = events.get(row["event_id"])
            if event is None:
                raise HubError(
                    "evidence_store_error", "event index does not match stored evidence", 500
                )
            event["review"] = _review_json(row)
            items.append(event)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @_public_method
    def get_event(self, event_id: str) -> dict:
        _validate_identifier("event_id", event_id, "evt_")
        latest = (
            "SELECT ei.recording_id, rh.revision AS review_revision, "
            "rh.label AS review_label, rh.notes AS review_notes, "
            "rh.reviewer AS review_reviewer, rh.updated_at AS review_updated_at "
            "FROM event_index ei JOIN sources s ON s.recording_id = ei.recording_id "
            "LEFT JOIN review_history rh ON rh.event_id = ei.event_id AND rh.revision = "
            "(SELECT MAX(newer.revision) FROM review_history newer "
            "WHERE newer.event_id = ei.event_id) "
            "WHERE ei.event_id = ? AND s.state = 'available'"
        )
        try:
            with self._workspace.connect(read_only=True) as connection:
                row = connection.execute(latest, (event_id,)).fetchone()
        except sqlite3.Error as exc:
            raise HubError("workspace_unavailable", "cannot read the event", 500) from exc
        if row is None:
            raise HubError("event_not_found", "event was not found", 404)
        event = self._fetch_events([event_id]).get(event_id)
        if event is None:
            raise HubError(
                "evidence_store_error", "event index does not match stored evidence", 500
            )
        event["review"] = _review_json(row)
        return {"event": event, "recording": self.get_recording(row["recording_id"])}

    def _fetch_events(self, event_ids: Iterable[str]) -> dict[str, dict]:
        ids = list(event_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        try:
            with self._workspace.evidence_connection(read_only=True) as connection:
                rows = connection.execute(
                    "SELECT event_id, run_id, recording_id, start_frame, end_frame, event_json "
                    f"FROM events WHERE event_id IN ({placeholders})",
                    ids,
                ).fetchall()
        except sqlite3.Error as exc:
            raise HubError("evidence_store_error", "cannot read stored events", 500) from exc
        result: dict[str, dict] = {}
        for row in rows:
            try:
                event = AcousticCandidateEvent.from_json(row["event_json"])
            except ModelValidationError as exc:
                raise HubError(
                    "evidence_store_error", "stored event evidence is invalid", 500
                ) from exc
            if (
                event.event_id != row["event_id"]
                or event.run_id != row["run_id"]
                or event.recording_id != row["recording_id"]
                or event.start_frame != row["start_frame"]
                or event.end_frame != row["end_frame"]
                or event.to_json() != row["event_json"]
            ):
                raise HubError(
                    "evidence_store_error", "stored event evidence is inconsistent", 500
                )
            result[event.event_id] = event.to_dict()
        return result

    @_public_method
    def save_review(
        self,
        event_id: str,
        label: str,
        notes: str,
        reviewer: str,
        expected_revision: int,
    ) -> dict:
        _validate_identifier("event_id", event_id, "evt_")
        if type(label) is not str or label not in _REVIEW_LABELS:
            raise HubError("invalid_review", "review label is not supported", 400)
        if type(notes) is not str or len(notes) > 2000:
            raise HubError("invalid_review", "review notes must be at most 2000 characters", 400)
        if label == "confirmed_feeding" and not notes.strip():
            raise HubError(
                "invalid_review", "confirmed_feeding reviews require notes", 400
            )
        if type(reviewer) is not str or not reviewer.strip() or len(reviewer) > 80:
            raise HubError(
                "invalid_review", "reviewer must contain 1 through 80 characters", 400
            )
        if type(expected_revision) is not int or expected_revision < 0:
            raise HubError(
                "invalid_review", "expected_revision must be a nonnegative integer", 400
            )
        now = _utc_now()
        try:
            with self._workspace.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                event = connection.execute(
                    "SELECT ei.event_id, ei.recording_id FROM event_index ei "
                    "JOIN sources s ON s.recording_id = ei.recording_id "
                    "WHERE ei.event_id = ? AND s.state = 'available'",
                    (event_id,),
                ).fetchone()
                if event is None:
                    connection.rollback()
                    raise HubError("event_not_found", "event was not found", 404)
                current = connection.execute(
                    "SELECT COALESCE(MAX(revision), 0) FROM review_history WHERE event_id = ?",
                    (event_id,),
                ).fetchone()[0]
                if current != expected_revision:
                    connection.rollback()
                    raise HubError(
                        "review_conflict",
                        "review revision changed; reload the event before saving",
                        409,
                    )
                revision = current + 1
                connection.execute(
                    "INSERT INTO review_history "
                    "(event_id, revision, label, notes, reviewer, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (event_id, revision, label, notes, reviewer, now),
                )
                self._audit_recording(connection, "review.save", event["recording_id"],
                                      {"event_id": event_id, "revision": revision})
                connection.commit()
        except HubError:
            raise
        except sqlite3.Error as exc:
            raise HubError("workspace_unavailable", "cannot save the review", 500) from exc
        return {
            "label": label,
            "notes": notes,
            "reviewer": reviewer,
            "revision": revision,
            "updated_at": now,
        }

    @_public_method
    def waveform(self, recording_id: str, points: int = 512) -> dict:
        _validate_identifier("recording_id", recording_id)
        if type(points) is not int or not WAVEFORM_MIN_POINTS <= points <= WAVEFORM_MAX_POINTS:
            raise HubError(
                "invalid_points",
                f"points must be an integer from {WAVEFORM_MIN_POINTS} through {WAVEFORM_MAX_POINTS}",
                400,
            )
        try:
            with self._workspace.connect(read_only=True) as connection:
                expired_guard(connection, recording_id, "media")
                row = connection.execute(
                    "SELECT wav_sha256, byte_count, duration_s, sample_rate_hz, "
                    "channel_count, frame_count FROM sources "
                    "WHERE recording_id = ? AND state = 'available'",
                    (recording_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise HubError("workspace_unavailable", "cannot read waveform metadata", 500) from exc
        if row is None:
            raise HubError("recording_not_found", "recording was not found", 404)
        path = self._workspace.recordings_dir / recording_id / "source.wav"
        self._workspace._require_regular(path, "recording WAV")
        expected = WavInfo(
            byte_count=row["byte_count"],
            sha256=row["wav_sha256"],
            duration_s=row["duration_s"],
            sample_rate_hz=row["sample_rate_hz"],
            channel_count=row["channel_count"],
            frame_count=row["frame_count"],
        )
        buckets = waveform_envelope(path, points, expected)
        return {
            "recording_id": recording_id,
            "duration_s": row["duration_s"],
            "sample_rate_hz": row["sample_rate_hz"],
            "channel_count": row["channel_count"],
            "amplitude_units": "normalized_pcm16_full_scale",
            "calibration_status": "uncalibrated",
            "buckets": buckets,
        }

    @_public_method
    def attach_video(
        self,
        recording_id: str,
        video_stream: BinaryIO,
        offset_s: float = 0.0,
    ) -> dict:
        _validate_identifier("recording_id", recording_id)
        if type(offset_s) not in (int, float):
            raise HubError("invalid_video_offset", "offset_s must be a finite number", 400)
        try:
            numeric_offset = float(offset_s)
        except OverflowError as exc:
            raise HubError("invalid_video_offset", "offset_s must be a finite number", 400) from exc
        if not math.isfinite(numeric_offset):
            raise HubError("invalid_video_offset", "offset_s must be a finite number", 400)

        with self._video_lock:
            try:
                with self._workspace.connect(read_only=True) as connection:
                    recording = connection.execute(
                        "SELECT recording_id FROM sources "
                        "WHERE recording_id = ? AND state = 'available'",
                        (recording_id,),
                    ).fetchone()
                    existing = connection.execute(
                        "SELECT recording_id FROM videos WHERE recording_id = ?",
                        (recording_id,),
                    ).fetchone()
            except sqlite3.Error as exc:
                raise HubError("workspace_unavailable", "cannot inspect video evidence", 500) from exc
            if recording is None:
                raise HubError("recording_not_found", "recording was not found", 404)
            if existing is not None:
                raise HubError(
                    "video_conflict", "recording already has video evidence", 409
                )

            filename = f"{recording_id}.mp4"
            target = self._workspace.videos_dir / filename
            if target.exists() or target.is_symlink():
                raise HubError(
                    "unsafe_workspace", "video target already exists outside the catalog", 409
                )
            staged, byte_count, digest = stage_video(
                self._workspace.staging_dir, video_stream
            )
            published = False
            try:
                try:
                    os.rename(staged, target)
                    published = True
                    self._sync_directory(self._workspace.videos_dir)
                except OSError as exc:
                    raise HubError(
                        "workspace_unavailable", "cannot publish video evidence", 500
                    ) from exc
                now = _utc_now()
                try:
                    with self._workspace.connect() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        connection.execute(
                            "INSERT INTO videos "
                            "(recording_id, filename, sha256, byte_count, offset_s, uploaded_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                recording_id,
                                filename,
                                digest,
                                byte_count,
                                numeric_offset,
                                now,
                            ),
                        )
                        self._audit_recording(connection, "video.attach", recording_id,
                                              {"sha256": digest, "alignment": "operator_declared"})
                        connection.commit()
                        published = False
                except sqlite3.IntegrityError as exc:
                    raise HubError(
                        "video_conflict", "recording already has video evidence", 409
                    ) from exc
                except sqlite3.Error as exc:
                    raise HubError(
                        "workspace_unavailable", "cannot catalog video evidence", 500
                    ) from exc
                return {
                    "sha256": digest,
                    "offset_s": numeric_offset,
                    "uploaded_at": now,
                    "alignment": "operator_declared",
                }
            finally:
                if published:
                    self._remove_owned_file(target)
                else:
                    self._remove_owned_file(staged)

    @_public_method
    def video_path(self, recording_id: str) -> Path:
        _validate_identifier("recording_id", recording_id)
        try:
            with self._workspace.connect(read_only=True) as connection:
                expired_guard(connection, recording_id, "media")
                row = connection.execute(
                    "SELECT v.filename FROM videos v JOIN sources s "
                    "ON s.recording_id = v.recording_id "
                    "WHERE v.recording_id = ? AND s.state = 'available'",
                    (recording_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise HubError("workspace_unavailable", "cannot read video evidence", 500) from exc
        if row is None:
            raise HubError("video_not_found", "video evidence was not found", 404)
        filename = row["filename"]
        expected = f"{recording_id}.mp4"
        if filename != expected:
            raise HubError("workspace_corrupt", "stored video name is invalid", 500)
        path = self._workspace.videos_dir / filename
        self._workspace._require_regular(path, "stored video")
        return path

    def _source_identity(self, recording_id: str) -> sqlite3.Row | None:
        try:
            with self._workspace.connect(read_only=True) as connection:
                return connection.execute(
                    "SELECT recording_id, job_id, manifest_fingerprint, manifest_json, "
                    "wav_sha256, duration_s, sample_rate_hz, channel_count, frame_count, byte_count "
                    "FROM sources WHERE recording_id = ?",
                    (recording_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise HubError("workspace_unavailable", "cannot inspect recording identity", 500) from exc

    @staticmethod
    def _same_source(
        row: sqlite3.Row,
        manifest_fingerprint: str,
        manifest_json: str,
        info: WavInfo,
    ) -> bool:
        return (
            row["manifest_fingerprint"] == manifest_fingerprint
            and row["manifest_json"] == manifest_json
            and row["wav_sha256"] == info.sha256
            and row["duration_s"] == info.duration_s
            and row["sample_rate_hz"] == info.sample_rate_hz
            and row["channel_count"] == info.channel_count
            and row["frame_count"] == info.frame_count
            and row["byte_count"] == info.byte_count
        )

    @staticmethod
    def _sync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            # The atomic rename remains valid on filesystems that reject directory fsync.
            pass

    @staticmethod
    def _remove_owned_file(path: Path) -> None:
        try:
            info = path.lstat()
        except OSError:
            return
        if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            try:
                path.unlink()
            except OSError:
                pass
