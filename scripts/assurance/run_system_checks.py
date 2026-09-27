"""Record one bounded, source-bound synthetic system test run in a new directory."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import subprocess
import sys

from evidence import ROOT, POLICY, TEST_COMMAND, EvidenceError, policy, require, source_hashes, digest, write_new, passing_test_ids


def run(root: Path, output: Path, policy_path: str = POLICY) -> int:
    output = output.absolute()
    require(".." not in output.parts and output.is_relative_to(root), "report directory must be under repository root without traversal")
    require(not output.exists() and not output.is_symlink(), "refusing existing output directory")
    current = root
    for part in output.relative_to(root).parts[:-1]:
        current /= part
        require(not current.is_symlink(), "symlink report parent not allowed")
    rules = policy(root, policy_path)
    before = source_hashes(root)
    result = subprocess.run(TEST_COMMAND, cwd=root, capture_output=True, text=True, timeout=120, check=False)
    after = source_hashes(root)
    require(before == after, "source changed during tests; no stable evidence recorded")
    log_text = result.stdout + result.stderr
    try:
        matches = passing_test_ids(log_text)
        passed = result.returncode == 0
    except EvidenceError:
        matches = []
        passed = False
    output.mkdir(parents=False, exist_ok=False)
    log = output / "system-checks-v1.log"
    with log.open("x", encoding="utf-8") as handle:
        handle.write(log_text)
    if not passed:
        print(log_text, end="")
        print(f"Failed or incomplete run; log retained at {log}; no accepted report created.")
        return 1
    report = {
        "schema_version": 1, "configuration": rules["configuration"], "evidence_level": "simulated",
        "provenance": "synthetic", "created_at": datetime.now(timezone.utc).isoformat(),
        "command": TEST_COMMAND, "exit_code": result.returncode,
        "tests_run": len(matches),
        "failures": 0, "errors": 0, "skipped": 0,
        "input_hashes": before, "test_ids": matches,
        "log": log.relative_to(root).as_posix(), "log_sha256": digest(log), "release_authorized": False,
    }
    write_new(output / "system-checks-v1.json", report)
    print(log_text, end="")
    print(f"Evidence report: {output / 'system-checks-v1.json'}; release_authorized=false")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--policy", default=POLICY)
    args = parser.parse_args()
    try:
        return run(ROOT, args.output_dir, args.policy)
    except (EvidenceError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"No accepted system evidence: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
