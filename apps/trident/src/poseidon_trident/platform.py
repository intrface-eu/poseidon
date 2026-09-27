"""Local scoped identity, observations and telemetry. Standard library only.

The unscoped Python Hub is the trusted local operator interface. HTTP always uses
ScopedHub, whose context is set inside each call (including worker-thread calls).
No credential or filesystem path is accepted as a declared actor in request JSON.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from typing import Any, Iterator

from poseidon_proto import ModelValidationError
from poseidon_proto.platform import validate_contract

from .errors import HubError


_LOCAL = {
    "subject": "local-development", "role": "admin", "site_ids": [],
    "device_id": None, "auth_mode": "local_development_key",
}
_ACTOR: ContextVar[dict | None] = ContextVar("poseidon_actor", default=None)
_ROLES = {"viewer", "reviewer", "admin", "device", "operator"}
_MAX_AGE_S = 604800


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise HubError("invalid_request", "request must contain finite JSON values", 400) from exc


def contract(name: str, value: Any, maximum: int = 65536) -> dict:
    if len(canonical(value).encode("utf-8")) > maximum:
        raise HubError("request_too_large", "request body exceeds the size limit", 413)
    try:
        validate_contract(name, value)
    except ModelValidationError as exc:
        raise HubError("invalid_request", str(exc), 400) from exc
    return value


def identifier(name: str, value: Any) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 128
            or not value[0].isascii() or not value[0].isalnum()
            or any(not (c.isascii() and (c.isalnum() or c in "._-")) for c in value)):
        raise HubError("invalid_identifier", f"{name} is not a valid identifier", 400)
    return value


def page_args(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 2**63 - 1:
        raise HubError("invalid_pagination", "limit must be 1..200 and offset a nonnegative integer", 400)


def public(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._workspace.operation():
            try:
                self._authorize_method(method.__name__, args, kwargs)
                return method(self, *args, **kwargs)
            except HubError as exc:
                if exc.code in {"companion_store_error", "evidence_store_error", "workspace_corrupt"} and hasattr(self, "_integrity_failure"):
                    self._integrity_failure(exc.code)
                if exc.status_code in {403, 409}:
                    self._audit_denial(method.__name__, exc.code)
                raise
            except sqlite3.Error as exc:
                raise HubError("workspace_unavailable", "cannot access platform storage", 500) from exc
    return call


class ScopedHub:
    """Request-local facade, never a mutable principal field on the shared Hub."""

    def __init__(self, hub, principal: dict) -> None:
        self._hub = hub
        self._principal = json.loads(canonical(principal))

    def __getattr__(self, name: str):
        if name.startswith("_") or name in {"for_principal", "authenticate", "close", "access_token", "process_next_job"}:
            raise AttributeError(name)
        method = getattr(self._hub, name)
        if not callable(method):
            raise AttributeError(name)

        @wraps(method)
        def call(*args, **kwargs):
            with self._hub.principal_context(self._principal):
                return method(*args, **kwargs)
        return call


class PlatformMixin:
    def for_principal(self, principal: dict) -> ScopedHub:
        return ScopedHub(self, principal)

    @contextmanager
    def principal_context(self, principal: dict) -> Iterator[None]:
        token = _ACTOR.set(principal)
        try:
            yield
        finally:
            _ACTOR.reset(token)

    def _actor(self) -> dict:
        actor = _ACTOR.get()
        if actor is None or actor.get("auth_mode") == "local_development_key":
            return dict(_LOCAL)
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute(
                "SELECT * FROM principals WHERE id = ? AND revoked_at IS NULL",
                (actor.get("_principal_id"),),
            ).fetchone()
            if row is None or not hmac.compare_digest(row["token_hash"], actor.get("_token_hash", "")):
                raise HubError("unauthorized", "authentication required", 401)
            if row["device_id"] is not None:
                device = connection.execute("SELECT revoked_at FROM devices WHERE id = ?", (row["device_id"],)).fetchone()
                if device is None or device["revoked_at"] is not None:
                    raise HubError("unauthorized", "authentication required", 401)
        result = self._principal_json(row)
        return {key: result[key] for key in ("subject", "role", "site_ids", "device_id")} | {"auth_mode": "scoped_token"}

    @public
    def current_identity(self) -> dict:
        return self._actor()

    @public
    def authenticate(self, token: str) -> dict:
        if type(token) is not str or len(token) > 256:
            raise HubError("unauthorized", "authentication required", 401)
        if hmac.compare_digest(token.encode("utf-8"), self._workspace.access_token().encode("ascii")):
            return dict(_LOCAL)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute("SELECT * FROM principals WHERE token_hash = ? AND revoked_at IS NULL", (digest,)).fetchone()
            if row is not None and row["device_id"] is not None:
                device = connection.execute("SELECT revoked_at FROM devices WHERE id = ?", (row["device_id"],)).fetchone()
                if device is None or device["revoked_at"] is not None:
                    row = None
        if row is None:
            raise HubError("unauthorized", "authentication required", 401)
        principal = self._principal_json(row)
        return {key: principal[key] for key in ("subject", "role", "site_ids", "device_id")} | {
            "auth_mode": "scoped_token", "_principal_id": row["id"], "_token_hash": digest,
        }

    def _require_role(self, *roles: str) -> dict:
        actor = self._actor()
        if actor["role"] not in roles:
            raise HubError("forbidden", "this role cannot perform the operation", 403)
        return actor

    def _require_site(self, site_id: str, device_id: str | None = None) -> dict:
        actor = self._actor()
        if actor["auth_mode"] != "local_development_key":
            if site_id not in actor["site_ids"] or (actor["role"] == "device" and device_id != actor["device_id"]):
                raise HubError("not_found", "resource was not found", 404)
        return actor

    def _scope_sql(self, site_column: str, device_column: str | None = None) -> tuple[str, list]:
        actor = self._actor()
        if actor["auth_mode"] == "local_development_key":
            return "1 = 1", []
        sites = actor["site_ids"]
        if not sites:
            return "0 = 1", []
        expression = f"{site_column} IN ({','.join('?' for _ in sites)})"
        parameters = list(sites)
        if actor["role"] == "device":
            if device_column is None:
                return "0 = 1", []
            expression += f" AND {device_column} = ?"
            parameters.append(actor["device_id"])
        return expression, parameters

    def _recording_scope_sql(self, recording_column: str) -> tuple[str, list]:
        if self._actor()["auth_mode"] == "local_development_key":
            return "1 = 1", []
        scope, parameters = self._scope_sql("aps.site_id", "aps.device_id")
        return (
            "EXISTS (SELECT 1 FROM recording_sessions rs JOIN acquisition_sessions aps "
            "ON aps.id = rs.session_id WHERE rs.recording_id = " + recording_column + " AND " + scope + ")",
            parameters,
        )

    def _recording_access(self, recording_id: str) -> None:
        identifier("recording_id", recording_id)
        scope, parameters = self._recording_scope_sql("s.recording_id")
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute("SELECT s.recording_id FROM sources s WHERE s.recording_id = ? AND " + scope,
                                     [recording_id, *parameters]).fetchone()
        if row is None:
            raise HubError("recording_not_found", "recording was not found", 404)

    def _authorize_method(self, name: str, args: tuple, kwargs: dict) -> None:
        actor = self._actor()
        if name in {"submit_recording", "submit_demo", "access_token", "process_next_job", "authenticate"}:
            if actor["auth_mode"] != "local_development_key":
                raise HubError("forbidden", "operation requires the local development key", 403)
        if name in {"save_review", "attach_video", "create_observation", "update_observation"}:
            self._require_role("reviewer", "admin")
        if actor["auth_mode"] == "local_development_key":
            return
        recording_methods = {
            "get_recording", "waveform", "attach_video", "video_path", "list_observations",
            "create_observation", "update_observation", "observation_history",
            "get_recording_session", "bind_recording_session",
        }
        if name in recording_methods:
            self._recording_access(args[0] if args else kwargs.get("recording_id"))
        elif name in {"get_event", "save_review", "get_job"}:
            key = "job_id" if name == "get_job" else "event_id"
            value = args[0] if args else kwargs.get(key)
            identifier(key, value)
            table, column = ("jobs", "id") if name == "get_job" else ("event_index", "event_id")
            with self._workspace.connect(read_only=True) as connection:
                row = connection.execute(f"SELECT recording_id FROM {table} WHERE {column} = ?", (value,)).fetchone()
            if row is None:
                raise HubError("not_found", "resource was not found", 404)
            self._recording_access(row["recording_id"])

    def _audit(self, connection, action: str, *, site_id: str | None = None,
               device_id: str | None = None, resource_id: str | None = None, details: dict | None = None) -> None:
        actor = self._actor()
        connection.execute(
            "INSERT INTO security_audit (action, actor_subject, auth_mode, site_id, device_id, resource_id, created_at, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (action, actor["subject"], actor["auth_mode"], site_id, device_id, resource_id, now_utc(), canonical(details or {})),
        )

    def _audit_denial(self, action: str, code: str) -> None:
        # Only declared operation/code are recorded; never request text or tokens.
        try:
            actor = self._actor()
            sites = [None] if actor["auth_mode"] == "local_development_key" else actor["site_ids"]
            with self._workspace.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for site in sites:
                    self._audit(connection, "denied." + action, site_id=site,
                                device_id=actor["device_id"], details={"code": code})
                connection.commit()
        except (HubError, sqlite3.Error):
            pass  # Original rejection still reaches the caller if auditing is unavailable.

    def _audit_recording(self, connection, action: str, recording_id: str, details: dict | None = None) -> None:
        row = connection.execute(
            "SELECT a.site_id, a.device_id FROM recording_sessions r JOIN acquisition_sessions a "
            "ON a.id = r.session_id WHERE r.recording_id = ?", (recording_id,),
        ).fetchone()
        self._audit(connection, action, site_id=row["site_id"] if row else None,
                    device_id=row["device_id"] if row else None, resource_id=recording_id, details=details)

    @staticmethod
    def _principal_json(row) -> dict:
        return {"id": row["id"], "subject": row["subject"], "role": row["role"],
                "site_ids": json.loads(row["site_ids_json"]), "device_id": row["device_id"],
                "created_at": row["created_at"], "updated_at": row["updated_at"], "revoked_at": row["revoked_at"]}

    def _manageable_principal(self, row) -> dict:
        actor = self._require_role("admin")
        if row is None:
            raise HubError("principal_not_found", "principal was not found", 404)
        result = self._principal_json(row)
        if actor["auth_mode"] != "local_development_key" and not set(result["site_ids"]).issubset(actor["site_ids"]):
            raise HubError("principal_not_found", "principal was not found", 404)
        return result

    @public
    def create_principal(self, body: dict) -> dict:
        actor = self._require_role("admin")
        if type(body) is not dict or set(body) != {"subject", "role", "site_ids", "device_id"}:
            raise HubError("invalid_request", "principal fields are invalid", 400)
        subject = identifier("subject", body["subject"])
        if subject == _LOCAL["subject"]:
            raise HubError("invalid_request", "subject is reserved", 400)
        role, sites, device_id = body["role"], body["site_ids"], body["device_id"]
        if type(role) is not str or role not in _ROLES or type(sites) is not list or not 1 <= len(sites) <= 64:
            raise HubError("invalid_request", "role or site_ids are invalid", 400)
        for site in sites:
            identifier("site_id", site)
        if len(set(sites)) != len(sites):
            raise HubError("invalid_request", "site_ids must be unique", 400)
        if actor["auth_mode"] != "local_development_key" and not set(sites).issubset(actor["site_ids"]):
            raise HubError("forbidden", "cannot grant sites outside the admin scope", 403)
        if role == "device":
            identifier("device_id", device_id)
            if len(sites) != 1:
                raise HubError("invalid_request", "device credentials require exactly one site", 400)
        elif device_id is not None:
            raise HubError("invalid_request", "human credentials require device_id null", 400)
        principal_id, token, now = "principal_" + secrets.token_hex(16), secrets.token_urlsafe(32), now_utc()
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if role == "device":
                device = connection.execute("SELECT site_id, revoked_at FROM devices WHERE id = ?", (device_id,)).fetchone()
                if device is None or device["site_id"] != sites[0] or device["revoked_at"] is not None:
                    raise HubError("invalid_device", "device is not active in the credential site", 400)
            if connection.execute("SELECT 1 FROM principals WHERE subject = ?", (subject,)).fetchone():
                raise HubError("principal_conflict", "subject is already enrolled", 409)
            connection.execute("INSERT INTO principals VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                               (principal_id, subject, role, canonical(sorted(sites)), device_id,
                                hashlib.sha256(token.encode("ascii")).hexdigest(), now, now))
            for site in sites:
                self._audit(connection, "principal.enroll", site_id=site, device_id=device_id,
                            resource_id=principal_id, details={"role": role, "subject": subject})
            row = connection.execute("SELECT * FROM principals WHERE id = ?", (principal_id,)).fetchone()
            connection.commit()
        return {"principal": self._principal_json(row), "token": token}

    @public
    def list_principals(self, limit: int = 50, offset: int = 0) -> dict:
        actor = self._require_role("admin")
        page_args(limit, offset)
        with self._workspace.connect(read_only=True) as connection:
            # At most 64 sites per principal. Scope the entire grant, not any one site.
            rows = connection.execute("SELECT * FROM principals ORDER BY created_at DESC, id DESC").fetchall()
        items = [self._principal_json(row) for row in rows
                 if actor["auth_mode"] == "local_development_key" or set(json.loads(row["site_ids_json"])).issubset(actor["site_ids"])]
        return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}

    @public
    def rotate_principal(self, principal_id: str) -> dict:
        return self._change_principal(principal_id, revoke=False)

    @public
    def revoke_principal(self, principal_id: str) -> dict:
        return self._change_principal(principal_id, revoke=True)

    def _change_principal(self, principal_id: str, *, revoke: bool) -> dict:
        self._require_role("admin")
        identifier("principal_id", principal_id)
        token, now = secrets.token_urlsafe(32), now_utc()
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM principals WHERE id = ?", (principal_id,)).fetchone()
            result = self._manageable_principal(row)
            if result["revoked_at"] is not None:
                if revoke:
                    return result
                raise HubError("principal_revoked", "revoked principals cannot rotate credentials", 409)
            if not revoke and result["device_id"] is not None:
                device = connection.execute("SELECT revoked_at FROM devices WHERE id = ?", (result["device_id"],)).fetchone()
                if device["revoked_at"] is not None:
                    raise HubError("device_revoked", "device is revoked", 409)
            for site in result["site_ids"]:
                self._audit(connection, "principal.revoke" if revoke else "principal.rotate", site_id=site,
                            device_id=result["device_id"], resource_id=principal_id)
            if revoke:
                connection.execute("UPDATE principals SET revoked_at = ?, updated_at = ? WHERE id = ?", (now, now, principal_id))
            else:
                connection.execute("UPDATE principals SET token_hash = ?, updated_at = ? WHERE id = ?",
                                   (hashlib.sha256(token.encode("ascii")).hexdigest(), now, principal_id))
            row = connection.execute("SELECT * FROM principals WHERE id = ?", (principal_id,)).fetchone()
            connection.commit()
        result = self._principal_json(row)
        return result if revoke else {"principal": result, "token": token}

    @staticmethod
    def _device_json(row) -> dict:
        return json.loads(row["document_json"]) | {"created_at": row["created_at"], "revoked_at": row["revoked_at"]}

    @public
    def create_device(self, body: dict) -> dict:
        self._require_role("admin")
        contract("device", body)
        self._require_site(body["site_id"])
        now = now_utc()
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM devices WHERE id = ?", (body["id"],)).fetchone():
                raise HubError("device_conflict", "device identity is already registered", 409)
            connection.execute("INSERT INTO devices VALUES (?, ?, ?, ?, NULL)", (body["id"], body["site_id"], canonical(body), now))
            self._audit(connection, "device.register", site_id=body["site_id"], device_id=body["id"], resource_id=body["id"])
            connection.commit()
        return body | {"created_at": now, "revoked_at": None}

    @public
    def get_device(self, device_id: str) -> dict:
        identifier("device_id", device_id)
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if row is None:
            raise HubError("device_not_found", "device was not found", 404)
        self._require_site(row["site_id"], device_id)
        return self._device_json(row)

    @public
    def list_devices(self, limit: int = 50, offset: int = 0) -> dict:
        page_args(limit, offset)
        scope, args = self._scope_sql("site_id", "id")
        with self._workspace.connect(read_only=True) as connection:
            total = connection.execute("SELECT COUNT(*) FROM devices WHERE " + scope, args).fetchone()[0]
            rows = connection.execute("SELECT * FROM devices WHERE " + scope + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        return {"items": [self._device_json(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    @public
    def revoke_device(self, device_id: str) -> dict:
        self._require_role("admin")
        self.get_device(device_id)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            if row["revoked_at"] is None:
                now = now_utc()
                connection.execute("UPDATE devices SET revoked_at = ? WHERE id = ?", (now, device_id))
                connection.execute("UPDATE principals SET revoked_at = ?, updated_at = ? WHERE device_id = ? AND revoked_at IS NULL", (now, now, device_id))
                self._audit(connection, "device.revoke", site_id=row["site_id"], device_id=device_id, resource_id=device_id)
            row = connection.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            connection.commit()
        return self._device_json(row)

    @public
    def put_aquilon_mapping(self, device_id: str, body: dict) -> dict:
        self._require_role("admin")
        device = self.get_device(device_id)
        if device["revoked_at"] is not None:
            raise HubError("device_revoked", "device is revoked", 409)
        if type(body) is not dict or set(body) != {"dev_eui", "calibration_refs"}:
            raise HubError("invalid_request", "mapping fields are invalid", 400)
        if type(body["dev_eui"]) is not str or not re.fullmatch(r"[a-f0-9]{16}", body["dev_eui"]):
            raise HubError("invalid_request", "DevEUI must be 16 lowercase hex digits", 400)
        refs = body["calibration_refs"]
        if type(refs) is not list or len(canonical(body).encode("utf-8")) > 65536:
            raise HubError("invalid_request", "calibration_refs must be a bounded array", 400)
        codes = set()
        for ref in refs:
            if type(ref) is not dict or set(ref) != {"code", "sensor_kind", "calibration_id"}:
                raise HubError("invalid_request", "calibration reference fields are invalid", 400)
            if type(ref["code"]) is not int or not 1 <= ref["code"] <= 65535 or ref["code"] in codes:
                raise HubError("invalid_request", "calibration codes must be unique uint16 nonzero values", 400)
            if type(ref["sensor_kind"]) is not str or ref["sensor_kind"] not in {"temperature", "salinity", "dissolved_oxygen"}:
                raise HubError("invalid_request", "calibration sensor_kind is unsupported", 400)
            identifier("calibration_id", ref["calibration_id"])
            codes.add(ref["code"])
        payload = canonical(body)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT * FROM aquilon_mappings WHERE device_id = ?", (device_id,)).fetchone()
            if existing is not None:
                if existing["document_json"] == payload:
                    return json.loads(payload)
                raise HubError("mapping_conflict", "device mapping cannot be replaced", 409)
            if connection.execute("SELECT 1 FROM aquilon_mappings WHERE dev_eui = ?", (body["dev_eui"],)).fetchone():
                raise HubError("mapping_conflict", "DevEUI is already registered", 409)
            connection.execute("INSERT INTO aquilon_mappings VALUES (?, ?, ?)", (device_id, body["dev_eui"], payload))
            self._audit(connection, "device.map_aquilon", site_id=device["site_id"], device_id=device_id, resource_id=device_id)
            connection.commit()
        return json.loads(payload)

    @public
    def get_aquilon_mapping(self, device_id: str) -> dict:
        self._require_role("admin", "device")
        self.get_device(device_id)
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute("SELECT document_json FROM aquilon_mappings WHERE device_id = ?", (device_id,)).fetchone()
        if row is None:
            raise HubError("mapping_not_found", "AQUILON mapping was not found", 404)
        return json.loads(row["document_json"])

    def _validate_telemetry_mapping(self, connection, body: dict) -> None:
        row = connection.execute("SELECT document_json FROM aquilon_mappings WHERE device_id = ?", (body["device_id"],)).fetchone()
        mapping = json.loads(row["document_json"]) if row else None
        radio = body.get("radio")
        if body["provenance"]["transport"] == "aquilon":
            if mapping is None or radio is None or radio["dev_eui"] != mapping["dev_eui"]:
                raise HubError("telemetry_mapping", "AQUILON identity does not match the immutable registry mapping", 400)
        elif radio is not None:
            raise HubError("telemetry_mapping", "radio provenance requires AQUILON transport", 400)
        refs = mapping["calibration_refs"] if mapping else []
        calibrated = []
        for measurement in body["measurements"]:
            if measurement["quality"] != "calibrated":
                if measurement["calibration_id"] is not None:
                    raise HubError("telemetry_calibration", "uncalibrated or invalid values cannot carry calibration claims", 400)
                continue
            matching = [ref for ref in refs if ref["sensor_kind"] == measurement["name"] and ref["calibration_id"] == measurement["calibration_id"]]
            if radio is not None:
                matching = [ref for ref in matching if ref["code"] == radio["calibration_code"]]
            if not matching:
                raise HubError("telemetry_calibration", "calibrated claim lacks a matching device-specific registry reference", 400)
            calibrated.append(measurement)
        if radio is not None and (radio["calibration_code"] is not None) != bool(calibrated):
            raise HubError("telemetry_calibration", "radio calibration code must match a calibrated measurement", 400)

    @public
    def create_session(self, body: dict) -> dict:
        actor = self._require_role("admin")
        contract("acquisition-session", body)
        self._require_site(body["site_id"])
        if body["device_id"] is not None:
            device = self.get_device(body["device_id"])
            if device["site_id"] != body["site_id"] or device["source_kind"] != body["provenance"]["source_kind"] or device["revoked_at"] is not None:
                raise HubError("session_source_mismatch", "session does not match the active device source", 400)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT document_json FROM acquisition_sessions WHERE id = ?", (body["id"],)).fetchone()
            if old is not None:
                if old["document_json"] == canonical(body):
                    return json.loads(old["document_json"])
                raise HubError("session_conflict", "session identity is already bound to different metadata", 409)
            connection.execute("INSERT INTO acquisition_sessions VALUES (?, ?, ?, ?, ?, ?)",
                               (body["id"], body["site_id"], body["device_id"], canonical(body), now_utc(), actor["subject"]))
            self._audit(connection, "session.create", site_id=body["site_id"], device_id=body["device_id"], resource_id=body["id"])
            connection.commit()
        return body

    @public
    def get_session(self, session_id: str) -> dict:
        identifier("session_id", session_id)
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute("SELECT * FROM acquisition_sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise HubError("session_not_found", "acquisition session was not found", 404)
        self._require_site(row["site_id"], row["device_id"])
        return json.loads(row["document_json"])

    @public
    def list_sessions(self, limit: int = 50, offset: int = 0) -> dict:
        page_args(limit, offset)
        scope, args = self._scope_sql("site_id", "device_id")
        with self._workspace.connect(read_only=True) as connection:
            total = connection.execute("SELECT COUNT(*) FROM acquisition_sessions WHERE " + scope, args).fetchone()[0]
            rows = connection.execute("SELECT document_json FROM acquisition_sessions WHERE " + scope + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        return {"items": [json.loads(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}

    @public
    def bind_recording_session(self, recording_id: str, session_id: str) -> dict:
        actor = self._require_role("admin")
        recording = self.get_recording(recording_id)
        session = self.get_session(session_id)
        if (session["site_id"] != recording["site_id"]
                or session["device_id"] != recording["device_id"]
                or session["provenance"]["source_kind"] != recording["provenance"]):
            raise HubError("session_source_mismatch", "session site, device and source kind must match the recording", 409)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT session_id FROM recording_sessions WHERE recording_id = ?", (recording_id,)).fetchone()
            if row is not None:
                if row["session_id"] == session_id:
                    return session
                raise HubError("session_binding_conflict", "recording is already bound to another session", 409)
            connection.execute("INSERT INTO recording_sessions VALUES (?, ?, ?, ?)", (recording_id, session_id, now_utc(), actor["subject"]))
            self._audit_recording(connection, "recording.bind_session", recording_id,
                                  {"session_id": session_id, "recording_sha256": recording["wav_sha256"]})
            connection.commit()
        return session

    @public
    def get_recording_session(self, recording_id: str) -> dict | None:
        self.get_recording(recording_id)
        with self._workspace.connect(read_only=True) as connection:
            row = connection.execute("SELECT session_id FROM recording_sessions WHERE recording_id = ?", (recording_id,)).fetchone()
        return self.get_session(row["session_id"]) if row else None

    @public
    def create_observation(self, recording_id: str, body: dict) -> dict:
        return self._save_observation(recording_id, body, create=True)

    @public
    def update_observation(self, recording_id: str, observation_id: str, body: dict) -> dict:
        identifier("observation_id", observation_id)
        contract("independent-observation", body)
        if body["id"] != observation_id:
            raise HubError("invalid_request", "observation ID must match the route", 400)
        return self._save_observation(recording_id, body, create=False)

    def _save_observation(self, recording_id: str, body: dict, *, create: bool) -> dict:
        actor = self._require_role("reviewer", "admin")
        contract("independent-observation", body)
        recording = self.get_recording(recording_id)
        if not 0 <= body["start_s"] < body["end_s"] <= recording["duration_s"]:
            raise HubError("invalid_observation", "interval must lie within the recording duration", 400)
        now = now_utc()
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute("SELECT * FROM independent_observations WHERE id = ?", (body["id"],)).fetchone()
            if create:
                if source is not None or body["expected_revision"] != 0:
                    raise HubError("observation_conflict", "observation identity or revision already exists", 409)
                provenance = {"recording_sha256": recording["wav_sha256"], "source_kind": recording["provenance"]}
                created_at, revision = now, 1
                connection.execute("INSERT INTO independent_observations VALUES (?, ?, ?, ?)",
                                   (body["id"], recording_id, now, canonical(provenance)))
            else:
                if source is None or source["recording_id"] != recording_id:
                    raise HubError("observation_not_found", "observation was not found", 404)
                current = connection.execute("SELECT MAX(revision) FROM observation_history WHERE observation_id = ?", (body["id"],)).fetchone()[0]
                if current != body["expected_revision"]:
                    raise HubError("observation_conflict", "observation revision changed; reload before saving", 409)
                created_at, provenance, revision = source["created_at"], json.loads(source["provenance_json"]), current + 1
            result = body | {"recording_id": recording_id, "revision": revision, "actor_subject": actor["subject"],
                             "auth_mode": actor["auth_mode"], "created_at": created_at, "updated_at": now, "provenance": provenance}
            connection.execute("INSERT INTO observation_history VALUES (?, ?, ?)", (body["id"], revision, canonical(result)))
            self._audit_recording(connection, "observation.create" if create else "observation.revise", recording_id,
                                  {"observation_id": body["id"], "revision": revision})
            connection.commit()
        return result

    @public
    def list_observations(self, recording_id: str, limit: int = 50, offset: int = 0) -> dict:
        self.get_recording(recording_id)
        page_args(limit, offset)
        with self._workspace.connect(read_only=True) as connection:
            total = connection.execute("SELECT COUNT(*) FROM independent_observations WHERE recording_id = ?", (recording_id,)).fetchone()[0]
            rows = connection.execute(
                "SELECT h.document_json FROM independent_observations o JOIN observation_history h ON h.observation_id = o.id "
                "AND h.revision = (SELECT MAX(n.revision) FROM observation_history n WHERE n.observation_id = o.id) "
                "WHERE o.recording_id = ? ORDER BY o.created_at, o.id LIMIT ? OFFSET ?", (recording_id, limit, offset),
            ).fetchall()
        return {"items": [json.loads(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}

    @public
    def observation_history(self, recording_id: str, observation_id: str, limit: int = 50, offset: int = 0) -> dict:
        self.get_recording(recording_id)
        identifier("observation_id", observation_id)
        page_args(limit, offset)
        with self._workspace.connect(read_only=True) as connection:
            if not connection.execute("SELECT 1 FROM independent_observations WHERE id = ? AND recording_id = ?", (observation_id, recording_id)).fetchone():
                raise HubError("observation_not_found", "observation was not found", 404)
            total = connection.execute("SELECT COUNT(*) FROM observation_history WHERE observation_id = ?", (observation_id,)).fetchone()[0]
            rows = connection.execute("SELECT document_json FROM observation_history WHERE observation_id = ? ORDER BY revision LIMIT ? OFFSET ?", (observation_id, limit, offset)).fetchall()
        return {"items": [json.loads(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}

    @staticmethod
    def _telemetry_json(row, duplicate: bool = False) -> dict:
        return {"id": row["id"], "envelope": json.loads(row["envelope_json"]), "received_at": row["received_at"],
                "actor_subject": row["actor_subject"], "duplicate": duplicate}

    @public
    def ingest_telemetry(self, body: dict) -> dict:
        actor = self._require_role("device")
        contract("telemetry-envelope", body, 16384)
        self._require_site(body["site_id"], body["device_id"])
        payload = canonical(body)
        now = now_utc()
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            device = connection.execute("SELECT * FROM devices WHERE id = ?", (body["device_id"],)).fetchone()
            if device is None or device["revoked_at"] is not None:
                raise HubError("device_revoked", "device is not active", 403)
            document = json.loads(device["document_json"])
            if device["site_id"] != body["site_id"] or document["source_kind"] != body["provenance"]["source_kind"]:
                raise HubError("telemetry_source_mismatch", "telemetry does not match the registered device source", 400)
            self._validate_telemetry_mapping(connection, body)
            key = (body["device_id"], body["boot_id"], body["sequence"])
            existing = connection.execute("SELECT * FROM telemetry WHERE device_id = ? AND boot_id = ? AND sequence = ?", key).fetchone()
            if existing is not None:
                if existing["envelope_json"] != payload:
                    raise HubError("telemetry_conflict", "telemetry sequence is already bound to different contents", 409)
                self._audit(connection, "telemetry.duplicate", site_id=body["site_id"], device_id=body["device_id"], resource_id=existing["id"])
                connection.commit()
                return self._telemetry_json(existing, duplicate=True)
            latest_boot = connection.execute(
                "SELECT boot_id FROM telemetry WHERE device_id = ? ORDER BY length(boot_id) DESC, boot_id DESC LIMIT 1",
                (body["device_id"],),
            ).fetchone()
            if latest_boot is not None and int(body["boot_id"]) < int(latest_boot["boot_id"]):
                raise HubError("telemetry_boot", "unknown older boot counter is rejected", 409)
            maximum = connection.execute("SELECT MAX(sequence) FROM telemetry WHERE device_id = ? AND boot_id = ?", key[:2]).fetchone()[0]
            if maximum is not None and body["sequence"] <= maximum:
                raise HubError("telemetry_sequence", "unknown older telemetry sequence is rejected", 409)
            if body["observed_at"] is not None:
                age = (datetime.fromisoformat(now.replace("Z", "+00:00")) - datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00"))).total_seconds()
                declared_uncertainty = body["clock_quality"]["uncertainty_ms"]
                uncertainty = declared_uncertainty / 1000 if declared_uncertainty is not None else 0
                if age > _MAX_AGE_S or age < -uncertainty:
                    raise HubError("telemetry_age", "telemetry timestamp is outside the bounded delivery window", 400)
            record_id = "telemetry_" + hashlib.sha256(canonical(key).encode("utf-8")).hexdigest()
            connection.execute("INSERT INTO telemetry VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (record_id, body["device_id"], body["site_id"], body["boot_id"], body["sequence"], payload, now, actor["subject"]))
            self._audit(connection, "telemetry.ingest", site_id=body["site_id"], device_id=body["device_id"], resource_id=record_id)
            row = connection.execute("SELECT * FROM telemetry WHERE id = ?", (record_id,)).fetchone()
            connection.commit()
        return self._telemetry_json(row)

    @public
    def list_telemetry(self, device_id: str | None = None, site_id: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        page_args(limit, offset)
        scope, args = self._scope_sql("site_id", "device_id")
        for name, value in (("device_id", device_id), ("site_id", site_id)):
            if value is not None:
                identifier(name, value)
                scope += f" AND {name} = ?"
                args.append(value)
        with self._workspace.connect(read_only=True) as connection:
            total = connection.execute("SELECT COUNT(*) FROM telemetry WHERE " + scope, args).fetchone()[0]
            rows = connection.execute("SELECT * FROM telemetry WHERE " + scope + " ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        return {"items": [self._telemetry_json(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    @public
    def list_audit(self, limit: int = 50, offset: int = 0) -> dict:
        self._require_role("admin")
        page_args(limit, offset)
        scope, args = self._scope_sql("site_id", "device_id")
        with self._workspace.connect(read_only=True) as connection:
            total = connection.execute("SELECT COUNT(*) FROM security_audit WHERE " + scope, args).fetchone()[0]
            rows = connection.execute("SELECT * FROM security_audit WHERE " + scope + " ORDER BY id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        items = [{key: row[key] for key in ("id", "action", "actor_subject", "auth_mode", "site_id", "device_id", "resource_id", "created_at")} | {"details": json.loads(row["details_json"])} for row in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}
