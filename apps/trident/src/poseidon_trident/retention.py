"""Opt-in, explicit-plan deletion of newly admitted synthetic evidence only."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import secrets
import stat

from poseidon_proto.platform import canonical_json, parse_utc
from .errors import HubError
from .operating import document, put_document
from .platform import public, now_utc, identifier

CLASSES = ("media", "companions")
DEFAULT_POLICY = {"schema_version": "poseidon.retention-policy.v1",
                  "media": {"enabled": False, "max_age_s": 86400},
                  "companions": {"enabled": False, "max_age_s": 86400}}


def tombstone(connection, recording_id, data_class):
    row = connection.execute("SELECT document_json FROM retention_tombstones WHERE resource_id=? AND data_class=?", (recording_id, data_class)).fetchone()
    return json.loads(row[0]) if row else None


def expired_guard(connection, recording_id, *classes):
    if any(tombstone(connection, recording_id, c) for c in classes):
        raise HubError("evidence_expired", "evidence was deleted by an approved retention plan; metadata and hashes remain in the tombstone", 410)


def _file(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
            raise ValueError("not an exclusively owned regular file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_nlink) != (info.st_dev, info.st_ino, info.st_size, 1):
                raise ValueError("file identity changed")
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return {"sha256": digest, "bytes": info.st_size, "device": info.st_dev, "inode": info.st_ino}
    except (OSError, ValueError) as exc:
        raise HubError("retention_integrity", "known evidence file is missing, linked or changed; nothing authorized for deletion", 409) from exc


def validate_expired_import(workspace, connection, recording_id):
    """Validate deletion metadata, never present deleted bytes as complete evidence."""
    media, companions = (tombstone(connection, recording_id, c) for c in CLASSES)
    if not media and not companions:
        return False
    source = connection.execute("SELECT * FROM sources WHERE recording_id=?", (recording_id,)).fetchone()
    imported = connection.execute("SELECT * FROM recording_companion_imports WHERE recording_id=?", (recording_id,)).fetchone()
    if source is None:
        raise HubError("retention_integrity", "tombstone source is missing", 409)
    for t in (media, companions):
        if t and (t["recording_id"] != recording_id or t["source_sha256"] != source["wav_sha256"] or t["manifest_fingerprint"] != source["manifest_fingerprint"]):
            raise HubError("retention_integrity", "tombstone no longer matches catalog", 409)
    if companions:
        if imported is None or connection.execute("SELECT 1 FROM recording_companion_documents WHERE recording_id=?", (recording_id,)).fetchone() or bytes(imported["projection_bytes"]) != b"":
            raise HubError("retention_integrity", "expired companion bytes or metadata differ", 409)
        if imported["projection_sha256"] != companions["projection_sha256"]:
            raise HubError("retention_integrity", "expired projection digest differs", 409)
    elif imported:
        rows = connection.execute("SELECT * FROM recording_companion_documents WHERE recording_id=?", (recording_id,)).fetchall()
        from poseidon_proto.companion import DOCUMENT_ROLES
        if {row["role"] for row in rows} != set(DOCUMENT_ROLES):
            raise HubError("retention_integrity", "remaining companion role set differs", 409)
        for row in rows:
            if len(row["body"]) != row["byte_count"] or hashlib.sha256(row["body"]).hexdigest() != row["sha256"]:
                raise HubError("retention_integrity", "remaining companion bytes differ", 409)
        if hashlib.sha256(imported["projection_bytes"]).hexdigest() != imported["projection_sha256"]:
            raise HubError("retention_integrity", "remaining projection differs", 409)
    return True


class RetentionMixin:
    @public
    def get_retention_policy(self):
        self._require_role("admin")
        with self._workspace.connect(read_only=True) as connection:
            return document(connection, "retention-policy", DEFAULT_POLICY | {"eligible_after": {"media": None, "companions": None}})

    @public
    def put_retention_policy(self, body):
        actor = self._require_role("admin")
        if actor["auth_mode"] != "local_development_key":
            raise HubError("forbidden", "workspace retention policy requires local administrator", 403)
        if type(body) is not dict or set(body) != {"schema_version", *CLASSES} or body["schema_version"] != DEFAULT_POLICY["schema_version"]:
            raise HubError("invalid_request", "invalid retention policy schema", 400)
        for c in CLASSES:
            row = body[c]
            if type(row) is not dict or set(row) != {"enabled", "max_age_s"} or type(row["enabled"]) is not bool or type(row["max_age_s"]) is not int or not 1 <= row["max_age_s"] <= 315360000:
                raise HubError("invalid_request", "retention requires opt-in and bounded positive age seconds", 400)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = document(connection, "retention-policy")
            # Watermark never moves backwards. Earlier user/campaign evidence is ineligible.
            watermarks = {c: (prior["eligible_after"][c] if prior and prior[c]["enabled"] and body[c]["enabled"] else now_utc() if body[c]["enabled"] else None) for c in CLASSES}
            result = body | {"eligible_after": watermarks}
            put_document(connection, "retention-policy", result)
            self._audit(connection, "retention.policy", details=result)
            connection.commit()
        return result

    def _retention_candidates(self, connection, recording_ids, classes, policy):
        items = []
        now = datetime.now(timezone.utc)
        for recording_id in recording_ids:
            self._recording_access(recording_id)
            source = connection.execute("SELECT * FROM sources WHERE recording_id=?", (recording_id,)).fetchone()
            manifest = json.loads(source["manifest_json"])
            if manifest["provenance"] != "synthetic" or source["state"] != "available":
                raise HubError("retention_ineligible", "only completed synthetic evidence is eligible", 409)
            self._require_site(manifest["site_id"], manifest["device_id"])
            directory = self._workspace.recordings_dir / recording_id
            self._workspace._require_directory(directory, "recording directory")
            media_expired = tombstone(connection, recording_id, "media")
            if {p.name for p in directory.iterdir()} != ({"manifest.json"} if media_expired else {"manifest.json", "source.wav"}):
                raise HubError("retention_integrity", "recording contains unknown or missing files", 409)
            retained = connection.execute("SELECT * FROM recording_companion_imports WHERE recording_id=?", (recording_id,)).fetchone()
            if retained:
                if not validate_expired_import(self._workspace, connection, recording_id):
                    from .companion_integrity import validate_retained_import
                    validate_retained_import(self._workspace, connection, recording_id)
            for c in classes:
                if tombstone(connection, recording_id, c):
                    raise HubError("evidence_expired", "selected data class is already expired", 410)
                watermark = policy["eligible_after"][c]
                if not policy[c]["enabled"] or watermark is None or parse_utc(source["imported_at"]) <= parse_utc(watermark) or (now - parse_utc(source["imported_at"])).total_seconds() < policy[c]["max_age_s"]:
                    raise HubError("retention_ineligible", "disabled, pre-policy or unexpired evidence cannot be deleted", 409)
                item = {"recording_id": recording_id, "data_class": c, "site_id": manifest["site_id"], "device_id": manifest["device_id"],
                        "source_sha256": source["wav_sha256"], "manifest_fingerprint": source["manifest_fingerprint"], "files": [], "documents": []}
                if c == "media":
                    wav = _file(directory / "source.wav")
                    if wav["sha256"] != source["wav_sha256"] or wav["bytes"] != source["byte_count"]:
                        raise HubError("retention_integrity", "WAV differs from its catalog hash", 409)
                    manifest_file = _file(directory / "manifest.json")
                    from poseidon_proto import RecordingManifest
                    original = RecordingManifest.from_json((directory / "manifest.json").read_text())
                    if original.fingerprint() != source["manifest_fingerprint"]:
                        raise HubError("retention_integrity", "manifest differs from catalog", 409)
                    item["manifest_sha256"] = manifest_file["sha256"]
                    item["files"].append({"path": f"recordings/{recording_id}/source.wav", **wav})
                    video = connection.execute("SELECT * FROM videos WHERE recording_id=?", (recording_id,)).fetchone()
                    if video:
                        info = _file(self._workspace.videos_dir / video["filename"])
                        if info["sha256"] != video["sha256"] or info["bytes"] != video["byte_count"]:
                            raise HubError("retention_integrity", "video differs from catalog", 409)
                        item["files"].append({"path": "videos/" + video["filename"], **info})
                else:
                    if retained is None:
                        raise HubError("retention_ineligible", "no companion documents exist for this recording", 409)
                    rows = connection.execute("SELECT role,name,byte_count,sha256 FROM recording_companion_documents WHERE recording_id=? ORDER BY role", (recording_id,)).fetchall()
                    item["documents"] = [dict(row) for row in rows]
                    item["projection_sha256"] = retained["projection_sha256"]
                    item["projection_bytes"] = len(retained["projection_bytes"])
                items.append(item)
        return items

    @public
    def preview_retention(self, body):
        self._require_role("admin")
        if type(body) is not dict or set(body) != {"recording_ids", "data_classes"}:
            raise HubError("invalid_request", "preview requires exact recording_ids and data_classes", 400)
        ids, classes = body["recording_ids"], body["data_classes"]
        if type(ids) is not list or not 1 <= len(ids) <= 32 or type(classes) is not list or not classes or any(type(c) is not str or c not in CLASSES for c in classes):
            raise HubError("invalid_request", "invalid retention selection", 400)
        for value in ids:
            identifier("recording_id", value)
        if len(set(ids)) != len(ids) or len(set(classes)) != len(classes):
            raise HubError("invalid_request", "retention selection must be unique", 400)
        with self._submit_lock, self._video_lock, self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            policy = document(connection, "retention-policy", DEFAULT_POLICY | {"eligible_after": dict.fromkeys(CLASSES)})
            items = self._retention_candidates(connection, sorted(ids), sorted(classes), policy)
            plan = {"schema_version": "poseidon.retention-plan.v1", "plan_id": "plan_" + secrets.token_hex(16), "state": "preview",
                    "created_at": now_utc(), "approved_by": None, "approved_at": None, "executed_at": None,
                    "recording_ids": sorted(ids), "data_classes": sorted(classes), "items": items, "policy": policy}
            plan["sha256"] = hashlib.sha256(canonical_json(plan)).hexdigest()
            put_document(connection, plan["plan_id"], plan)
            for item in items:
                self._audit(connection, "retention.preview", site_id=item["site_id"], device_id=item["device_id"], resource_id=plan["plan_id"], details={"recording_id": item["recording_id"], "data_class": item["data_class"]})
            connection.commit()
        return plan

    def _plan(self, connection, plan_id):
        identifier("plan_id", plan_id)
        plan = document(connection, plan_id)
        if plan is None or plan.get("schema_version") != "poseidon.retention-plan.v1":
            raise HubError("plan_not_found", "retention plan was not found", 404)
        for item in plan["items"]:
            self._require_site(item["site_id"], item["device_id"])
            self._recording_access(item["recording_id"])
        return plan

    @public
    def approve_retention(self, plan_id, body):
        actor = self._require_role("admin")
        if type(body) is not dict or set(body) != {"sha256"}:
            raise HubError("invalid_request", "approval must bind the exact preview sha256", 400)
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan = self._plan(connection, plan_id)
            if plan["state"] != "preview" or body["sha256"] != plan["sha256"]:
                raise HubError("plan_conflict", "approval differs from preview", 409)
            plan |= {"state": "approved", "approved_by": actor["subject"], "approved_at": now_utc()}
            put_document(connection, plan_id, plan)
            for item in plan["items"]:
                self._audit(connection, "retention.approve", site_id=item["site_id"], device_id=item["device_id"], resource_id=plan_id, details={"sha256": plan["sha256"]})
            connection.commit()
        return plan

    @public
    def execute_retention(self, plan_id, body):
        self._require_role("admin")
        if type(body) is not dict or set(body) != {"sha256"}:
            raise HubError("invalid_request", "execution must bind the approved sha256", 400)
        with self._submit_lock, self._video_lock, self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan = self._plan(connection, plan_id)
            if plan["state"] != "approved" or body["sha256"] != plan["sha256"]:
                raise HubError("plan_conflict", "plan is not the approved deletion plan", 409)
            policy = document(connection, "retention-policy")
            if policy != plan["policy"]:
                raise HubError("plan_conflict", "retention policy changed after preview", 409)
            actual = self._retention_candidates(connection, plan["recording_ids"], plan["data_classes"], policy)
            if actual != plan["items"]:
                raise HubError("retention_integrity", "selected bytes or identities changed after preview", 409)
            # Persist the exact authorized intent before removing any bytes. A crash
            # before tombstones commit fails catalog validation, not silent repair.
            plan["state"] = "executing"
            put_document(connection, plan_id, plan)
            for item in actual:
                self._audit(connection, "retention.execute_intent", site_id=item["site_id"], device_id=item["device_id"], resource_id=plan_id, details={"sha256": plan["sha256"]})
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            for item in actual:
                for entry in item["files"]:
                    path = self._workspace.root / entry["path"]
                    if _file(path) != {key: entry[key] for key in ("sha256", "bytes", "device", "inode")}:
                        raise HubError("retention_integrity", "file identity changed during deletion", 409)
                    path.unlink()
                    self._sync_directory(path.parent)
                if item["data_class"] == "companions":
                    connection.execute("DELETE FROM recording_companion_documents WHERE recording_id=?", (item["recording_id"],))
                    connection.execute("UPDATE recording_companion_imports SET projection_bytes=? WHERE recording_id=?", (b"", item["recording_id"]))
                t = item | {"schema_version": "poseidon.retention-tombstone.v1", "plan_id": plan_id, "deleted_at": now_utc(), "state": "expired", "complete_evidence": False}
                connection.execute("INSERT INTO retention_tombstones VALUES (?,?,?,?)", (item["recording_id"], item["data_class"], plan_id, canonical_json(t).decode()))
                self._audit(connection, "retention.delete", site_id=item["site_id"], device_id=item["device_id"], resource_id=item["recording_id"], details={"plan_id": plan_id, "data_class": item["data_class"], "tombstone_sha256": hashlib.sha256(canonical_json(t)).hexdigest()})
            plan |= {"state": "executed", "executed_at": now_utc()}
            put_document(connection, plan_id, plan)
            connection.commit()
        return plan

    @public
    def get_retention_tombstones(self, recording_id):
        self._recording_access(recording_id)
        with self._workspace.connect(read_only=True) as connection:
            items = [t for c in CLASSES if (t := tombstone(connection, recording_id, c))]
        return {"recording_id": recording_id, "items": items}
