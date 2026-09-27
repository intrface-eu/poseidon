"""Scoped digital commands, public-key enrollment, telemetry health and alarms."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets

from poseidon_proto.command import KINDS, parse_command, parse_command_ack, payload_bytes
from poseidon_proto.calibration import parse_calibration
from poseidon_proto.config_migrations import migrate_config
from poseidon_proto.models import ModelValidationError
from poseidon_proto.platform import canonical_json, parse_utc

from .errors import HubError
from .operating import document, put_document
from .platform import public, identifier, canonical, now_utc, page_args

STATE_KINDS = {"inhibit", "resume", "rearm", "clear-fault"}


def parsed(parser, value):
    try:
        return parser(value)
    except (ModelValidationError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise HubError("invalid_request", str(exc), 400) from exc


class ControlMixin:
    def _operator(self, connection):
        actor = self._require_role("operator")
        if actor["auth_mode"] != "scoped_token":
            raise HubError("forbidden", "commands require an explicitly enrolled scoped operator", 403)
        row = connection.execute("SELECT * FROM principals WHERE subject=? AND role='operator' AND revoked_at IS NULL", (actor["subject"],)).fetchone()
        if row is None:
            raise HubError("forbidden", "operator grant is inactive", 403)
        return row

    @public
    def put_health_profile(self, device_id, body):
        self._require_role("admin")
        device = self.get_device(device_id)
        if (type(body) is not dict or set(body) != {"schema_version", "zone_id", "stale_after_s", "offline_after_s"}
                or body["schema_version"] != "poseidon.device-health-profile.v1"
                or type(body["stale_after_s"]) is not int or type(body["offline_after_s"]) is not int
                or not 0 < body["stale_after_s"] < body["offline_after_s"] <= 86400):
            raise HubError("invalid_request", "explicit zone and positive ordered health thresholds required", 400)
        identifier("zone_id", body["zone_id"])
        if device["revoked_at"]:
            raise HubError("device_revoked", "device is revoked", 409)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            key = "profile." + device_id
            old = document(connection, key)
            if old and old != body:
                raise HubError("profile_conflict", "health profile is immutable", 409)
            if old is None:
                put_document(connection, key, body)
                self._audit(connection, "device.health_profile", site_id=device["site_id"], device_id=device_id, details=body)
            connection.commit()
        return body

    @public
    def get_health_profile(self, device_id):
        self.get_device(device_id)
        with self._workspace.connect(read_only=True) as connection:
            result = document(connection, "profile." + device_id)
        if result is None:
            raise HubError("health_unprofiled", "device has no explicit zone/health profile", 404)
        return result

    def _health(self, connection, device):
        profile = document(connection, "profile." + device["id"])
        telemetry = connection.execute("SELECT received_at,envelope_json FROM telemetry WHERE device_id=? ORDER BY received_at DESC,id DESC LIMIT 1", (device["id"],)).fetchone()
        age = None
        if telemetry:
            envelope = json.loads(telemetry["envelope_json"])
            age = max(0.0, (datetime.now(timezone.utc) - parse_utc(telemetry["received_at"])).total_seconds()) + envelope["delivery_age_s"]
        health = "revoked" if device["revoked_at"] else "unprofiled" if profile is None else "offline" if age is None or age >= profile["offline_after_s"] else "stale" if age >= profile["stale_after_s"] else "online"
        return {"device_id": device["id"], "site_id": device["site_id"], "zone_id": profile["zone_id"] if profile else None,
                "health": health, "last_telemetry_at": telemetry["received_at"] if telemetry else None, "age_s": age, "profile": profile}

    def _alarm_condition(self, connection, *, source, site_id, device_id, condition, failed, severity, reason):
        key = "alarm-condition." + source + "." + device_id + "." + condition
        active_id = document(connection, key)
        active = connection.execute("SELECT * FROM alarms WHERE id=? AND cleared_at IS NULL", (active_id,)).fetchone() if active_id else None
        if failed and active is None:
            alarm_id = "alarm_" + secrets.token_hex(16)
            connection.execute("INSERT INTO alarms VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL)",
                               (alarm_id, source, site_id, device_id, severity, condition + ": " + reason, now_utc()))
            put_document(connection, key, alarm_id)
            self._audit(connection, "alarm.open", site_id=site_id, device_id=device_id, resource_id=alarm_id, details={"condition": condition})
        elif not failed and active is not None:
            connection.execute("UPDATE alarms SET cleared_at=? WHERE id=?", (now_utc(), active["id"]))
            self._audit(connection, "alarm.clear", site_id=site_id, device_id=device_id, resource_id=active["id"])

    def _refresh_device_health(self, connection):
        rows = connection.execute("SELECT * FROM devices").fetchall()
        for row in rows:
            health = self._health(connection, row)
            self._alarm_condition(connection, source="device", site_id=row["site_id"], device_id=row["id"], condition="connection",
                                  failed=health["health"] in {"stale", "offline"}, severity="warning", reason=health["health"])

    @public
    def list_device_health(self, limit=50, offset=0):
        page_args(limit, offset)
        scope, args = self._scope_sql("site_id", "id")
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Only update authorized devices from this request; process tick handles others.
            rows = connection.execute("SELECT * FROM devices WHERE " + scope + " ORDER BY id", args).fetchall()
            items = [self._health(connection, row) for row in rows]
            for item in items:
                self._alarm_condition(connection, source="device", site_id=item["site_id"], device_id=item["device_id"], condition="connection",
                                      failed=item["health"] in {"stale", "offline"}, severity="warning", reason=item["health"])
            connection.commit()
        return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}

    @public
    def list_alarms(self, limit=50, offset=0):
        page_args(limit, offset)
        scope, args = self._scope_sql("site_id", "device_id")
        with self._workspace.connect(read_only=True) as connection:
            total = connection.execute("SELECT COUNT(*) FROM alarms WHERE " + scope, args).fetchone()[0]
            rows = connection.execute("SELECT * FROM alarms WHERE " + scope + " ORDER BY opened_at DESC,id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    @public
    def acknowledge_alarm(self, alarm_id):
        actor = self._require_role("operator", "admin")
        identifier("alarm_id", alarm_id)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM alarms WHERE id=?", (alarm_id,)).fetchone()
            if row is None:
                raise HubError("alarm_not_found", "alarm was not found", 404)
            self._require_site(row["site_id"], row["device_id"])
            if row["acknowledged_by"] is None:
                connection.execute("UPDATE alarms SET acknowledged_by=?,acknowledged_at=? WHERE id=?", (actor["subject"], now_utc(), alarm_id))
                self._audit(connection, "alarm.acknowledge", site_id=row["site_id"], device_id=row["device_id"], resource_id=alarm_id)
            result = dict(connection.execute("SELECT * FROM alarms WHERE id=?", (alarm_id,)).fetchone())
            connection.commit()
        return result

    @staticmethod
    def _key_json(row):
        return {key: row[key] for key in ("key_id", "principal_id", "public_key_hex", "created_at", "revoked_at")} | {"site_ids": json.loads(row["site_ids_json"])}

    def _manage_key(self, connection, principal_id):
        actor = self._require_role("operator", "admin")
        row = connection.execute("SELECT * FROM principals WHERE id=? AND role='operator' AND revoked_at IS NULL", (principal_id,)).fetchone()
        if row is None:
            raise HubError("principal_not_found", "active operator principal was not found", 404)
        sites = json.loads(row["site_ids_json"])
        if (actor["role"] == "operator" and actor["subject"] != row["subject"]) or (actor["auth_mode"] != "local_development_key" and not set(sites).issubset(actor["site_ids"])):
            raise HubError("forbidden", "key is outside principal scope", 403)
        return row

    @public
    def enroll_command_key(self, body):
        if type(body) is not dict or set(body) != {"key_id", "principal_id", "public_key_hex"}:
            raise HubError("invalid_request", "key enrollment fields are invalid", 400)
        identifier("key_id", body["key_id"])
        identifier("principal_id", body["principal_id"])
        if type(body["public_key_hex"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", body["public_key_hex"]) or body["public_key_hex"] == "0" * 64:
            raise HubError("invalid_request", "public key must be 32 Ed25519 bytes in lowercase hex", 400)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            owner = self._manage_key(connection, body["principal_id"])
            if connection.execute("SELECT 1 FROM command_keys WHERE key_id=?", (body["key_id"],)).fetchone():
                raise HubError("key_conflict", "key identifier is immutable", 409)
            connection.execute("INSERT INTO command_keys VALUES (?,?,?,?,?,NULL)", (body["key_id"], body["principal_id"], body["public_key_hex"], owner["site_ids_json"], now_utc()))
            for site in json.loads(owner["site_ids_json"]):
                self._audit(connection, "command_key.enroll", site_id=site, resource_id=body["key_id"], details={"principal_id": body["principal_id"]})
            result = self._key_json(connection.execute("SELECT * FROM command_keys WHERE key_id=?", (body["key_id"],)).fetchone())
            connection.commit()
        return result

    @public
    def list_command_keys(self):
        actor = self._require_role("operator", "admin")
        with self._workspace.connect(read_only=True) as connection:
            rows = connection.execute("SELECT k.*,p.subject FROM command_keys k JOIN principals p ON p.id=k.principal_id ORDER BY k.key_id").fetchall()
        return {"items": [self._key_json(row) for row in rows if (actor["role"] != "operator" or row["subject"] == actor["subject"]) and (actor["auth_mode"] == "local_development_key" or set(json.loads(row["site_ids_json"])).issubset(actor["site_ids"]))]}

    @public
    def revoke_command_key(self, key_id):
        identifier("key_id", key_id)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM command_keys WHERE key_id=?", (key_id,)).fetchone()
            if row is None:
                raise HubError("key_not_found", "key was not found", 404)
            self._manage_key(connection, row["principal_id"])
            if row["revoked_at"] is None:
                connection.execute("UPDATE command_keys SET revoked_at=? WHERE key_id=?", (now_utc(), key_id))
                for site in json.loads(row["site_ids_json"]):
                    self._audit(connection, "command_key.revoke", site_id=site, resource_id=key_id)
            result = self._key_json(connection.execute("SELECT * FROM command_keys WHERE key_id=?", (key_id,)).fetchone())
            connection.commit()
        return result

    @staticmethod
    def _sequence(connection, device_id, principal_id):
        row = connection.execute("SELECT sequence_seen FROM command_counters WHERE device_id=? AND principal_id=?", (device_id, principal_id)).fetchone()
        return row[0] if row else "0"

    @public
    def command_context(self, device_id):
        self.get_device(device_id)
        with self._workspace.connect(read_only=True) as connection:
            principal = self._operator(connection)
            profile = document(connection, "profile." + device_id)
            keys = connection.execute("SELECT * FROM command_keys WHERE principal_id=? AND revoked_at IS NULL ORDER BY key_id", (principal["id"],)).fetchall()
            return {"principal_id": principal["id"], "device_id": device_id, "allowed_kinds": list(KINDS) if profile else [],
                    "sequence_seen": self._sequence(connection, device_id, principal["id"]), "keys": [self._key_json(row) for row in keys]}

    def _verify_signature(self, connection, body, principal_id, site_id):
        row = connection.execute("SELECT * FROM command_keys WHERE key_id=?", (body["key_id"],)).fetchone()
        if row is None:
            return "unknown_key"
        if row["revoked_at"] is not None:
            return "revoked_key"
        if row["principal_id"] != principal_id or site_id not in json.loads(row["site_ids_json"]):
            return "key_scope_mismatch"
        # Existing locked API dependency, imported only on the signed mutation path.
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(row["public_key_hex"])).verify(base64.b64decode(body["signature"]["value"], validate=True), payload_bytes(body))
        except (ValueError, InvalidSignature):
            return "signature_mismatch"
        return None

    @public
    def execute_command(self, wire: bytes | str | dict, *, retained=False):
        self._require_role("operator")
        body = parsed(parse_command, wire)
        if type(retained) is not bool:
            raise HubError("invalid_request", "retained must be boolean", 400)
        raw = canonical_json(body) if type(wire) is dict else wire.encode("utf-8") if type(wire) is str else wire
        with self._control_lock, self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            principal = self._operator(connection)
            # Scope rejection precedes all state/key/counter reads.
            self._require_site(body["site_id"], body["device_id"])
            binding = self._binding(connection, authorize=False)
            state_visible = binding is None or binding["site_id"] in json.loads(principal["site_ids_json"])
            seen = self._sequence(connection, body["device_id"], principal["id"])
            def ack(outcome, reason):
                return parse_command_ack({"schema_version": "poseidon.command-ack.v1", "command_id": body["command_id"], "device_id": body["device_id"],
                    "received_at": now_utc(), "outcome": outcome, "reason": reason, "state_after": self._state(connection) if state_visible else "inhibited", "sequence_seen": seen})
            reason = "retained_delivery" if retained else "principal_mismatch" if body["principal_id"] != principal["id"] else None
            device = connection.execute("SELECT * FROM devices WHERE id=?", (body["device_id"],)).fetchone()
            profile = document(connection, "profile." + body["device_id"])
            if reason is None:
                reason = "unknown_device" if device is None else "device_revoked" if device["revoked_at"] else "site_mismatch" if device["site_id"] != body["site_id"] else "health_unprofiled" if profile is None else "zone_mismatch" if profile["zone_id"] != body["zone_id"] else None
            if reason is None:
                reason = self._verify_signature(connection, body, principal["id"], body["site_id"])
            now = datetime.now(timezone.utc)
            if reason is None:
                reason = "expired" if parse_utc(body["expires_at"]) <= now else "not_yet_issued" if parse_utc(body["issued_at"]) > now else None
            if reason is None and json.loads(device["document_json"])["source_kind"] != "synthetic":
                reason = "digital_simulation_only"
            if reason is None and body["kind"] in STATE_KINDS and binding != {"device_id": body["device_id"], "site_id": body["site_id"], "zone_id": body["zone_id"]}:
                reason = "hub_target_mismatch"
            existing = connection.execute("SELECT * FROM commands WHERE command_id=?", (body["command_id"],)).fetchone()
            if reason is None and existing is not None and bytes(existing["wire_bytes"]) == raw:
                result = ack("duplicate", "byte-identical valid retry; no execution")
                self._audit(connection, "command.duplicate", site_id=body["site_id"], device_id=body["device_id"], resource_id=body["command_id"])
                connection.commit()
                return result
            if reason is None and (existing is not None or int(body["sequence"]) <= int(seen)):
                reason = "sequence_not_increasing" if existing is None else "command_id_conflict"
            if reason is not None:
                result = ack("expired" if reason == "expired" else "rejected", reason)
                self._audit(connection, "command.reject", site_id=body["site_id"], device_id=body["device_id"], resource_id=body["command_id"], details={"reason": reason})
                connection.commit()
                return result
            seen = body["sequence"]
            connection.execute("INSERT INTO command_counters VALUES (?,?,?) ON CONFLICT(device_id,principal_id) DO UPDATE SET sequence_seen=excluded.sequence_seen", (body["device_id"], principal["id"], seen))
            readings = self._evaluate_watchdogs(connection) if state_visible else []
            outcome, reason = "executed", "digital simulation only; no physical dispatch"
            kind = body["kind"]
            try:
                if kind in STATE_KINDS:
                    if kind == "rearm":
                        if not readings or not all(r["healthy"] for r in readings):
                            raise HubError("watchdogs_unhealthy", "all watchdogs must be healthy", 409)
                        if connection.execute("SELECT 1 FROM alarms WHERE source='hub' AND severity='critical' AND acknowledged_by IS NULL LIMIT 1").fetchone():
                            raise HubError("fault_unacknowledged", "fault alarm must be acknowledged", 409)
                    if kind == "clear-fault" and connection.execute("SELECT 1 FROM alarms WHERE source='hub' AND severity='critical' AND acknowledged_by IS NULL LIMIT 1").fetchone():
                        raise HubError("fault_unacknowledged", "fault alarm must be acknowledged", 409)
                    target = {"inhibit": "inhibited", "resume": "observe", "rearm": "armed", "clear-fault": "inhibited"}[kind]
                    self._transition(connection, target, kind, command_id=body["command_id"])
                elif kind == "config-apply":
                    put_document(connection, "device-config." + body["device_id"], migrate_config(body["params"]["config"]))
            except HubError as exc:
                outcome, reason = "failed", exc.code
                self._alarm_condition(connection, source="device", site_id=body["site_id"], device_id=body["device_id"], condition="command." + body["command_id"], failed=True, severity="warning", reason=reason)
            result = ack(outcome, reason)
            connection.execute("INSERT INTO commands VALUES (?,?,?,?,?,?,?,?)", (body["command_id"], body["site_id"], body["device_id"], principal["id"], seen, raw, canonical(body), canonical(result)))
            self._audit(connection, "command." + outcome, site_id=body["site_id"], device_id=body["device_id"], resource_id=body["command_id"], details={"kind": kind, "simulation": True, "sequence": seen, "reason": reason})
            connection.commit()
            return result

    @public
    def get_command(self, command_id):
        identifier("command_id", command_id)
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
        if row is None:
            raise HubError("command_not_found", "command was not found", 404)
        self._require_site(row["site_id"], row["device_id"])
        return {"command": json.loads(row["command_json"]), "ack": json.loads(row["ack_json"])}

    @public
    def list_commands(self, limit=50, offset=0):
        page_args(limit, offset)
        scope, args = self._scope_sql("site_id", "device_id")
        with self._workspace.connect(read_only=True) as connection:
            total = connection.execute("SELECT COUNT(*) FROM commands WHERE " + scope, args).fetchone()[0]
            rows = connection.execute("SELECT * FROM commands WHERE " + scope + " ORDER BY rowid DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        return {"items": [{"command": json.loads(r["command_json"]), "ack": json.loads(r["ack_json"])} for r in rows], "total": total, "limit": limit, "offset": offset}

    @public
    def create_calibration(self, value):
        body = parsed(parse_calibration, value)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            operator = self._operator(connection)
            device = self.get_device(body["instrument_id"])
            self.get_health_profile(body["instrument_id"])
            if body["operator_id"] != operator["id"] or device["revoked_at"]:
                raise HubError("forbidden", "calibration requires the matching active operator and instrument", 403)
            reason = self._verify_signature(connection, body, operator["id"], device["site_id"])
            if reason:
                raise HubError("invalid_signature", reason, 403)
            if parse_utc(body["valid_until"]) <= datetime.now(timezone.utc):
                raise HubError("calibration_expired", "expired calibration cannot be enrolled", 409)
            if connection.execute("SELECT 1 FROM calibrations WHERE record_id=?", (body["record_id"],)).fetchone():
                raise HubError("calibration_immutable", "record identity is already enrolled", 409)
            predecessor = body["supersedes_id"]
            seen = {body["record_id"]}
            while predecessor is not None:
                if predecessor in seen:
                    raise HubError("calibration_chain", "cyclic calibration chain", 409)
                seen.add(predecessor)
                prior = connection.execute("SELECT * FROM calibrations WHERE record_id=?", (predecessor,)).fetchone()
                if prior is None or prior["instrument_id"] != body["instrument_id"] or prior["quantity"] != body["quantity"]:
                    raise HubError("calibration_chain", "predecessor must exist for the same instrument and quantity", 409)
                predecessor = prior["supersedes_id"]
            if body["supersedes_id"] and connection.execute("SELECT 1 FROM calibrations WHERE supersedes_id=?", (body["supersedes_id"],)).fetchone():
                raise HubError("calibration_chain", "predecessor already superseded", 409)
            connection.execute("INSERT INTO calibrations VALUES (?,?,?,?,?,?)", (body["record_id"], body["instrument_id"], device["site_id"], body["quantity"], body["supersedes_id"], canonical(body)))
            self._audit(connection, "calibration.enroll", site_id=device["site_id"], device_id=body["instrument_id"], resource_id=body["record_id"], details={"digital_only": True, "supersedes_id": body["supersedes_id"]})
            result = self._calibration_json(connection, body)
            connection.commit()
            return result

    @staticmethod
    def _calibration_json(connection, record):
        now = datetime.now(timezone.utc)
        superseded = connection.execute("SELECT 1 FROM calibrations WHERE supersedes_id=?", (record["record_id"],)).fetchone()
        validity = "superseded" if superseded else "expired" if parse_utc(record["valid_until"]) <= now else "not_yet_valid" if parse_utc(record["valid_from"]) > now else "current"
        return {"record": record, "validity": validity}

    @public
    def list_calibrations(self, limit=50, offset=0):
        page_args(limit, offset)
        scope, args = self._scope_sql("site_id", "instrument_id")
        with self._workspace.connect(read_only=True) as connection:
            total = connection.execute("SELECT COUNT(*) FROM calibrations WHERE " + scope, args).fetchone()[0]
            rows = connection.execute("SELECT document_json FROM calibrations WHERE " + scope + " ORDER BY rowid DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
            items = [self._calibration_json(connection, json.loads(row[0])) for row in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @public
    def get_calibration(self, record_id):
        identifier("record_id", record_id)
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute("SELECT * FROM calibrations WHERE record_id=?", (record_id,)).fetchone()
            if row is None:
                raise HubError("calibration_not_found", "calibration was not found", 404)
            self._require_site(row["site_id"], row["instrument_id"])
            return self._calibration_json(connection, json.loads(row["document_json"]))
