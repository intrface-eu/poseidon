"""Hub v3 companion retention and owned, abort-only import reservations."""

COMPANION_COLUMNS = {
    "acquisition_source_bindings": ("session_id", "capture_session_id", "source_id", "header_sha256", "final_sha256"),
    "recording_companion_imports": ("recording_id", "session_id", "capture_session_id", "source_id", "selected_index", "header_sha256", "final_sha256", "wav_sha256", "manifest_sha256", "projection_sha256", "projection_bytes", "imported_at", "actor_subject", "auth_mode"),
    "recording_companion_documents": ("recording_id", "role", "name", "byte_count", "sha256", "body"),
    "companion_import_intents": ("id", "recording_id", "session_id", "staging_name", "state", "reserved_bytes", "package_json", "ownership_json", "wav_bytes", "manifest_bytes", "created_at"),
}

COMPANION_SQL = """
CREATE TABLE acquisition_source_bindings (
    session_id TEXT PRIMARY KEY REFERENCES acquisition_sessions(id),
    capture_session_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    header_sha256 TEXT NOT NULL,
    final_sha256 TEXT NOT NULL
);
CREATE TABLE recording_companion_imports (
    recording_id TEXT PRIMARY KEY REFERENCES sources(recording_id),
    session_id TEXT NOT NULL REFERENCES acquisition_sessions(id),
    capture_session_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    selected_index INTEGER NOT NULL CHECK (selected_index >= 0),
    header_sha256 TEXT NOT NULL,
    final_sha256 TEXT NOT NULL,
    wav_sha256 TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    projection_sha256 TEXT NOT NULL,
    projection_bytes BLOB NOT NULL CHECK (typeof(projection_bytes) = 'blob'),
    imported_at TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    auth_mode TEXT NOT NULL,
    UNIQUE (capture_session_id, source_id, header_sha256, final_sha256, selected_index)
);
CREATE TABLE recording_companion_documents (
    recording_id TEXT NOT NULL REFERENCES recording_companion_imports(recording_id),
    role TEXT NOT NULL CHECK (role IN ('binding', 'source_receipt', 'source_header', 'source_final', 'export_receipt')),
    name TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    sha256 TEXT NOT NULL,
    body BLOB NOT NULL CHECK (typeof(body) = 'blob' AND length(body) = byte_count),
    PRIMARY KEY (recording_id, role)
);
CREATE TABLE companion_import_intents (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL REFERENCES acquisition_sessions(id),
    staging_name TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('receiving', 'ready')),
    reserved_bytes INTEGER NOT NULL CHECK (reserved_bytes >= 0 AND reserved_bytes <= 4194304),
    package_json TEXT NOT NULL,
    ownership_json TEXT NOT NULL,
    wav_bytes BLOB NOT NULL CHECK (typeof(wav_bytes) = 'blob' AND length(wav_bytes) BETWEEN 1 AND 8388608),
    manifest_bytes BLOB NOT NULL CHECK (typeof(manifest_bytes) = 'blob' AND length(manifest_bytes) BETWEEN 1 AND 16384),
    created_at TEXT NOT NULL
);
"""


def occupied_queue_slots(connection) -> int:
    """One shared predicate for legacy jobs and new preparing reservations."""
    return connection.execute(
        "SELECT (SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')) "
        "+ (SELECT COUNT(*) FROM companion_import_intents)"
    ).fetchone()[0]


def companion_logical_bytes(connection) -> int:
    return connection.execute(
        "SELECT COALESCE((SELECT SUM(length(body)) FROM recording_companion_documents), 0) "
        "+ COALESCE((SELECT SUM(reserved_bytes) FROM companion_import_intents), 0)"
    ).fetchone()[0]
