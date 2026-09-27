#!/usr/bin/env python3
"""Bounded local fixed-pattern scan, including untracked source/config files.

Matches are never printed. A clean result covers these patterns and readable text
only; it is not proof that the repository contains no possible secrets.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path("scripts/assurance/secrets-allowlist.json")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 30000
# Vendor snapshots that once carried third-party credential-like values were
# redacted and rehashed in hardware run B (2026-09-09); the scanner accepts only
# synthetic fixtures. There is no non-synthetic exception category.
# Exclusions are fixed and reported, never read from .gitignore. In particular,
# .env source files are scanned; .local runtime credentials are never traversed.
EXCLUDED_DIRS = {
    ".git", ".local", ".venv", "venv", "node_modules", ".next", ".pio",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".pdf", ".mp4", ".mov", ".pgm", ".ppm",
    ".wav", ".flac", ".mp3", ".zip", ".gz", ".xz", ".bz2", ".zst", ".tar",
    ".whl", ".pyc", ".pyo", ".so", ".dylib", ".dll", ".o", ".a", ".elf",
    ".bin", ".stl", ".step", ".stp", ".glb", ".blend", ".woff", ".woff2",
    ".sqlite", ".sqlite3", ".db", ".npz", ".npy", ".parquet", ".qcow2", ".raw",
}
# Deliberately finite recognizers. Assignment patterns require a long literal;
# short passwords, assembled/encoded tokens and unrecognized vendors are gaps.
PATTERNS = {
    "private-key-pem": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "aws-access-key": re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    "github-token": re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{40,255})(?![A-Za-z0-9_])"),
    "slack-token": re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{20,255}(?![A-Za-z0-9-])"),
    "google-api-key": re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])"),
    "stripe-live-key": re.compile(r"(?<![A-Za-z0-9_])(?:sk|rk)_live_[0-9A-Za-z]{24,255}(?![A-Za-z0-9])"),
    "credential-assignment": re.compile(r'''(?im)["']?\b(?:api[_-]?key|api[_-]?token|access[_-]?token|auth[_-]?token|client[_-]?secret|secret[_-]?key|password|passwd|aws[_-]?secret[_-]?access[_-]?key)\b["']?\s*[:=]\s*["']([A-Za-z0-9_+/=.!@#$%^&*-]{20,256})["']'''),
    "credential-url": re.compile(r"(?i)\b(?:https?|postgres(?:ql)?|mysql|redis|amqps?)://[^\s:/@\"']{1,128}:([^\s/@\"']{8,256})@"),
}


def fingerprint(pattern: str, value: str) -> str:
    # Domain separation prevents allowlist fingerprints crossing patterns.
    return hashlib.sha256(("poseidon-secret-match-v1\0" + pattern + "\0" + value).encode()).hexdigest()


def matches_in_text(path: str, text: str) -> list[dict]:
    matches = []
    for name, regex in PATTERNS.items():
        for match in regex.finditer(text):
            value = match.group(1) if match.lastindex else match.group(0)
            if name == "private-key-pem":
                # Header-only identities would allow a replacement real key at
                # the same fixture path. Bind any PEM body too; an unfinished
                # block binds the remaining (file-byte-bounded) text.
                end = text.find("-----END ", match.end())
                end_line = text.find("\n", end) if end >= 0 else -1
                value = text[match.start(): end_line if end_line >= 0 else len(text)]
            matches.append({"path": path, "line": text.count("\n", 0, match.start()) + 1, "pattern": name, "fingerprint": fingerprint(name, value)})
    return sorted(matches, key=lambda m: (m["path"], m["line"], m["pattern"], m["fingerprint"]))


def exclusion(path: PurePosixPath) -> str | None:
    if any(part in EXCLUDED_DIRS for part in path.parts):
        return "excluded-directory"
    if path.name in {".DS_Store"}:
        return "os-metadata"
    if path.suffix.lower() == ".log":
        return "generated-log-output"
    if path.suffix.lower() in BINARY_SUFFIXES:
        return "binary-extension"
    return None


def load_allowlist(path: Path) -> list[dict]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("allowlist must be a regular file no larger than 1 MiB")
    data = json.loads(path.read_bytes())
    if not isinstance(data, dict) or set(data) != {"version", "entries"} or data["version"] != 1 or not isinstance(data["entries"], list):
        raise ValueError("invalid allowlist structure")
    seen = set()
    for entry in data["entries"]:
        if not isinstance(entry, dict):
            raise ValueError("allowlist entry must be an object")
        fields = {"path", "pattern", "fingerprint", "occurrences", "justification", "category"}
        if set(entry) != fields or entry["category"] != "synthetic-fixture":
            raise ValueError("allowlist entries need exact identity, occurrence count, the synthetic-fixture category and justification")
        name = entry["path"]
        if not isinstance(name, str) or not name or "\\" in name or any(c in name for c in "*?[]\n\r\0"):
            raise ValueError("allowlist path must be literal and repository-relative")
        pure = PurePosixPath(name)
        if pure.is_absolute() or any(p in {".", ".."} for p in name.split("/")) or pure.as_posix() != name or exclusion(pure):
            raise ValueError("allowlist path cannot escape root or address an excluded file")
        if not (name.startswith("tests/") or "fixtures" in pure.parts or pure.suffix == ".example"):
            raise ValueError("allowlisting is restricted to synthetic test/fixture/example paths")
        if entry["pattern"] not in PATTERNS or not isinstance(entry["fingerprint"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["fingerprint"]) is None:
            raise ValueError("allowlist pattern/fingerprint must be exact")
        if type(entry["occurrences"]) is not int or not 1 <= entry["occurrences"] <= 100:
            raise ValueError("allowlist occurrence count must be a bounded positive integer")
        reason = entry["justification"]
        if not isinstance(reason, str) or not 20 <= len(reason) <= 1000 or "synthetic" not in reason.lower():
            raise ValueError("allowlist needs a specific synthetic-fixture justification")
        identity = (name, entry["pattern"], entry["fingerprint"])
        if identity in seen:
            raise ValueError("duplicate allowlist identity")
        seen.add(identity)
    return data["entries"]


def scan(root: Path, entries: list[dict]) -> dict:
    root = root.resolve()
    if not root.is_dir() or root == Path(root.anchor) or root == Path.home().resolve():
        raise ValueError("scan root must be a project directory, never host root/home")
    matches, errors, skipped = [], [], Counter()
    scanned, scanned_bytes, visited = 0, 0, 0
    files_digest = hashlib.sha256()
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=lambda e: errors.append({"path": os.path.relpath(e.filename, root), "reason": "directory-read-error"})):
        retained = []
        for name in sorted(dirs):
            path = Path(directory) / name
            if name in EXCLUDED_DIRS:
                skipped["excluded-directory"] += 1
            elif path.is_symlink():
                skipped["symlink"] += 1
            else:
                retained.append(name)
        dirs[:] = retained
        for name in sorted(files):
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            visited += 1
            if visited > MAX_FILES:
                errors.append({"path": ".", "reason": "file-count-limit"})
                dirs[:] = []
                break
            try:
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    skipped["symlink"] += 1
                    continue
                if not stat.S_ISREG(mode):
                    errors.append({"path": rel, "reason": "non-regular-file"})
                    continue
                reason = exclusion(PurePosixPath(rel))
                if reason:
                    skipped[reason] += 1
                    continue
                # O_NOFOLLOW closes final-component symlink races. Ancestor
                # directories are not followed by traversal; source must freeze
                # for an evidence run because arbitrary concurrent edits remain.
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
                with os.fdopen(fd, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        errors.append({"path": rel, "reason": "non-regular-file"})
                        continue
                    raw = stream.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    errors.append({"path": rel, "reason": "file-byte-limit"})
                    continue
                scanned_bytes += len(raw)
                if scanned_bytes > MAX_TOTAL_BYTES:
                    errors.append({"path": ".", "reason": "total-byte-limit"})
                    dirs[:] = []
                    break
                if b"\0" in raw:
                    skipped["binary-nul"] += 1
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append({"path": rel, "reason": "non-utf8-unclassified"})
                    continue
                matches.extend(matches_in_text(rel, text))
                files_digest.update(rel.encode() + b"\0" + hashlib.sha256(raw).digest())
                scanned += 1
            except OSError:
                errors.append({"path": rel, "reason": "file-read-error"})
        if visited > MAX_FILES or scanned_bytes > MAX_TOTAL_BYTES:
            break
    actual = Counter((m["path"], m["pattern"], m["fingerprint"]) for m in matches)
    allowed = {(e["path"], e["pattern"], e["fingerprint"]): e for e in entries}
    allowlist_errors = [{"path": key[0], "pattern": key[1], "fingerprint": key[2], "expected_occurrences": entry["occurrences"], "actual_occurrences": actual[key]} for key, entry in sorted(allowed.items()) if actual[key] != entry["occurrences"]]
    unallowlisted = [m for m in matches if (m["path"], m["pattern"], m["fingerprint"]) not in allowed]
    categories = Counter(allowed[key]["category"] for key, count in actual.items() for _ in range(count) if key in allowed)
    return {
        "format": "poseidon.secrets-scan.v1", "ok": not (unallowlisted or errors or allowlist_errors),
        "publication_blocked": False, "allowlisted_categories": dict(sorted(categories.items())), "retained_vendor_exceptions": [],
        "open_items": [],
        "pattern_set_sha256": hashlib.sha256(json.dumps({n: {"regex": p.pattern, "flags": p.flags} for n, p in PATTERNS.items()}, sort_keys=True).encode()).hexdigest(),
        "coverage": {"scanned_text_files": scanned, "read_bytes": scanned_bytes, "visited_files": visited, "scanned_files_sha256": files_digest.hexdigest(), "skipped": dict(sorted(skipped.items())), "limits": {"file_bytes": MAX_FILE_BYTES, "total_bytes": MAX_TOTAL_BYTES, "files": MAX_FILES}, "excluded_directories": sorted(EXCLUDED_DIRS), "excluded_binary_suffixes": sorted(BINARY_SUFFIXES), "patterns": sorted(PATTERNS), "includes_untracked": True, "uses_gitignore": False, "claim": "Finite fixed-pattern scan of bounded UTF-8 text, not proof of absence of all secrets; binary/dependency/cache/runtime trees and symlinks excluded."},
        "counts": {"matches": len(matches), "allowlisted": len(matches) - len(unallowlisted), "unallowlisted": len(unallowlisted), "allowlist_errors": len(allowlist_errors), "coverage_errors": len(errors)},
        "unallowlisted": sorted(unallowlisted, key=lambda m: (m["path"], m["line"], m["pattern"])), "allowlist_errors": allowlist_errors, "coverage_errors": sorted(errors, key=lambda e: (e["path"], e["reason"])),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--allowlist", type=Path, help="Defaults to root/scripts/assurance/secrets-allowlist.json")
    args = parser.parse_args(argv)
    try:
        report = scan(args.root, load_allowlist(args.allowlist or args.root / ALLOWLIST))
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0 if report["ok"] else 1
    except (OSError, ValueError, TypeError, KeyError):
        # Never interpolate an exception: malformed input may contain a secret.
        print(json.dumps({"ok": False, "error": "invalid/unreadable scan root or allowlist; details withheld"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
