"""Signed artifacts and crash-persistent local simulated update targets.

No artifact is executed, installed, flashed or sent to a device. This module
checks real signatures/bytes, and keeps a transactional simulated trial state.
"""
from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3

from poseidon_proto.models import ModelValidationError
from poseidon_proto.platform import canonical_json, parse_utc, validate_contract
from poseidon_proto.signing import signing_bytes  # Compatibility export for existing local callers.

from .errors import HubError

MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_TARGETS = 100
MAX_KEYS = 100
MAX_HISTORY = 1000
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX = re.compile(r"^[a-f0-9]{64}$")
_TARGET_FIELDS = ("id", "device_id", "site_id", "target_kind", "hardware_revision", "simulation", "state", "current_sha256", "current_version", "security_floor", "highest_sequence", "staged_manifest_id", "trial_manifest_id", "previous_sha256", "revision", "updated_at")
_KEY_FIELDS = ("id", "site_ids", "public_key_hex", "created_at", "revoked_at")


def _error(code: str, message: str, status: int = 400):
    raise HubError(code, message, status)


def _identifier(value, name="id"):
    if type(value) is not str or not _ID.fullmatch(value):
        _error("invalid_lifecycle", f"{name} must be a safe identifier")
    return value


def _hash(value):
    if type(value) is not str or not _HEX.fullmatch(value):
        _error("invalid_lifecycle", "SHA256/public key must be 64 lowercase hex characters")
    return value


def _exact(body, fields):
    if type(body) is not dict or set(body) != set(fields):
        _error("invalid_lifecycle", "request fields do not match the lifecycle contract")


def _page(items, limit):
    return {"items": items, "total": len(items), "limit": limit, "offset": 0}


def sign_test_manifest(payload: dict, key_id: str, private_key) -> dict:
    """Helper for offline ephemeral-key tests; no production signer or key store."""
    manifest = {"payload": payload, "signature": {"algorithm": "Ed25519", "key_id": key_id, "canonicalization": "poseidon-json-v1", "value": base64.b64encode(private_key.sign(signing_bytes(payload, key_id))).decode("ascii")}}
    return validate_contract("signed-manifest", manifest)


class LocalLifecycle:
    def __init__(self, hub, *, now=None):
        self.hub = hub
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _timestamp(self):
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            _error("clock_unavailable", "lifecycle requires a timezone-aware server clock", 409)
        return now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _authorize(identity, *, write=False, root=False, site=None):
        if identity.get("role") not in ({"admin"} if write else {"admin", "reviewer", "viewer"}):
            _error("forbidden", "identity cannot access local lifecycle", 403)
        local = identity.get("auth_mode") == "local_development_key"
        if root and not local:
            _error("forbidden", "trust-root mutation requires the local development key", 403)
        if site is not None and not local and site not in identity.get("site_ids", []):
            _error("not_found", "local lifecycle record not found", 404)

    @contextmanager
    def _transaction(self, *, write=False):
        with self.hub._workspace.operation(), self.hub._workspace.connect(read_only=not write) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
                connection.commit()
            except sqlite3.Error as exc:
                connection.rollback()
                raise HubError("lifecycle_unavailable", "local lifecycle store is unavailable", 500) from exc
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _load(connection, key):
        row = connection.execute("SELECT document_json FROM platform_documents WHERE id=?", (key,)).fetchone()
        if row is None:
            _error("not_found", "local lifecycle record not found", 404)
        return json.loads(row[0])

    @staticmethod
    def _put(connection, key, value, *, create=False):
        if create:
            if connection.execute("SELECT 1 FROM platform_documents WHERE id=?", (key,)).fetchone():
                _error("identity_conflict", "local lifecycle identity already exists", 409)
            connection.execute("INSERT INTO platform_documents(id,document_json) VALUES (?,?)", (key, canonical_json(value).decode()))
        else:
            connection.execute("UPDATE platform_documents SET document_json=? WHERE id=?", (canonical_json(value).decode(), key))
        if key.startswith("lifecycle:target:"):
            event = value["history"][-1]
            audit = ("lifecycle." + event["action"], event["actor_subject"], event["auth_mode"], value["site_id"], value["device_id"], value["id"], event["created_at"], canonical_json(event["details"]).decode())
        else:
            revoked = value["revoked_at"] is not None
            audit = ("lifecycle.key_revoke" if revoked else "lifecycle.key_add", value.get("revoked_by", value["actor_subject"]), "local_development_key", None, None, value["id"], value["revoked_at"] if revoked else value["created_at"], "{}")
        connection.execute("INSERT INTO security_audit(action,actor_subject,auth_mode,site_id,device_id,resource_id,created_at,details_json) VALUES (?,?,?,?,?,?,?,?)", audit)

    @staticmethod
    def _all(connection, prefix):
        return [json.loads(row[0]) for row in connection.execute("SELECT document_json FROM platform_documents WHERE id LIKE ? ORDER BY id", (prefix + "%",)).fetchall()]

    def _target(self, connection, identity, target_id, *, write=False):
        _identifier(target_id)
        target = self._load(connection, "lifecycle:target:" + target_id)
        self._authorize(identity, write=write, site=target["site_id"])
        return target

    @staticmethod
    def _public_target(target):
        return {key: target[key] for key in _TARGET_FIELDS}

    def _device(self, identity, device_id):
        device = self.hub.get_device(device_id)
        self._authorize(identity, site=device["site_id"])
        if device["revoked_at"] is not None:
            _error("device_revoked", "registered device is revoked", 409)
        if device["source_kind"] not in ("synthetic", "bench") or device["kind"] not in ("hub", "reef"):
            _error("simulation_only", "local targets require a synthetic/bench hub or reef registry entry", 403)
        return device

    def list_keys(self, identity):
        self._authorize(identity)
        with self._transaction() as connection:
            keys = self._all(connection, "lifecycle:key:")
        items = [{field: key[field] for field in _KEY_FIELDS} for key in keys if identity["auth_mode"] == "local_development_key" or set(key["site_ids"]) & set(identity["site_ids"])]
        return _page(items, MAX_KEYS)

    def add_key(self, identity, body):
        self._authorize(identity, write=True, root=True)
        _exact(body, ("id", "site_ids", "public_key_hex"))
        _identifier(body["id"])
        _hash(body["public_key_hex"])
        if type(body["site_ids"]) is not list or not 1 <= len(body["site_ids"]) <= 100:
            _error("invalid_lifecycle", "key needs 1..100 unique site IDs")
        for site in body["site_ids"]:
            _identifier(site, "site_id")
        if len(set(body["site_ids"])) != len(body["site_ids"]):
            _error("invalid_lifecycle", "key site IDs must be unique")
        # Construct via the maintained crypto implementation, not custom crypto.
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(body["public_key_hex"]))
        key = {**body, "created_at": self._timestamp(), "revoked_at": None, "actor_subject": identity["subject"]}
        with self._transaction(write=True) as connection:
            if len(self._all(connection, "lifecycle:key:")) >= MAX_KEYS:
                _error("lifecycle_capacity", "local trust key capacity reached", 409)
            self._put(connection, "lifecycle:key:" + body["id"], key, create=True)
        return {field: key[field] for field in _KEY_FIELDS}

    def revoke_key(self, identity, key_id):
        self._authorize(identity, write=True, root=True)
        _identifier(key_id)
        with self._transaction(write=True) as connection:
            key = self._load(connection, "lifecycle:key:" + key_id)
            if key["revoked_at"] is None:
                key["revoked_at"] = self._timestamp()
                key["revoked_by"] = identity["subject"]
                self._put(connection, "lifecycle:key:" + key_id, key)
        return {field: key[field] for field in _KEY_FIELDS}

    def list_targets(self, identity):
        self._authorize(identity)
        with self._transaction() as connection:
            targets = self._all(connection, "lifecycle:target:")
        return _page([self._public_target(target) for target in targets if identity["auth_mode"] == "local_development_key" or target["site_id"] in identity["site_ids"]], MAX_TARGETS)

    def get_target(self, identity, target_id):
        self._authorize(identity)
        with self._transaction() as connection:
            return self._public_target(self._target(connection, identity, target_id))

    def _audit(self, target, identity, action, details):
        if len(target["history"]) >= MAX_HISTORY:
            _error("lifecycle_capacity", "local target transition history capacity reached", 409)
        target["revision"] += 1
        target["updated_at"] = self._timestamp()
        target["history"].append({"revision": target["revision"], "action": action, "actor_subject": identity["subject"], "auth_mode": identity["auth_mode"], "created_at": target["updated_at"], "details": details})

    def create_target(self, identity, body):
        self._authorize(identity, write=True)
        _exact(body, ("id", "device_id", "simulation", "initial_sha256", "initial_version", "security_floor"))
        _identifier(body["id"])
        _identifier(body["device_id"], "device_id")
        _identifier(body["initial_version"], "initial_version")
        _hash(body["initial_sha256"])
        if body["simulation"] is not True:
            _error("simulation_only", "only local simulated targets are supported", 403)
        if type(body["security_floor"]) is not int or not 0 <= body["security_floor"] <= 2**32 - 1:
            _error("invalid_lifecycle", "security floor must be uint32")
        with self._transaction(write=True) as connection:
            device = self._device(identity, body["device_id"])
            self._authorize(identity, write=True, site=device["site_id"])
            targets = self._all(connection, "lifecycle:target:")
            if len(targets) >= MAX_TARGETS or any(t["device_id"] == device["id"] for t in targets):
                _error("lifecycle_capacity", "device already has a local target or target capacity reached", 409)
            target = {"id": body["id"], "device_id": device["id"], "site_id": device["site_id"], "target_kind": device["kind"], "hardware_revision": device["hardware_revision"], "simulation": True, "state": "idle", "current_sha256": body["initial_sha256"], "current_version": body["initial_version"], "current_security_version": body["security_floor"], "security_floor": body["security_floor"], "highest_sequence": -1, "staged_manifest_id": None, "trial_manifest_id": None, "previous_sha256": None, "previous": None, "staged": None, "trial": None, "history": [], "revision": 0, "updated_at": self._timestamp()}
            self._audit(target, identity, "create", {"baseline": "operator_declared_local_simulation", "sha256": body["initial_sha256"]})
            self._put(connection, "lifecycle:target:" + body["id"], target, create=True)
        return self._public_target(target)

    def _verify(self, connection, target, manifest, artifact):
        try:
            manifest = validate_contract("signed-manifest", manifest)
        except ModelValidationError as exc:
            raise HubError("invalid_manifest", str(exc), 400) from exc
        payload, signature = manifest["payload"], manifest["signature"]
        key = self._load(connection, "lifecycle:key:" + signature["key_id"])
        if key["revoked_at"] is not None or target["site_id"] not in key["site_ids"]:
            _error("untrusted_manifest", "signing key is revoked or outside target site", 403)
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            signature_bytes = base64.b64decode(signature["value"], validate=True)
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"])).verify(signature_bytes, signing_bytes(payload, signature["key_id"]))
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise HubError("invalid_signature", "artifact signature verification failed", 403) from exc
        now = parse_utc(self._timestamp())
        if now < parse_utc(payload["issued_at"]) or now >= parse_utc(payload["expires_at"]):
            _error("manifest_expired", "manifest is not within its validity interval", 409)
        if payload["target_kind"] != target["target_kind"] or payload["hardware_revision"] != target["hardware_revision"]:
            _error("incompatible_manifest", "manifest does not match the local target", 409)
        if payload["security_version"] < target["security_floor"]:
            _error("security_floor", "manifest is below the security floor", 409)
        if not 1 <= len(artifact) <= MAX_ARTIFACT_BYTES or len(artifact) != payload["artifact_size_bytes"] or hashlib.sha256(artifact).hexdigest() != payload["artifact_sha256"]:
            _error("artifact_mismatch", "artifact hash or byte length does not match signed metadata", 400)
        return manifest

    @staticmethod
    def _artifact(value):
        if type(value) is not str or len(value) > 4 * ((MAX_ARTIFACT_BYTES + 2) // 3):
            _error("artifact_too_large", "local artifact exceeds the 1 MiB software limit", 413)
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HubError("invalid_artifact", "artifact must be strict base64", 400) from exc

    def stage(self, identity, target_id, body):
        self._authorize(identity, write=True)
        _exact(body, ("manifest", "artifact_base64"))
        artifact = self._artifact(body["artifact_base64"])
        with self._transaction(write=True) as connection:
            target = self._target(connection, identity, target_id, write=True)
            self._device(identity, target["device_id"])
            if target["state"] in ("staged", "trial"):
                _error("transition_conflict", "finish or recover the existing stage/trial first", 409)
            manifest = self._verify(connection, target, body["manifest"], artifact)
            payload = manifest["payload"]
            if payload["sequence"] <= target["highest_sequence"]:
                _error("manifest_replay", "manifest sequence was already consumed", 409)
            if payload["previous_sha256"] != target["current_sha256"]:
                _error("base_mismatch", "manifest requires a different previous image", 409)
            target["highest_sequence"] = payload["sequence"]
            target["staged"] = {"manifest": manifest, "artifact_base64": body["artifact_base64"]}
            target["staged_manifest_id"] = payload["id"]
            target["state"] = "staged"
            self._audit(target, identity, "stage", {"manifest_id": payload["id"], "artifact_sha256": payload["artifact_sha256"], "sequence": payload["sequence"]})
            self._put(connection, "lifecycle:target:" + target_id, target)
        return self._public_target(target)

    def transition(self, identity, target_id, action):
        self._authorize(identity, write=True)
        if action not in ("activate", "confirm", "rollback", "recover"):
            _error("invalid_transition", "unknown local lifecycle transition")
        with self._transaction(write=True) as connection:
            target = self._target(connection, identity, target_id, write=True)
            # Revoked devices cannot advance an update. Recovery is still local
            # state cleanup, not a command to a revoked physical device.
            if action in ("activate", "confirm"):
                self._device(identity, target["device_id"])
            if action == "activate":
                if target["state"] != "staged":
                    _error("transition_conflict", "activate requires a staged artifact", 409)
                staged = target["staged"]
                self._verify(connection, target, staged["manifest"], self._artifact(staged["artifact_base64"]))
                target["previous"] = {"sha256": target["current_sha256"], "version": target["current_version"], "security_version": target["current_security_version"]}
                target["previous_sha256"] = target["current_sha256"]
                target["trial"] = staged
                target["trial_manifest_id"] = target["staged_manifest_id"]
                target["staged"] = None
                target["staged_manifest_id"] = None
                target["state"] = "trial"
            elif action == "confirm":
                if target["state"] != "trial":
                    _error("transition_conflict", "confirm requires an unconfirmed local trial", 409)
                trial = target["trial"]
                manifest = self._verify(connection, target, trial["manifest"], self._artifact(trial["artifact_base64"]))
                payload = manifest["payload"]
                target["current_sha256"] = payload["artifact_sha256"]
                target["current_version"] = payload["version"]
                target["current_security_version"] = payload["security_version"]
                target["security_floor"] = max(target["security_floor"], payload["security_version"])
                target["trial"] = None
                target["trial_manifest_id"] = None
                target["state"] = "healthy"
            else:
                if target["state"] not in ("staged", "trial", "healthy"):
                    _error("transition_conflict", "nothing staged or tried to recover", 409)
                if target["state"] == "staged":
                    target["staged"] = None
                    target["staged_manifest_id"] = None
                else:
                    previous = target["previous"]
                    if previous is None or previous["security_version"] < target["security_floor"]:
                        _error("security_floor", "previous baseline cannot satisfy the security floor", 409)
                    target["current_sha256"] = previous["sha256"]
                    target["current_version"] = previous["version"]
                    target["current_security_version"] = previous["security_version"]
                target["trial"] = None
                target["trial_manifest_id"] = None
                target["state"] = "rolled_back"
            self._audit(target, identity, action, {"state": target["state"], "health_evidence": "operator_declared_local_test" if action == "confirm" else None})
            self._put(connection, "lifecycle:target:" + target_id, target)
        return self._public_target(target)

    def history(self, identity, target_id):
        self._authorize(identity)
        with self._transaction() as connection:
            target = self._target(connection, identity, target_id)
            return _page(target["history"], MAX_HISTORY)
