"""Additive Hub schema; the acoustic evidence database is never migrated here."""

PLATFORM_COLUMNS = {
    "principals": ("id", "subject", "role", "site_ids_json", "device_id", "token_hash", "created_at", "updated_at", "revoked_at"),
    "devices": ("id", "site_id", "document_json", "created_at", "revoked_at"),
    "aquilon_mappings": ("device_id", "dev_eui", "document_json"),
    "acquisition_sessions": ("id", "site_id", "device_id", "document_json", "created_at", "actor_subject"),
    "recording_sessions": ("recording_id", "session_id", "bound_at", "actor_subject"),
    "independent_observations": ("id", "recording_id", "created_at", "provenance_json"),
    "observation_history": ("observation_id", "revision", "document_json"),
    "telemetry": ("id", "device_id", "site_id", "boot_id", "sequence", "envelope_json", "received_at", "actor_subject"),
    "security_audit": ("id", "action", "actor_subject", "auth_mode", "site_id", "device_id", "resource_id", "created_at", "details_json"),
    "platform_documents": ("id", "document_json"),
}

PLATFORM_SQL = """
CREATE TABLE principals (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'reviewer', 'admin', 'device')),
    site_ids_json TEXT NOT NULL,
    device_id TEXT REFERENCES devices(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX devices_scope ON devices(site_id, id);
CREATE TABLE aquilon_mappings (
    device_id TEXT PRIMARY KEY REFERENCES devices(id),
    dev_eui TEXT NOT NULL UNIQUE,
    document_json TEXT NOT NULL
);
CREATE TABLE acquisition_sessions (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    device_id TEXT REFERENCES devices(id),
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    actor_subject TEXT NOT NULL
);
CREATE INDEX acquisition_scope ON acquisition_sessions(site_id, device_id, id);
CREATE TABLE recording_sessions (
    recording_id TEXT PRIMARY KEY REFERENCES sources(recording_id),
    session_id TEXT NOT NULL REFERENCES acquisition_sessions(id),
    bound_at TEXT NOT NULL,
    actor_subject TEXT NOT NULL
);
CREATE TABLE independent_observations (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES sources(recording_id),
    created_at TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);
CREATE TABLE observation_history (
    observation_id TEXT NOT NULL REFERENCES independent_observations(id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    document_json TEXT NOT NULL,
    PRIMARY KEY (observation_id, revision)
);
CREATE TABLE telemetry (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id),
    site_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    envelope_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    UNIQUE (device_id, boot_id, sequence)
);
CREATE INDEX telemetry_scope ON telemetry(site_id, device_id, received_at, id);
CREATE TABLE security_audit (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    auth_mode TEXT NOT NULL,
    site_id TEXT,
    device_id TEXT,
    resource_id TEXT,
    created_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);
CREATE INDEX audit_scope ON security_audit(site_id, device_id, id);
CREATE TABLE platform_documents (
    id TEXT PRIMARY KEY,
    document_json TEXT NOT NULL
);
"""
