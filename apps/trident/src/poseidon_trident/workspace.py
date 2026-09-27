"""Safe ownership and short-lived storage for a Trident workspace."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
from typing import Iterator

from poseidon_acoustic.errors import StoreError
from poseidon_acoustic.store import _connect_existing as _connect_evidence_existing
from poseidon_acoustic.store import _create_database as _create_evidence_database

from .errors import HubError
from .platform_schema import PLATFORM_COLUMNS, PLATFORM_SQL
from .companion_schema import COMPANION_COLUMNS, COMPANION_SQL
from .control_schema import CONTROL_COLUMNS, CONTROL_SQL
from .companion_storage import reconcile_import_intents
from .companion_integrity import validate_companion_catalog


HUB_APPLICATION_ID = 0x54524944  # "TRID"
HUB_SCHEMA_VERSION = 4
TOKEN_NAME = "access.token"
HUB_DATABASE_NAME = "hub.sqlite3"
EVIDENCE_DATABASE_NAME = "evidence.sqlite3"
LOCK_NAME = ".hub.lock"
RECORDINGS_DIR_NAME = "recordings"
VIDEOS_DIR_NAME = "videos"
STAGING_DIR_NAME = ".staging"

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


_EXPECTED_COLUMNS = {
    "metadata": ("key", "value"),
    "jobs": (
        "id",
        "recording_id",
        "status",
        "created_at",
        "updated_at",
        "error",
        "run_id",
        "event_count",
    ),
    "sources": (
        "recording_id",
        "job_id",
        "manifest_fingerprint",
        "manifest_json",
        "wav_sha256",
        "duration_s",
        "sample_rate_hz",
        "channel_count",
        "frame_count",
        "byte_count",
        "imported_at",
        "state",
        "completed_at",
    ),
    "event_index": (
        "event_id",
        "recording_id",
        "run_id",
        "start_frame",
    ),
    "review_history": (
        "event_id",
        "revision",
        "label",
        "notes",
        "reviewer",
        "updated_at",
    ),
    "videos": (
        "recording_id",
        "filename",
        "sha256",
        "byte_count",
        "offset_s",
        "uploaded_at",
    ),
}

_SCHEMA_SQL = f"""
PRAGMA application_id = {HUB_APPLICATION_ID};
PRAGMA user_version = {HUB_SCHEMA_VERSION};
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error TEXT,
    run_id TEXT,
    event_count INTEGER CHECK (event_count IS NULL OR event_count >= 0)
);
CREATE TABLE sources (
    recording_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
    manifest_fingerprint TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    wav_sha256 TEXT NOT NULL,
    duration_s REAL NOT NULL CHECK (duration_s >= 0),
    sample_rate_hz INTEGER NOT NULL CHECK (sample_rate_hz >= 1),
    channel_count INTEGER NOT NULL CHECK (channel_count BETWEEN 1 AND 8),
    frame_count INTEGER NOT NULL CHECK (frame_count >= 0),
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    imported_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'available', 'failed')),
    completed_at TEXT
);
CREATE TABLE event_index (
    event_id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES sources(recording_id),
    run_id TEXT NOT NULL,
    start_frame INTEGER NOT NULL CHECK (start_frame >= 0)
);
CREATE INDEX event_index_order
    ON event_index(recording_id, start_frame, event_id);
CREATE TABLE review_history (
    event_id TEXT NOT NULL REFERENCES event_index(event_id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    label TEXT NOT NULL CHECK (label IN ('confirmed_feeding', 'non_feeding', 'uncertain')),
    notes TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (event_id, revision)
);
CREATE INDEX review_history_latest
    ON review_history(event_id, revision DESC);
CREATE TABLE videos (
    recording_id TEXT PRIMARY KEY REFERENCES sources(recording_id),
    filename TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    offset_s REAL NOT NULL,
    uploaded_at TEXT NOT NULL
);
"""


class Workspace:
    """Own the fixed workspace paths and provide validated SQLite connections."""

    def __init__(self, data_dir: Path | str) -> None:
        if not isinstance(data_dir, (str, Path)):
            raise HubError("invalid_data_dir", "data directory must be a path", 400)
        self.root = Path(os.path.abspath(os.fspath(data_dir)))
        self.hub_database = self.root / HUB_DATABASE_NAME
        self.evidence_database = self.root / EVIDENCE_DATABASE_NAME
        self.token_path = self.root / TOKEN_NAME
        self.recordings_dir = self.root / RECORDINGS_DIR_NAME
        self.videos_dir = self.root / VIDEOS_DIR_NAME
        self.staging_dir = self.root / STAGING_DIR_NAME
        self.lock_path = self.root / LOCK_NAME
        self._lock_fd: int | None = None
        self._closed = False
        self._closing = False
        self._active_operations = 0
        self._state_lock = threading.RLock()
        self._state_changed = threading.Condition(self._state_lock)
        self._prepare_root()
        try:
            self._acquire_lock()
            self._open_or_initialize()
            reconcile_import_intents(self)
            validate_companion_catalog(self)
            self._recover_running_jobs()
            self._validate_catalog_files()
        except Exception:
            self.close()
            raise

    def _prepare_root(self) -> None:
        try:
            info = self.root.lstat()
        except FileNotFoundError:
            parent = self.root.parent
            try:
                parent_info = parent.stat()
            except (OSError, ValueError) as exc:
                raise HubError(
                    "invalid_data_dir", "data directory parent is unavailable", 400
                ) from exc
            if not stat.S_ISDIR(parent_info.st_mode) or parent.is_symlink():
                raise HubError(
                    "invalid_data_dir", "data directory parent must be a real directory", 400
                )
            try:
                self.root.mkdir(mode=0o700)
            except OSError as exc:
                raise HubError(
                    "workspace_unavailable", "cannot create the data directory", 500
                ) from exc
            return
        except (OSError, ValueError) as exc:
            raise HubError("workspace_unavailable", "cannot inspect the data directory", 500) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise HubError(
                "invalid_data_dir", "data directory must be a real directory", 400
            )

    def _acquire_lock(self) -> None:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                os.close(descriptor)
                raise HubError(
                    "unsafe_workspace", "workspace lock is not a regular file", 409
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            try:
                os.close(descriptor)
            except (OSError, UnboundLocalError):
                pass
            raise HubError(
                "workspace_locked", "workspace is already open by another process", 409
            ) from exc
        except HubError:
            raise
        except OSError as exc:
            raise HubError("workspace_unavailable", "cannot lock the workspace", 500) from exc
        self._lock_fd = descriptor

    def _open_or_initialize(self) -> None:
        allowed = {
            LOCK_NAME,
            TOKEN_NAME,
            HUB_DATABASE_NAME,
            EVIDENCE_DATABASE_NAME,
            RECORDINGS_DIR_NAME,
            VIDEOS_DIR_NAME,
            STAGING_DIR_NAME,
            f"{HUB_DATABASE_NAME}-journal",
            f"{EVIDENCE_DATABASE_NAME}-journal",
        }
        try:
            names = {entry.name for entry in self.root.iterdir()}
        except OSError as exc:
            raise HubError("workspace_unavailable", "cannot inspect workspace contents", 500) from exc
        unknown = names - allowed
        if unknown:
            raise HubError(
                "incompatible_workspace", "workspace contains unexpected files", 409
            )
        for database_name in (HUB_DATABASE_NAME, EVIDENCE_DATABASE_NAME):
            journal = self.root / f"{database_name}-journal"
            if journal.exists() or journal.is_symlink():
                self._require_regular(journal, "database recovery journal")

        if not self.hub_database.exists() and not self.hub_database.is_symlink():
            if names - {LOCK_NAME}:
                raise HubError(
                    "incompatible_workspace", "workspace is incomplete or unrelated", 409
                )
            self._initialize_new()
            return

        self._require_directory(self.recordings_dir, "recordings directory")
        self._require_directory(self.videos_dir, "videos directory")
        self._require_directory(self.staging_dir, "staging directory")
        self._require_regular(self.hub_database, "hub database")
        self._require_regular(self.evidence_database, "evidence database")
        self._require_regular(self.token_path, "access token")
        self._validate_evidence_database()
        self._read_token()
        connection = self._connect_hub_raw(read_only=False)
        try:
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            except sqlite3.Error as exc:
                raise HubError("incompatible_workspace", "cannot read corrupt Hub database; no repair attempted", 409) from exc
            if version in (1, 2, 3):
                self._validate_hub_schema(connection, expected_version=version)
                # One transaction covers all required additive schema steps.
                additions = (PLATFORM_SQL if version == 1 else "") + (COMPANION_SQL if version < 3 else "") + CONTROL_SQL
                try:
                    connection.executescript(
                        "BEGIN IMMEDIATE;\n" + additions
                        + f"\nPRAGMA user_version = {HUB_SCHEMA_VERSION};\n"
                        + f"UPDATE metadata SET value = '{HUB_SCHEMA_VERSION}' "
                        "WHERE key = 'workspace_schema';\n"
                    )
                    self._validate_hub_schema(connection)
                    connection.commit()
                except (sqlite3.Error, HubError) as exc:
                    connection.rollback()
                    raise HubError("migration_failed", "cannot migrate the Hub database", 409) from exc
            self._validate_hub_schema(connection)
        finally:
            connection.close()

    def _initialize_new(self) -> None:
        for path, label in (
            (self.recordings_dir, "recordings directory"),
            (self.videos_dir, "videos directory"),
            (self.staging_dir, "staging directory"),
        ):
            try:
                path.mkdir(mode=0o700)
            except OSError as exc:
                raise HubError("workspace_unavailable", f"cannot create {label}", 500) from exc
        self._create_hub_database()
        try:
            evidence = _create_evidence_database(self.evidence_database)
        except StoreError as exc:
            raise HubError(
                "incompatible_evidence_store", "cannot initialize the evidence database", 409
            ) from exc
        else:
            evidence.close()
        self._create_token()

    @staticmethod
    def _require_directory(path: Path, label: str) -> None:
        try:
            info = path.lstat()
        except OSError as exc:
            raise HubError("incompatible_workspace", f"{label} is missing", 409) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise HubError(
                "incompatible_workspace", f"{label} must be a real directory", 409
            )

    @staticmethod
    def _require_regular(path: Path, label: str) -> None:
        try:
            info = path.lstat()
        except OSError as exc:
            raise HubError("incompatible_workspace", f"{label} is missing", 409) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise HubError(
                "incompatible_workspace", f"{label} must be a regular file", 409
            )

    def _create_hub_database(self) -> None:
        try:
            descriptor = os.open(
                self.hub_database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            os.close(descriptor)
        except OSError as exc:
            raise HubError("workspace_unavailable", "cannot create the hub database", 500) from exc
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect_hub_raw(read_only=False)
            connection.executescript(_SCHEMA_SQL + PLATFORM_SQL + COMPANION_SQL + CONTROL_SQL)
            connection.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("workspace_schema", str(HUB_SCHEMA_VERSION)),
            )
            connection.commit()
            self._validate_hub_schema(connection)
        except (sqlite3.Error, HubError) as exc:
            if connection is not None:
                connection.close()
            try:
                self.hub_database.unlink()
            except OSError:
                pass
            if isinstance(exc, HubError):
                raise
            raise HubError("workspace_unavailable", "cannot initialize the hub database", 500) from exc
        else:
            connection.close()

    def _connect_hub_raw(self, *, read_only: bool) -> sqlite3.Connection:
        try:
            uri = self.hub_database.resolve().as_uri()
            mode = "ro" if read_only else "rw"
            connection = sqlite3.connect(
                f"{uri}?mode={mode}", uri=True, timeout=5.0, isolation_level=None
            )
        except (OSError, sqlite3.Error) as exc:
            raise HubError("workspace_unavailable", "cannot open the hub database", 500) from exc
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            if read_only:
                connection.execute("PRAGMA query_only = ON")
        except sqlite3.Error as exc:
            connection.close()
            raise HubError(
                "workspace_unavailable", "cannot configure the hub database", 500
            ) from exc
        return connection

    def _validate_hub_schema(
        self, connection: sqlite3.Connection, *, expected_version: int = HUB_SCHEMA_VERSION
    ) -> None:
        expected_columns = dict(_EXPECTED_COLUMNS)
        if expected_version >= 2:
            expected_columns.update(PLATFORM_COLUMNS)
        if expected_version >= 3:
            expected_columns.update(COMPANION_COLUMNS)
        if expected_version >= 4:
            expected_columns.update(CONTROL_COLUMNS)
        try:
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            names = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            )
        except sqlite3.Error as exc:
            raise HubError(
                "incompatible_workspace", "cannot inspect the hub database", 409
            ) from exc
        if application_id != HUB_APPLICATION_ID or version != expected_version:
            raise HubError(
                "incompatible_workspace", "hub database schema is not supported", 409
            )
        if names != tuple(sorted(expected_columns)):
            raise HubError(
                "incompatible_workspace", "hub database has unexpected tables", 409
            )
        for table, expected in expected_columns.items():
            try:
                actual = tuple(
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                )
            except sqlite3.Error as exc:
                raise HubError(
                    "incompatible_workspace", "cannot inspect the hub database", 409
                ) from exc
            if actual != expected:
                raise HubError(
                    "incompatible_workspace", "hub database has unexpected columns", 409
                )
        try:
            metadata = tuple(
                tuple(row)
                for row in connection.execute(
                    "SELECT key, value FROM metadata ORDER BY key"
                ).fetchall()
            )
        except sqlite3.Error as exc:
            raise HubError(
                "incompatible_workspace", "cannot inspect hub metadata", 409
            ) from exc
        if metadata != (("workspace_schema", str(expected_version)),):
            raise HubError(
                "incompatible_workspace", "hub metadata is not supported", 409
            )

    def _validate_evidence_database(self) -> None:
        try:
            connection = _connect_evidence_existing(
                self.evidence_database, read_only=False
            )
        except StoreError as exc:
            raise HubError(
                "incompatible_evidence_store",
                "evidence database schema is not supported",
                409,
            ) from exc
        else:
            connection.close()

    def _create_token(self) -> None:
        token = secrets.token_urlsafe(32)
        if not _TOKEN_RE.fullmatch(token):
            raise HubError("workspace_unavailable", "cannot generate an access token", 500)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.token_path, flags, 0o600)
            try:
                payload = (token + "\n").encode("ascii")
                written = 0
                while written < len(payload):
                    count = os.write(descriptor, payload[written:])
                    if count <= 0:
                        raise OSError("short token write")
                    written += count
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise HubError("workspace_unavailable", "cannot create the access token", 500) from exc

    def _read_token(self) -> str:
        self._require_regular(self.token_path, "access token")
        try:
            info = self.token_path.stat()
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise HubError(
                    "unsafe_workspace", "access token permissions are too broad", 409
                )
            raw = self.token_path.read_bytes()
            token = raw.decode("ascii").rstrip("\n")
        except HubError:
            raise
        except (OSError, UnicodeError) as exc:
            raise HubError("workspace_unavailable", "cannot read the access token", 500) from exc
        if raw not in {(token + "\n").encode("ascii"), token.encode("ascii")} or not _TOKEN_RE.fullmatch(token):
            raise HubError("incompatible_workspace", "access token file is invalid", 409)
        return token

    def _recover_running_jobs(self) -> None:
        with self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE jobs SET status = 'queued', updated_at = ?, error = NULL "
                    "WHERE status = 'running'",
                    (_utc_now(),),
                )
                connection.commit()
            except sqlite3.Error as exc:
                connection.rollback()
                raise HubError(
                    "workspace_unavailable", "cannot recover interrupted jobs", 500
                ) from exc

    def _validate_catalog_files(self) -> None:
        with self.connect(read_only=True) as connection:
            try:
                recording_ids = {
                    row[0] for row in connection.execute("SELECT recording_id FROM sources")
                }
                video_names = {
                    row[0] for row in connection.execute("SELECT filename FROM videos v WHERE NOT EXISTS (SELECT 1 FROM retention_tombstones t WHERE t.resource_id=v.recording_id AND t.data_class='media')")
                }
                from .retention import tombstone, validate_expired_import
                media_tombstones = {}
                for recording_id in recording_ids:
                    validate_expired_import(self, connection, recording_id)
                    value = tombstone(connection, recording_id, "media")
                    if value:
                        media_tombstones[recording_id] = value
            except sqlite3.Error as exc:
                raise HubError(
                    "incompatible_workspace", "cannot inspect workspace catalog", 409
                ) from exc
        try:
            actual_recordings = {entry.name for entry in self.recordings_dir.iterdir()}
            actual_videos = {entry.name for entry in self.videos_dir.iterdir()}
            staging_entries = list(self.staging_dir.iterdir())
        except OSError as exc:
            raise HubError(
                "incompatible_workspace", "cannot inspect stored media", 409
            ) from exc
        if staging_entries:
            raise HubError(
                "incompatible_workspace", "workspace contains unfinished staging files", 409
            )
        if actual_recordings != recording_ids or actual_videos != video_names:
            raise HubError(
                "incompatible_workspace", "stored media does not match the workspace catalog", 409
            )
        for recording_id in recording_ids:
            if not _IDENTIFIER_RE.fullmatch(recording_id):
                raise HubError(
                    "incompatible_workspace", "workspace catalog contains an unsafe identifier", 409
                )
            directory = self.recordings_dir / recording_id
            self._require_directory(directory, "recording directory")
            try:
                names = {entry.name for entry in directory.iterdir()}
            except OSError as exc:
                raise HubError(
                    "incompatible_workspace", "cannot inspect a recording directory", 409
                ) from exc
            expected_names = {"manifest.json"} if recording_id in media_tombstones else {"source.wav", "manifest.json"}
            if names != expected_names:
                raise HubError(
                    "incompatible_workspace", "recording directory has unexpected files", 409
                )
            if recording_id not in media_tombstones:
                self._require_regular(directory / "source.wav", "recording WAV")
            self._require_regular(directory / "manifest.json", "recording manifest")
            if recording_id in media_tombstones:
                import hashlib
                if hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest() != media_tombstones[recording_id]["manifest_sha256"]:
                    raise HubError("retention_integrity", "retained manifest differs from deletion tombstone", 409)
        for filename in video_names:
            if not filename.endswith(".mp4") or not _IDENTIFIER_RE.fullmatch(filename[:-4]):
                raise HubError(
                    "incompatible_workspace", "workspace catalog contains an unsafe video name", 409
                )
            self._require_regular(self.videos_dir / filename, "stored video")

    @contextmanager
    def operation(self) -> Iterator[None]:
        with self._state_changed:
            if self._closed or self._closing:
                raise HubError("hub_closed", "hub is closed", 409)
            self._active_operations += 1
        try:
            yield
        finally:
            with self._state_changed:
                self._active_operations -= 1
                if self._active_operations == 0:
                    self._state_changed.notify_all()

    @contextmanager
    def connect(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        self.check_open()
        self._require_regular(self.hub_database, "hub database")
        connection = self._connect_hub_raw(read_only=read_only)
        try:
            self._validate_hub_schema(connection)
            yield connection
        finally:
            connection.close()

    @contextmanager
    def evidence_connection(self, *, read_only: bool = True) -> Iterator[sqlite3.Connection]:
        self.check_open()
        try:
            connection = _connect_evidence_existing(
                self.evidence_database, read_only=read_only
            )
        except StoreError as exc:
            raise HubError(
                "evidence_store_error", "evidence database is unavailable", 500
            ) from exc
        try:
            yield connection
        finally:
            connection.close()

    def check_open(self) -> None:
        with self._state_lock:
            if self._closed:
                raise HubError("hub_closed", "hub is closed", 409)

    def access_token(self) -> str:
        self.check_open()
        return self._read_token()

    def close(self) -> None:
        with self._state_changed:
            if self._closed:
                return
            if self._closing:
                while not self._closed:
                    self._state_changed.wait()
                return
            self._closing = True
            while self._active_operations:
                self._state_changed.wait()
            close_error = None
            try:
                callback = getattr(self, "before_close", None)
                if callback is not None:
                    callback()
            except Exception as exc:
                close_error = exc
            self._closed = True
            descriptor = self._lock_fd
            self._lock_fd = None
            self._state_changed.notify_all()
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(descriptor)
            except OSError:
                pass
        if close_error is not None:
            raise close_error
