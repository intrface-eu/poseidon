#!/usr/bin/env python3
"""Check publishability of tracked and newly added repository files (stdlib only)."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 10 * 1024 * 1024
REQUIRED = ("LICENSE", "NOTICE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md")
PROSE = {".md", ".txt", ".rst", ".adoc", ".html", ".cff"}
PERSONAL_PATH = re.compile(rb"/(?:Users|home)/[^\s\x00\"'<>]+")
GMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@gmail\.com\b", re.IGNORECASE)
AGENT_NAME = re.compile(rb"\b(?:astra|herdr|gpt-6(?:-[a-z0-9-]+)?|claude|fable|omp|codex|opus)\b", re.IGNORECASE)
# An upstream JSON Schema retains its author's attribution. Fingerprint binds the
# one permitted address, not arbitrary replacements at the same file path.
ALLOWLIST = {
    ("docs/compliance/software-supply-chain/schema/jsf-0.82.schema.json", "gmail", "5d7d5538395a96ff5e41f187903ef38c0df8719f4622d69175bef3fa46776b1e"):
        "Original upstream schema author attribution; third-party text must not be silently rewritten.",
}
# These files define a fixed unprivileged Linux VM account, not a developer
# home directory. Only the exact account prefix in these implementation/test
# directories is exempt; other user homes still fail.
GUEST_HOME_ALLOWLIST = {
    "scripts/assurance/linux_capture_env/": "Fixed isolated VM account path required by guest provisioning.",
    "scripts/assurance/linux_python_env/": "Fixed isolated VM account path required by guest provisioning.",
    "tests/assurance/test_linux_capture_env.py": "Negative test of the fixed guest account path.",
    "tests/assurance/test_linux_python_env_artifacts.py": "Guest-result path fixture for isolated VM tests.",
    "tests/assurance/test_linux_python_env_lifecycle.py": "Guest-source path fixture for isolated VM tests.",
}


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True,
    )
    return sorted({name.decode("utf-8", "surrogateescape") for name in result.stdout.split(b"\0") if name})


def vendor_artifact(name: str) -> bool:
    path = PurePosixPath(name)
    if not path.parts or path.parts[0] != "hardware":
        return False
    # Generated first-party CAD is intentionally published; supplier inputs are not.
    return ("sources" in path.parts or "vendor" in path.parts) and path.suffix.lower() in {".step", ".stp", ".zip", ".pdf"}


def scan(root: Path, names: list[str], allowlist: dict[tuple[str, str, str], str]) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    allowed: list[str] = []
    for name in REQUIRED:
        if not (root / name).is_file() or (root / name).is_symlink():
            findings.append(f"{name}: missing required regular file")
    for name in sorted(set(names)):
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            findings.append(f"{name}: invalid repository path")
            continue
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue  # A tracked file deleted in the working tree is not being published.
        if vendor_artifact(name):
            findings.append(f"{name}: vendor CAD/datasheet artifact")
        try:
            if path.is_symlink():
                data = path.readlink().as_posix().encode("utf-8", "surrogateescape")
            elif path.is_file():
                size = path.stat().st_size
                if size > MAX_BYTES:
                    findings.append(f"{name}: exceeds 10 MiB ({size} bytes)")
                    continue
                data = path.read_bytes()
            else:
                findings.append(f"{name}: not a regular file")
                continue
        except OSError as exc:
            findings.append(f"{name}: unreadable ({type(exc).__name__})")
            continue
        patterns = [("home-path", PERSONAL_PATH), ("gmail", GMAIL)]
        if path.suffix.lower() in PROSE:
            patterns.append(("agent-name", AGENT_NAME))
        for kind, pattern in patterns:
            for match in pattern.finditer(data):
                value = match.group().lower()
                identity = (name, kind, hashlib.sha256(value).hexdigest())
                line = data.count(b"\n", 0, match.start()) + 1
                if identity in allowlist:
                    reason = allowlist[identity]
                    if not reason.strip():
                        findings.append(f"{name}:{line}: allowlist entry lacks a reason")
                    else:
                        allowed.append(f"{name}:{line}: allowed {kind} ({reason})")
                elif kind == "home-path" and value.startswith(b"/home/" + b"builder") and (len(value) == 13 or value[13:14] in (b"/", b"\"", b"'", b")", b"+")):
                    reason = next((reason for prefix, reason in GUEST_HOME_ALLOWLIST.items() if name.startswith(prefix)), None)
                    if reason:
                        allowed.append(f"{name}:{line}: allowed guest path ({reason})")
                    else:
                        findings.append(f"{name}:{line}: {kind}")
                else:
                    findings.append(f"{name}:{line}: {kind}")
    return findings, allowed


def main() -> int:
    try:
        findings, allowed = scan(ROOT, tracked_paths(ROOT), ALLOWLIST)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"public release check: cannot list repository files ({type(exc).__name__})")
        return 1
    for item in allowed:
        print(f"allowed: {item}")
    for item in findings:
        print(f"finding: {item}")
    print(f"public release check: {len(findings)} finding(s), {len(allowed)} allowed match(es)")
    return int(bool(findings))


if __name__ == "__main__":
    sys.exit(main())
