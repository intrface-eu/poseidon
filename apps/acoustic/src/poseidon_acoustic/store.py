"""Local SQLite evidence storage for completed replay runs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Any

from poseidon_proto import (
    AcousticCandidateEvent,
    ModelValidationError,
    RecordingManifest,
    canonical_json,
    parse_json_object,
)

from .detector import DETECTOR_VERSION, DetectionResult, DetectorConfig
from .errors import InputError, StoreError


APPLICATION_ID = 0x5053444E  # "PSDN"
SCHEMA_VERSION = 1
_EXPECTED_COLUMNS = {
    "recordings": (
        "recording_id",
        "manifest_fingerprint",
        "manifest_json",
        "wav_sha256",
        "site_id",
        "zone_id",
        "device_id",
        "started_at",
        "provenance",
        "calibration_status",
    ),
    "runs": (
        "run_id",
        "recording_id",
        "detector_version",
        "detector_config_id",
        "detector_config_json",
        "emission_enabled",
    ),
    "events": (
        "event_id",
        "run_id",
        "recording_id",
        "start_frame",
        "end_frame",
        "event_json",
    ),
}

_SCHEMA_SQL = f"""
PRAGMA application_id = {APPLICATION_ID};
PRAGMA user_version = {SCHEMA_VERSION};
CREATE TABLE recordings (
    recording_id TEXT PRIMARY KEY,
    manifest_fingerprint TEXT NOT NULL UNIQUE,
    manifest_json TEXT NOT NULL,
    wav_sha256 TEXT NOT NULL,
    site_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('synthetic', 'field')),
    calibration_status TEXT NOT NULL CHECK (calibration_status = 'uncalibrated')
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recordings(recording_id),
    detector_version TEXT NOT NULL,
    detector_config_id TEXT NOT NULL,
    detector_config_json TEXT NOT NULL,
    emission_enabled INTEGER NOT NULL CHECK (emission_enabled = 0),
    UNIQUE (recording_id, detector_config_id)
);
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    recording_id TEXT NOT NULL REFERENCES recordings(recording_id),
    start_frame INTEGER NOT NULL CHECK (start_frame >= 0),
    end_frame INTEGER NOT NULL CHECK (end_frame > start_frame),
    event_json TEXT NOT NULL,
    UNIQUE (run_id, event_id)
);
CREATE INDEX events_export_order
    ON events(recording_id, run_id, start_frame, event_id);
"""


@dataclass(frozen=True, slots=True)
class SaveOutcome:
    run_id: str
    event_count: int
    already_present: bool


def _connect_existing(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if path.is_symlink():
        raise StoreError(f"database path must not be a symbolic link: {path}")
    if not path.exists():
        raise StoreError(f"database does not exist: {path}")
    if not path.is_file():
        raise StoreError(f"database path is not a regular file: {path}")
    try:
        if read_only:
            connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(path)
    except sqlite3.Error as exc:
        raise StoreError(f"cannot open database {path}: {exc}") from exc
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _validate_schema(connection, path)
    except Exception:
        connection.close()
        raise
    return connection


def _create_database(path: Path) -> sqlite3.Connection:
    if path.is_symlink():
        raise StoreError(f"database path must not be a symbolic link: {path}")
    parent = path.parent
    if not parent.exists() or not parent.is_dir():
        raise StoreError(f"database parent directory does not exist: {parent}")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    except FileExistsError:
        return _connect_existing(path, read_only=False)
    except OSError as exc:
        raise StoreError(f"cannot create database {path}: {exc}") from exc

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA_SQL)
        _validate_schema(connection, path)
        return connection
    except (sqlite3.Error, StoreError) as exc:
        if connection is not None:
            connection.close()
        try:
            path.unlink()
        except OSError:
            pass
        if isinstance(exc, StoreError):
            raise
        raise StoreError(f"cannot initialize database {path}: {exc}") from exc


def _validate_schema(connection: sqlite3.Connection, path: Path) -> None:
    try:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = ? AND name NOT LIKE ? ORDER BY name",
            ("table", "sqlite_%"),
        ).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"cannot inspect database schema in {path}: {exc}") from exc
    table_names = tuple(row[0] for row in table_rows)
    if application_id != APPLICATION_ID or user_version != SCHEMA_VERSION:
        raise StoreError(
            f"database schema mismatch in {path}: expected Poseidon passive schema v{SCHEMA_VERSION}"
        )
    if table_names != tuple(sorted(_EXPECTED_COLUMNS)):
        raise StoreError(f"database schema mismatch in {path}: unexpected table set")
    for table, expected_columns in _EXPECTED_COLUMNS.items():
        try:
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"cannot inspect table {table} in {path}: {exc}") from exc
        actual_columns = tuple(row[1] for row in rows)
        if actual_columns != expected_columns:
            raise StoreError(f"database schema mismatch in {path}: unexpected {table} columns")


def _recording_values(manifest: RecordingManifest) -> tuple[Any, ...]:
    return (
        manifest.recording_id,
        manifest.fingerprint(),
        manifest.to_json(),
        manifest.wav_sha256,
        manifest.site_id,
        manifest.zone_id,
        manifest.device_id,
        manifest.started_at,
        manifest.provenance,
        manifest.calibration_status,
    )


def _verify_existing_recording(row: sqlite3.Row, manifest: RecordingManifest) -> None:
    expected = _recording_values(manifest)[1:]
    actual = tuple(row[name] for name in _EXPECTED_COLUMNS["recordings"][1:])
    if actual != expected:
        raise StoreError(
            f"recording_id {manifest.recording_id!r} is already bound to conflicting "
            "manifest content or recording context"
        )


def _event_json_in_detection_order(result: DetectionResult) -> tuple[str, ...]:
    return tuple(event.to_json() for event in result.events)


def _validate_result(manifest: RecordingManifest, result: DetectionResult) -> None:
    if type(result.events) is not tuple:
        raise StoreError("result events must be an immutable tuple")
    if type(result.sample_rate_hz) is not int or not 1 <= result.sample_rate_hz <= 384_000:
        raise StoreError("result sample_rate_hz must be an integer from 1 through 384000")
    if type(result.channel_count) is not int or not 1 <= result.channel_count <= 8:
        raise StoreError("result channel_count must be an integer from 1 through 8")
    if (
        type(result.frame_count) is not int
        or result.frame_count < 0
        or result.frame_count > 2**63 - 1
    ):
        raise StoreError("result frame_count must fit a nonnegative SQLite integer")
    if type(result.detector_config_json) is not str:
        raise StoreError("result detector_config_json must be text")
    try:
        parsed_config = parse_json_object(result.detector_config_json)
    except ModelValidationError as exc:
        raise StoreError(f"result detector config is invalid: {exc}") from exc
    if canonical_json(parsed_config) != result.detector_config_json:
        raise StoreError("result detector config JSON must be canonical")
    if set(parsed_config) != {
        "detector_version",
        "threshold_normalized_rms",
        "window_ms",
        "window_frames",
    } or parsed_config.get("detector_version") != DETECTOR_VERSION:
        raise StoreError("result detector config fields do not match this detector version")
    try:
        detector_config = DetectorConfig(
            threshold=parsed_config["threshold_normalized_rms"],
            window_ms=parsed_config["window_ms"],
        )
    except InputError as exc:
        raise StoreError(f"result detector config values are invalid: {exc}") from exc
    window_frames = parsed_config["window_frames"]
    if type(window_frames) is not int or window_frames != detector_config.window_frames(
        result.sample_rate_hz
    ):
        raise StoreError("result detector window frame count is inconsistent")
    expected_config_id = (
        "cfg_" + hashlib.sha256(result.detector_config_json.encode("utf-8")).hexdigest()
    )
    if result.detector_config_id != expected_config_id:
        raise StoreError("result detector config identity does not match its content")
    expected_run_identity = canonical_json(
        {
            "recording_manifest_fingerprint": manifest.fingerprint(),
            "detector_config_id": result.detector_config_id,
        }
    )
    expected_run_id = "run_" + hashlib.sha256(expected_run_identity.encode("utf-8")).hexdigest()
    if result.run_id != expected_run_id:
        raise StoreError("result run identity does not match its manifest and detector config")

    prior_end = -1
    for event in result.events:
        if not isinstance(event, AcousticCandidateEvent):
            raise StoreError("result contains an invalid event object")
        context = (
            event.recording_id,
            event.site_id,
            event.zone_id,
            event.device_id,
            event.provenance,
            event.calibration_status,
        )
        expected_context = (
            manifest.recording_id,
            manifest.site_id,
            manifest.zone_id,
            manifest.device_id,
            manifest.provenance,
            manifest.calibration_status,
        )
        if context != expected_context:
            raise StoreError("result event context does not match its recording manifest")
        if (
            event.run_id != result.run_id
            or event.detector_version != DETECTOR_VERSION
            or event.detector_config_id != result.detector_config_id
            or event.sample_rate_hz != result.sample_rate_hz
            or event.channel_count != result.channel_count
        ):
            raise StoreError("result event metadata does not match its detection run")
        if event.end_frame > result.frame_count or event.start_frame < prior_end:
            raise StoreError("result event frame range is outside or overlaps its recording")
        event_identity = canonical_json(
            {
                "run_id": result.run_id,
                "start_frame": event.start_frame,
                "end_frame": event.end_frame,
            }
        )
        expected_event_id = "evt_" + hashlib.sha256(event_identity.encode("utf-8")).hexdigest()
        if event.event_id != expected_event_id:
            raise StoreError("result event identity does not match its frame range")
        prior_end = event.end_frame


def save_replay(
    database_path: Path | str,
    manifest: RecordingManifest,
    result: DetectionResult,
) -> SaveOutcome:
    """Atomically add one fully validated replay, or verify its prior exact copy."""

    if not isinstance(manifest, RecordingManifest):
        raise StoreError("manifest must be a RecordingManifest")
    if not isinstance(result, DetectionResult):
        raise StoreError("result must be a DetectionResult")
    _validate_result(manifest, result)

    path = Path(database_path)
    connection = _connect_existing(path, read_only=False) if path.exists() else _create_database(path)
    expected_event_json = _event_json_in_detection_order(result)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_schema(connection, path)
        recording_row = connection.execute(
            "SELECT recording_id, manifest_fingerprint, manifest_json, wav_sha256, "
            "site_id, zone_id, device_id, started_at, provenance, calibration_status "
            "FROM recordings WHERE recording_id = ?",
            (manifest.recording_id,),
        ).fetchone()
        if recording_row is None:
            connection.execute(
                "INSERT INTO recordings (recording_id, manifest_fingerprint, manifest_json, "
                "wav_sha256, site_id, zone_id, device_id, started_at, provenance, "
                "calibration_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _recording_values(manifest),
            )
        else:
            _verify_existing_recording(recording_row, manifest)

        run_row = connection.execute(
            "SELECT run_id, recording_id, detector_version, detector_config_id, "
            "detector_config_json, emission_enabled FROM runs WHERE run_id = ?",
            (result.run_id,),
        ).fetchone()
        if run_row is not None:
            expected_run = (
                result.run_id,
                manifest.recording_id,
                DETECTOR_VERSION,
                result.detector_config_id,
                result.detector_config_json,
                0,
            )
            actual_run = tuple(run_row[name] for name in _EXPECTED_COLUMNS["runs"])
            if actual_run != expected_run:
                raise StoreError(f"run_id {result.run_id!r} conflicts with stored evidence")
            stored_events = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT event_json FROM events WHERE run_id = ? "
                    "ORDER BY start_frame, event_id",
                    (result.run_id,),
                ).fetchall()
            )
            if stored_events != expected_event_json:
                raise StoreError(f"run_id {result.run_id!r} has conflicting stored events")
            connection.commit()
            return SaveOutcome(result.run_id, len(result.events), True)

        competing_run = connection.execute(
            "SELECT run_id FROM runs WHERE recording_id = ? AND detector_config_id = ?",
            (manifest.recording_id, result.detector_config_id),
        ).fetchone()
        if competing_run is not None:
            raise StoreError("recording and detector config are bound to a different run identity")

        connection.execute(
            "INSERT INTO runs (run_id, recording_id, detector_version, detector_config_id, "
            "detector_config_json, emission_enabled) VALUES (?, ?, ?, ?, ?, ?)",
            (
                result.run_id,
                manifest.recording_id,
                DETECTOR_VERSION,
                result.detector_config_id,
                result.detector_config_json,
                0,
            ),
        )
        connection.executemany(
            "INSERT INTO events (event_id, run_id, recording_id, start_frame, end_frame, "
            "event_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    event.event_id,
                    event.run_id,
                    event.recording_id,
                    event.start_frame,
                    event.end_frame,
                    event.to_json(),
                )
                for event in result.events
            ),
        )
        connection.commit()
        return SaveOutcome(result.run_id, len(result.events), False)
    except StoreError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise StoreError(f"cannot save replay in {path}: {exc}") from exc
    finally:
        connection.close()


def list_event_json(database_path: Path | str) -> tuple[str, ...]:
    """Read stored event JSON in a deterministic order without creating a database."""

    path = Path(database_path)
    connection = _connect_existing(path, read_only=True)
    try:
        rows = connection.execute(
            "SELECT event_id, run_id, recording_id, start_frame, end_frame, event_json "
            "FROM events ORDER BY recording_id, run_id, start_frame, event_id"
        ).fetchall()
        lines: list[str] = []
        for row in rows:
            try:
                event = AcousticCandidateEvent.from_json(row["event_json"])
            except ModelValidationError as exc:
                raise StoreError(f"stored event {row['event_id']!r} is invalid: {exc}") from exc
            if event.to_json() != row["event_json"] or (
                event.event_id,
                event.run_id,
                event.recording_id,
                event.start_frame,
                event.end_frame,
            ) != (
                row["event_id"],
                row["run_id"],
                row["recording_id"],
                row["start_frame"],
                row["end_frame"],
            ):
                raise StoreError(f"stored event {row['event_id']!r} has conflicting columns")
            lines.append(row["event_json"])
        return tuple(lines)
    except StoreError:
        raise
    except sqlite3.Error as exc:
        raise StoreError(f"cannot list events from {path}: {exc}") from exc
    finally:
        connection.close()
