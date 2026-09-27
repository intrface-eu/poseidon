"""Additive v4 digital control tables. Native evidence tables stay untouched."""
CONTROL_COLUMNS = {
    "control_documents": ("id", "document_json"),
    "command_keys": ("key_id", "principal_id", "public_key_hex", "site_ids_json", "created_at", "revoked_at"),
    "command_counters": ("device_id", "principal_id", "sequence_seen"),
    "commands": ("command_id", "site_id", "device_id", "principal_id", "sequence", "wire_bytes", "command_json", "ack_json"),
    "hub_transitions": ("id", "from_state", "to_state", "cause_id", "command_id", "reason", "created_at"),
    "alarms": ("id", "source", "site_id", "device_id", "severity", "reason", "opened_at", "cleared_at", "acknowledged_by", "acknowledged_at"),
    "calibrations": ("record_id", "instrument_id", "site_id", "quantity", "supersedes_id", "document_json"),
    "retention_tombstones": ("resource_id", "data_class", "plan_id", "document_json"),
}
CONTROL_SQL = """
CREATE TABLE principals_v4 (
    id TEXT PRIMARY KEY, subject TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('viewer','reviewer','admin','device','operator')),
    site_ids_json TEXT NOT NULL, device_id TEXT REFERENCES devices(id),
    token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revoked_at TEXT
);
INSERT INTO principals_v4 SELECT * FROM principals;
DROP TABLE principals;
ALTER TABLE principals_v4 RENAME TO principals;
CREATE TABLE control_documents (id TEXT PRIMARY KEY, document_json TEXT NOT NULL);
CREATE TABLE command_keys (
    key_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, public_key_hex TEXT NOT NULL,
    site_ids_json TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE command_counters (
    device_id TEXT NOT NULL, principal_id TEXT NOT NULL, sequence_seen TEXT NOT NULL CHECK(typeof(sequence_seen)='text'),
    PRIMARY KEY (device_id, principal_id)
);
CREATE TABLE commands (
    command_id TEXT PRIMARY KEY, site_id TEXT NOT NULL, device_id TEXT NOT NULL,
    principal_id TEXT NOT NULL, sequence TEXT NOT NULL CHECK(typeof(sequence)='text'),
    wire_bytes BLOB NOT NULL, command_json TEXT NOT NULL, ack_json TEXT NOT NULL,
    UNIQUE(device_id,principal_id,sequence)
);
CREATE TABLE hub_transitions (
    id INTEGER PRIMARY KEY, from_state TEXT NOT NULL, to_state TEXT NOT NULL CHECK(to_state IN ('observe','armed','inhibited','fault')),
    cause_id TEXT NOT NULL, command_id TEXT, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE alarms (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, site_id TEXT NOT NULL, device_id TEXT NOT NULL,
    severity TEXT NOT NULL, reason TEXT NOT NULL, opened_at TEXT NOT NULL, cleared_at TEXT,
    acknowledged_by TEXT, acknowledged_at TEXT
);
CREATE TABLE calibrations (
    record_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, site_id TEXT NOT NULL,
    quantity TEXT NOT NULL, supersedes_id TEXT UNIQUE REFERENCES calibrations(record_id), document_json TEXT NOT NULL
);
CREATE TABLE retention_tombstones (
    resource_id TEXT NOT NULL, data_class TEXT NOT NULL, plan_id TEXT NOT NULL, document_json TEXT NOT NULL,
    PRIMARY KEY(resource_id,data_class)
);
"""
for _table in ("hub_transitions", "calibrations", "retention_tombstones", "commands"):
    for _verb in ("UPDATE", "DELETE"):
        CONTROL_SQL += f"CREATE TRIGGER {_table}_no_{_verb.lower()} BEFORE {_verb} ON {_table} BEGIN SELECT RAISE(ABORT,'append-only digital audit'); END;\n"
