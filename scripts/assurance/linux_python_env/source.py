"""Copy only an explicit, hash-frozen full Python source/fixture closure.

This module never discovers host home, keys, caches or extra import sources. A
controller-reviewed manifest is input, not an authorization to start a VM.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

MAX_FILES = 30000
MAX_FILE_BYTES = 128 * 1024**2
MAX_TOTAL_BYTES = 2 * 1024**3
TOPS = frozenset({"apps", "libs", "firmware", "contracts", "tests", "scripts", "ops", "research", "docs", "hardware", ".github", ".taskmaster"})
ROOT_FILES = frozenset({"Makefile", "pyproject.toml", ".gitignore", "README.md", "PRODUCT.md", "DESIGN.md", "HARDWARE.md", "SECURITY.md"})
FORBIDDEN = frozenset({".git", ".local", ".venv", "node_modules", "__pycache__", ".next", ".pio", ".cache", ".ssh", ".env", ".DS_Store"})


class SourceError(ValueError):
    pass


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            result.update(chunk)
    return result.hexdigest()


def strict_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SourceError("duplicate manifest JSON field")
            result[key] = value
        return result

    def invalid(_):
        raise SourceError("nonfinite manifest JSON")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    if type(value) is not dict:
        raise SourceError("manifest root must be an object")
    return value


def safe_name(name: str) -> str:
    if type(name) is not str:
        raise SourceError("source path must be text")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name or any(ord(c) < 32 for c in name):
        raise SourceError("noncanonical or escaping source path")
    if path.parts[0] not in TOPS and name not in ROOT_FILES:
        raise SourceError("source path is outside the reviewed project closure")
    if any(part in FORBIDDEN or part.startswith(".env.") for part in path.parts) or path.suffix in {".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx"}:
        raise SourceError("cache, credentials or private path cannot be transferred")
    if path.parts[0] == ".taskmaster" and (len(path.parts) < 3 or path.parts[1] != "tasks"):
        raise SourceError("only frozen Taskmaster task inputs may be transferred")
    return name


def validate_manifest(value: dict) -> dict:
    if set(value) != {"schema_version", "files", "required_files", "coverage_roots"} or value["schema_version"] != "poseidon.linux-python-sources.v1":
        raise SourceError("invalid frozen-source manifest schema")
    files = value["files"]
    if type(files) is not dict or not 1 <= len(files) <= MAX_FILES:
        raise SourceError("full-source manifest needs a bounded nonempty file map")
    total = 0
    for name, item in files.items():
        safe_name(name)
        if type(item) is not dict or set(item) != {"sha256", "size"}:
            raise SourceError("each source needs exact SHA256 and size")
        if type(item["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise SourceError("invalid source hash")
        if type(item["size"]) is not int or not 0 <= item["size"] <= MAX_FILE_BYTES:
            raise SourceError("source exceeds per-file size bound")
        total += item["size"]
    if total > MAX_TOTAL_BYTES:
        raise SourceError("full-source closure exceeds total bound")
    for field in ("required_files", "coverage_roots"):
        names = value[field]
        if type(names) is not list or not names or len(names) != len(set(names)):
            raise SourceError(f"{field} must be a nonempty unique list")
        for name in names:
            safe_name(name)
    if not set(value["required_files"]) <= set(files):
        raise SourceError("missing required source/import/fixture file")
    if not all(any(name == root or name.startswith(root + "/") for root in value["coverage_roots"]) for name in files):
        raise SourceError("file is outside declared coverage roots")
    return value


def read_file(root: Path, name: str, expected: dict) -> bytes:
    safe_name(name)
    path = root / name
    if root.resolve() != root or path.resolve() != path:
        raise SourceError("source root/path must not traverse symlinks")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != expected["size"]:
        raise SourceError(f"source is not the frozen regular file: {name}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino, info.st_size) != (before.st_dev, before.st_ino, before.st_size):
            raise SourceError(f"source changed while opening: {name}")
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) != expected["size"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise SourceError(f"source hash changed: {name}")
    return raw


def verify(root: Path, manifest: dict, *, exact: bool = True) -> None:
    validate_manifest(manifest)
    for name, item in manifest["files"].items():
        read_file(root, name, item)
    if exact:
        actual = set()
        for coverage in manifest["coverage_roots"]:
            path = root / coverage
            if path.is_file():
                actual.add(coverage)
                continue
            if not path.is_dir() or path.is_symlink():
                raise SourceError(f"missing/nonregular coverage root: {coverage}")
            for directory, dirs, names in os.walk(path, followlinks=False):
                for part in dirs:
                    if (Path(directory) / part).is_symlink():
                        raise SourceError("symlink in source closure")
                for part in names:
                    name = (Path(directory) / part).relative_to(root).as_posix()
                    safe_name(name)
                    actual.add(name)
        if actual != set(manifest["files"]):
            raise SourceError(f"source closure membership changed; extra={sorted(actual-set(manifest['files']))[:8]}, missing={sorted(set(manifest['files'])-actual)[:8]}")


def freeze(root: Path, manifest: dict, destination: Path, archive: Path) -> dict:
    """Stage a new copy and deterministic tar; preserve partial failure artifacts."""
    validate_manifest(manifest)
    if destination.exists() or destination.is_symlink() or archive.exists() or archive.is_symlink():
        raise SourceError("staging and archive paths must be new")
    if destination.parent.resolve() != destination.parent or archive.parent.resolve() != archive.parent:
        raise SourceError("staging/archive parents must not traverse symlinks")
    # Working source may contain ignored caches, but only exact listed bytes are
    # read/copied. The staged closure must be exact, including every import root.
    verify(root, manifest, exact=False)
    destination.mkdir(mode=0o700)
    with archive.open("xb") as output, tarfile.open(fileobj=output, mode="w") as bundle:
        for name, expected in sorted(manifest["files"].items()):
            raw = read_file(root, name, expected)
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = 0o644
            member.uid = member.gid = member.mtime = 0
            bundle.addfile(member, io.BytesIO(raw))
    verify(root, manifest, exact=False)
    verify(destination, manifest)
    return {"files": len(manifest["files"]), "archive_sha256": sha256(archive), "source_hashes_preserved": True}


def unpack(archive: Path, destination: Path, manifest: dict) -> None:
    """Extract only the exact regular members, not tar links/devices or extras."""
    validate_manifest(manifest)
    if destination.exists() or destination.is_symlink() or destination.parent.resolve() != destination.parent:
        raise SourceError("extraction requires a new non-symlink destination")
    destination.mkdir(mode=0o700)
    seen = set()
    with tarfile.open(archive, "r:") as bundle:
        for member in bundle:
            name = safe_name(member.name)
            if not member.isfile() or name in seen or name not in manifest["files"] or member.size != manifest["files"][name]["size"]:
                raise SourceError("archive contains nonregular, duplicate, extra or resized member")
            stream = bundle.extractfile(member)
            if stream is None:
                raise SourceError("archive member is unreadable")
            with stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            if hashlib.sha256(raw).hexdigest() != manifest["files"][name]["sha256"]:
                raise SourceError("archive member hash differs from frozen source")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(raw)
            seen.add(name)
    if seen != set(manifest["files"]):
        raise SourceError("archive is missing frozen source members")
    verify(destination, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("freeze", "unpack", "verify"), default="freeze")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--archive-sha256")
    args = parser.parse_args()
    if sha256(args.manifest) != args.manifest_sha256:
        raise SourceError("manifest differs from the parent-frozen digest")
    manifest = strict_json(args.manifest.read_bytes())
    if args.action == "freeze":
        if args.source is None or args.destination is None or args.archive is None:
            parser.error("freeze needs source, destination and archive")
        result = freeze(args.source.resolve(), manifest, args.destination, args.archive)
    elif args.action == "unpack":
        if args.archive is None or args.destination is None or not args.archive_sha256:
            parser.error("unpack needs archive, archive SHA256 and destination")
        if sha256(args.archive) != args.archive_sha256:
            raise SourceError("source archive differs from parent-frozen transfer hash")
        unpack(args.archive, args.destination, manifest)
        result = {"state": "unpacked-exact-frozen-sources", "files": len(manifest["files"])}
    else:
        if args.source is None:
            parser.error("verify needs source")
        verify(args.source.resolve(), manifest)
        result = {"state": "exact-frozen-sources-verified", "files": len(manifest["files"])}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
