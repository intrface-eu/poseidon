#!/usr/bin/env python3
"""Fetch optional purchased-part evidence into a private, ignored cache."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "hardware/.vendor-cache"
REGISTRY = ROOT / "hardware/vendor-sources.json"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Unsafe vendor cache path")
    target = CACHE / path
    if CACHE.is_symlink() or any((CACHE / Path(*path.parts[:i])).is_symlink()
                                 for i in range(1, len(path.parts) + 1)):
        raise ValueError("Symlink vendor cache path")
    return target


def verified_bytes(record, offline=False):
    if record["license_status"] != "supplier_redistribution_unverified":
        raise ValueError("Unreviewed supplier redistribution status")
    target = safe_path(record["path"])
    if target.is_file():
        data = target.read_bytes()
        if sha256(data) == record["sha256"]:
            return data
        raise ValueError("Vendor cache hash mismatch: " + record["path"])
    if offline:
        raise FileNotFoundError("Vendor file not cached: " + record["path"])
    if "archive" in record:
        archive = next(r for r in json.loads(REGISTRY.read_text())["files"] if r["path"] == record["archive"])
        with zipfile.ZipFile(safe_path(archive["path"])) as z:
            data = z.read(record["archive_member"])
    else:
        with urllib.request.urlopen(record["url"], timeout=60) as response:
            data = response.read()
    if sha256(data) != record["sha256"]:
        raise ValueError("Downloaded vendor hash mismatch: " + record["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Check the cached copies without networking")
    parser.add_argument("--only", action="append", help="Select a cache-relative file (repeatable)")
    args = parser.parse_args()
    files = json.loads(REGISTRY.read_text())["files"]
    selected = set(args.only or (r["path"] for r in files))
    unknown = selected - {r["path"] for r in files}
    if unknown:
        parser.error("Unknown vendor source path: " + ", ".join(sorted(unknown)))
    needed = set(selected)
    for r in files:
        if r["path"] in selected and "archive" in r:
            needed.add(r["archive"])
    for record in files:
        if record["path"] in needed:
            verified_bytes(record, args.offline)
            print("Verified " + record["path"])


if __name__ == "__main__":
    main()
