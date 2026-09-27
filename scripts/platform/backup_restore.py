"""Offline private workspace backup/restore. Never overwrites a destination."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat

from poseidon_trident import Hub

FILES = {"hub.sqlite3", "evidence.sqlite3", "access.token"}
DIRECTORIES = {"recordings", "videos"}
MANIFEST = "backup-manifest.json"


def _real(path: Path, *, directory=False):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError("backup paths must be real directories and regular files")
    return info


def _private_destination(path: Path):
    _real(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        raise ValueError("destination must not already exist")
    path.mkdir(mode=0o700)


def _digest(path):
    _real(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root):
    result = []
    for fixed in sorted(FILES):
        _real(root / fixed)
        result.append(Path(fixed))
    for fixed in sorted(DIRECTORIES):
        directory = root / fixed
        _real(directory, directory=True)
        for parent, dirs, files in os.walk(directory, followlinks=False):
            for name in dirs:
                _real(Path(parent) / name, directory=True)
            for name in files:
                path = Path(parent) / name
                _real(path)
                result.append(path.relative_to(root))
    return sorted(result)


def _copy_private(source, destination):
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Source is an exclusively owned, validated private workspace/backup.
    with source.open("rb") as src, destination.open("xb") as dst:
        os.chmod(destination, 0o600)
        shutil.copyfileobj(src, dst, 1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())


def backup(source: Path, destination: Path):
    source, destination = Path(source).absolute(), Path(destination).absolute()
    _real(source, directory=True)
    if destination == source or source in destination.parents:
        raise ValueError("backup must be outside the workspace")
    # Hub refuses a workspace owned by a running service. It also validates
    # both database identities and immutable source paths before copying.
    with Hub(source) as hub:
        paths = _files(source)
        _private_destination(destination)
        for name in DIRECTORIES:
            (destination / name).mkdir(mode=0o700)
        for relative in paths:
            if str(relative) in {"hub.sqlite3", "evidence.sqlite3"}:
                target = destination / relative
                with closing(sqlite3.connect((source / relative).as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
                os.chmod(target, 0o600)
            else:
                _copy_private(source / relative, destination / relative)
        entries = [{"path": str(path), "size_bytes": (destination / path).stat().st_size, "sha256": _digest(destination / path)} for path in paths]
        manifest = {"schema_version": "poseidon.workspace-backup.v1", "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "contains_credentials": True, "encryption": "none_private_local_storage_required", "files": entries}
        with (destination / MANIFEST).open("x") as stream:
            os.chmod(destination / MANIFEST, 0o600)
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return {"files": len(entries), "bytes": sum(item["size_bytes"] for item in entries), "credentials": "included privately; rotate after an incident"}


def verify(source: Path):
    source = Path(source).absolute()
    info = _real(source, directory=True)
    if info.st_mode & 0o077:
        raise ValueError("backup directory must be private (mode 0700)")
    _real(source / MANIFEST)
    if (source / MANIFEST).stat().st_size > 16 * 1024 * 1024:
        raise ValueError("backup manifest exceeds the local tooling limit")
    manifest = json.loads((source / MANIFEST).read_text())
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "poseidon.workspace-backup.v1" or manifest.get("contains_credentials") is not True or type(manifest.get("files")) is not list:
        raise ValueError("unsupported backup manifest")
    actual = {str(path) for path in _files(source)}
    if {entry.get("path") for entry in manifest["files"] if isinstance(entry, dict)} != actual or len(manifest["files"]) != len(actual):
        raise ValueError("backup file catalog differs from its manifest")
    allowed_root = FILES | DIRECTORIES | {MANIFEST}
    if {path.name for path in source.iterdir()} != allowed_root:
        raise ValueError("backup contains unknown root entries")
    for entry in manifest["files"]:
        if set(entry) != {"path", "size_bytes", "sha256"}:
            raise ValueError("unexpected backup catalog fields")
        path = source / entry["path"]
        if type(entry["size_bytes"]) is not int or path.stat().st_size != entry["size_bytes"] or _digest(path) != entry["sha256"]:
            raise ValueError("backup content integrity check failed")
    return manifest


def restore(source: Path, destination: Path):
    source, destination = Path(source).absolute(), Path(destination).absolute()
    manifest = verify(source)
    if destination == source or source in destination.parents:
        raise ValueError("restore destination must be outside the backup")
    _private_destination(destination)
    for name in DIRECTORIES:
        (destination / name).mkdir(mode=0o700)
    for entry in manifest["files"]:
        _copy_private(source / entry["path"], destination / entry["path"])
    (destination / ".staging").mkdir(mode=0o700)
    # Existing-format initialization validates schema, source digests, jobs,
    # recording/video paths and ownership without starting application services.
    with Hub(destination) as hub:
        status = hub.status()
    return {"files": len(manifest["files"]), "recordings": status["recordings"], "events": status["events"], "credentials": "restored; rotate before reuse after an incident"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "verify", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    args = parser.parse_args()
    if args.action != "verify" and args.destination is None:
        parser.error("backup/restore needs a new destination path")
    if args.action == "verify":
        manifest = verify(args.source)
        print(json.dumps({"files": len(manifest["files"]), "state": "integrity_checked_not_authenticated"}))
    else:
        print(json.dumps((backup if args.action == "backup" else restore)(args.source, args.destination)))


if __name__ == "__main__":
    main()
