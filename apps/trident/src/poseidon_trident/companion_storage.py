"""Abort-only reconciliation of explicitly registered companion import files.

No scan adopts an orphan. Unknown directories, extra files, symlinks, hard links
and changed completed bytes are preserved and stop reconciliation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .errors import HubError


_STAGING_NAME = re.compile(r"companion-[a-f0-9]{32}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_NAMES = {"source.wav", "manifest.json"}


def _failure(message: str = "owned import files do not match their reservation") -> HubError:
    return HubError("companion_recovery_failed", message, 500)


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink


def package_spec(wav: bytes, manifest: bytes) -> dict:
    return {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in (("source.wav", wav), ("manifest.json", manifest))}


def checked_package(path: Path, specification: dict, *, complete: bool,
                    ownership: dict | None = None, expected_bytes: dict | None = None) -> dict:
    """Check full files or inode-bound exact expected prefixes; never remove.

    A short receiving file is not accepted by location alone. Its inode must
    have been checkpointed before writes and every byte must equal the reserved
    original prefix. Files checkpointed complete can never become short again.
    """
    try:
        directory = path.lstat()
        if not stat.S_ISDIR(directory.st_mode) or stat.S_ISLNK(directory.st_mode):
            raise _failure()
        if type(specification) is not dict or set(specification) != _NAMES:
            raise _failure("import reservation metadata is invalid")
        for expected in specification.values():
            if (type(expected) is not dict or set(expected) != {"bytes", "sha256"}
                    or type(expected["bytes"]) is not int or not 0 <= expected["bytes"] <= 64 * 1024 * 1024
                    or type(expected["sha256"]) is not str or not _SHA256.fullmatch(expected["sha256"])):
                raise _failure("import reservation metadata is invalid")
        if not complete and ownership is None:
            raise _failure("receiving files lack an ownership checkpoint")
        if ownership is not None:
            if (type(ownership) is not dict or set(ownership) != {"directory", "files"}
                    or type(ownership["directory"]) is not dict
                    or set(ownership["directory"]) != {"device", "inode"}
                    or type(ownership["files"]) is not dict or set(ownership["files"]) - _NAMES):
                raise _failure("import ownership checkpoint is incomplete")
            owned_directory = ownership["directory"]
            if (any(type(owned_directory[key]) is not int for key in ("device", "inode"))
                    or (directory.st_dev, directory.st_ino) != (owned_directory["device"], owned_directory["inode"])):
                raise _failure("staging directory identity changed")
            for item in ownership["files"].values():
                if (type(item) is not dict or set(item) != {"device", "inode", "complete"}
                        or type(item["device"]) is not int or type(item["inode"]) is not int or type(item["complete"]) is not bool):
                    raise _failure("file ownership checkpoint is invalid")
            if type(expected_bytes) is not dict or set(expected_bytes) != _NAMES:
                raise _failure("expected source bytes are missing")
            for name, raw in expected_bytes.items():
                if (type(raw) is not bytes or len(raw) != specification[name]["bytes"]
                        or hashlib.sha256(raw).hexdigest() != specification[name]["sha256"]):
                    raise _failure("reserved source bytes do not match their digest")
        entries = {entry.name: entry for entry in path.iterdir()}
        if set(entries) - _NAMES or (complete and set(entries) != _NAMES):
            raise _failure()
        if ownership is not None and set(entries) - set(ownership["files"]):
            raise _failure("staging file has no creation checkpoint")
        snapshots = {}
        for name, entry in entries.items():
            expected = specification[name]
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
                raise _failure()
            must_be_complete = complete
            if ownership is not None:
                owned = ownership["files"][name]
                if (info.st_dev, info.st_ino) != (owned["device"], owned["inode"]):
                    raise _failure("staging file identity changed")
                must_be_complete = must_be_complete or owned["complete"]
                if complete and not owned["complete"]:
                    raise _failure("published file lacks its completed-write checkpoint")
            if info.st_size > expected["bytes"] or (must_be_complete and info.st_size != expected["bytes"]):
                raise _failure()
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(entry, flags)
            try:
                if _identity(os.fstat(descriptor)) != _identity(info):
                    raise _failure()
                if must_be_complete or info.st_size == expected["bytes"] or ownership is not None:
                    digest = hashlib.sha256()
                    position = 0
                    while chunk := os.read(descriptor, 1024 * 1024):
                        if ownership is not None and chunk != expected_bytes[name][position:position + len(chunk)]:
                            raise _failure("receiving bytes differ from the reserved source prefix")
                        position += len(chunk)
                        if position > expected["bytes"]:
                            raise _failure("owned import file grew beyond its reserved size")
                        digest.update(chunk)
                    if position != info.st_size:
                        raise _failure()
                    if info.st_size == expected["bytes"] and digest.hexdigest() != expected["sha256"]:
                        raise _failure()
                if _identity(os.fstat(descriptor)) != _identity(info):
                    raise _failure()
            finally:
                os.close(descriptor)
            snapshots[name] = _identity(info)
        return {"directory": (directory.st_dev, directory.st_ino), "files": snapshots}
    except HubError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise _failure("cannot inspect owned import files") from exc


def _remove_checked(path: Path, snapshots: dict) -> None:
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != snapshots["directory"]:
            raise _failure()
        if {entry.name for entry in path.iterdir()} != set(snapshots["files"]):
            raise _failure()
        for name, expected in snapshots["files"].items():
            entry = path / name
            if _identity(entry.lstat()) != expected:
                raise _failure()
            entry.unlink()
        path.rmdir()
    except HubError:
        raise
    except OSError as exc:
        raise _failure("cannot remove owned incomplete import files") from exc


def intent_evidence(row) -> tuple[dict, dict]:
    ownership = json.loads(row["ownership_json"])
    expected = {"source.wav": row["wav_bytes"], "manifest.json": row["manifest_bytes"]}
    for name, maximum in (("source.wav", 8388608), ("manifest.json", 16384)):
        if type(expected[name]) is not bytes or not 1 <= len(expected[name]) <= maximum:
            raise _failure("reserved source BLOB is invalid or exceeds its cap")
    return ownership, expected


def capture_import_ownership(workspace, intent_id: str, event: str, path: Path, opened_info) -> None:
    """Checkpoint exclusive creation before writes and full completion after fsync."""
    try:
        with workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM companion_import_intents WHERE id = ? AND state = 'receiving'", (intent_id,)).fetchone()
            if row is None:
                raise _failure("receiving import reservation is missing")
            ownership, expected = intent_evidence(row)
            if type(ownership) is not dict or set(ownership) != {"directory", "files"} or type(ownership["files"]) is not dict:
                raise _failure("import ownership metadata is invalid")
            workspace._require_directory(workspace.staging_dir, "staging directory")
            package = workspace.staging_dir / row["staging_name"]
            if not _STAGING_NAME.fullmatch(row["staging_name"]):
                raise _failure()
            current = path.lstat()
            if _identity(current) != _identity(opened_info):
                raise _failure("newly opened import object changed before its checkpoint")
            if event == "directory":
                if path != package or not stat.S_ISDIR(current.st_mode) or ownership["directory"] is not None or ownership["files"]:
                    raise _failure("staging directory creation is not exclusive")
                ownership["directory"] = {"device": current.st_dev, "inode": current.st_ino}
            elif event in {"file_opened", "file_completed"}:
                if path.parent != package or path.name not in _NAMES or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                    raise _failure("staging file creation is not exclusive")
                if event == "file_opened":
                    if path.name in ownership["files"] or current.st_size != 0:
                        raise _failure("new staging file is not empty or already owned")
                    ownership["files"][path.name] = {"device": current.st_dev, "inode": current.st_ino, "complete": False}
                else:
                    registered = ownership["files"].get(path.name)
                    if registered is None or (registered["device"], registered["inode"]) != (current.st_dev, current.st_ino):
                        raise _failure("completed staging file lacks its creation checkpoint")
                    registered["complete"] = True
            else:
                raise _failure("unknown import ownership checkpoint")
            checked_package(package, json.loads(row["package_json"]), complete=False,
                            ownership=ownership, expected_bytes=expected)
            connection.execute("UPDATE companion_import_intents SET ownership_json = ? WHERE id = ?",
                               (json.dumps(ownership, sort_keys=True, separators=(",", ":")), intent_id))
            connection.commit()
    except HubError:
        raise
    except Exception as exc:
        raise _failure("cannot persist import ownership checkpoint") from exc


def abort_import_intent(workspace, intent_id: str) -> None:
    """Release a reservation only after all its owned artifacts are gone."""
    try:
        with workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM companion_import_intents WHERE id = ?", (intent_id,)).fetchone()
            if row is None:
                return  # Commit removed it atomically; never touch committed files.
            if (not _STAGING_NAME.fullmatch(row["staging_name"])
                    or not _IDENTIFIER.fullmatch(row["recording_id"])
                    or row["state"] not in {"receiving", "ready"}
                    or type(row["reserved_bytes"]) is not int or not 0 <= row["reserved_bytes"] <= 4194304):
                raise _failure("import reservation identity is invalid")
            workspace._require_directory(workspace.staging_dir, "staging directory")
            workspace._require_directory(workspace.recordings_dir, "recordings directory")
            if connection.execute("SELECT 1 FROM sources WHERE recording_id = ?", (row["recording_id"],)).fetchone():
                raise _failure("import reservation overlaps a catalogued source")
            specification = json.loads(row["package_json"])
            ownership, expected = intent_evidence(row)
            staging = workspace.staging_dir / row["staging_name"]
            published = workspace.recordings_dir / row["recording_id"]
            staged_exists = staging.exists() or staging.is_symlink()
            published_exists = published.exists() or published.is_symlink()
            if staged_exists and published_exists:
                raise _failure("import reservation has two competing packages")
            if published_exists and row["state"] != "ready":
                raise _failure("unvalidated reservation has an unexpected published package")
            if staged_exists:
                snapshot = checked_package(staging, specification, complete=row["state"] == "ready",
                                           ownership=ownership, expected_bytes=expected)
                _remove_checked(staging, snapshot)
            elif published_exists:
                snapshot = checked_package(published, specification, complete=True,
                                           ownership=ownership, expected_bytes=expected)
                _remove_checked(published, snapshot)
            connection.execute("DELETE FROM companion_import_intents WHERE id = ?", (intent_id,))
            connection.commit()
    except HubError:
        raise
    except Exception as exc:
        raise _failure("cannot reconcile the incomplete import reservation") from exc


def reconcile_import_intents(workspace) -> None:
    with workspace.connect(read_only=True) as connection:
        identities = [row[0] for row in connection.execute("SELECT id FROM companion_import_intents ORDER BY created_at, id")]
    for intent_id in identities:
        abort_import_intent(workspace, intent_id)
