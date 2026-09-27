"""Claim an empty project-local verification cache, or reuse its owned marker."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
MARKER = ".poseidon-verification-owner.json"
OWNER = {"schema_version": 1, "owner": "poseidon-digital-verification"}


def marker_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate verification ownership field")
        result[key] = value
    return result


def prepare(root: Path, directory: Path) -> Path:
    root = root.resolve()
    directory = directory.absolute()
    if ".." in directory.parts or not directory.is_relative_to(root):
        raise ValueError("verification workspace must be inside this repository without traversal")
    relative = directory.relative_to(root)
    if len(relative.parts) < 2 or relative.parts[0] != ".local":
        raise ValueError("verification caches must use a named directory under .local")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or current.exists() and not current.is_dir():
            raise ValueError("verification workspace must not use symlinks or file parents")
    marker = directory / MARKER
    if marker.is_symlink():
        raise ValueError("verification ownership marker must not be a symlink")
    if directory.exists():
        if marker.exists():
            if not marker.is_file() or marker.stat().st_size > 1024:
                raise ValueError("invalid verification ownership marker")
            value = json.loads(marker.read_text(), object_pairs_hook=marker_object)
            if (type(value) is not dict or set(value) != set(OWNER)
                    or type(value.get("schema_version")) is not int or value["schema_version"] != 1
                    or type(value.get("owner")) is not str or value["owner"] != OWNER["owner"]):
                raise ValueError("verification workspace belongs to another owner or has a malformed marker")
            return directory
        if any(directory.iterdir()):
            raise ValueError("refusing nonempty unowned verification workspace")
    directory.mkdir(parents=True, exist_ok=True)
    with marker.open("x", encoding="utf-8") as handle:
        json.dump(OWNER, handle, sort_keys=True)
        handle.write("\n")
    return directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(f"Owned verification workspace: {prepare(ROOT, args.directory)}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"Cannot prepare verification workspace: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
