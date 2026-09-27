"""Create a new assurance manifest from current plans and an existing passing system report."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from evidence import ROOT, POLICY, EvidenceError, digest, load, local_file, policy, require, verify_test_report, write_new


def snapshot(root: Path, output: Path, policy_path: str = POLICY) -> dict:
    rules = policy(root, policy_path)
    gates_by_path: dict[str, list[str]] = {}
    for gate in rules["gates"]:
        gates_by_path.setdefault(gate["artifact"], []).append(gate["id"])
    # Supporting dossiers are hashed too; their presence never closes a gate.
    for directory, gates in (
        ("docs/compliance", ["G-CONFORMITY", "G-PRIVACY"]),
        ("docs/manufacturing", ["G-MANUFACTURE", "G-LIFECYCLE"]),
        ("docs/qualification/procedures", ["G-MECHANICAL", "G-POWER", "G-SAFETY"]),
    ):
        for path in sorted((root / directory).rglob("*")):
            if path.suffix in {".md", ".json"}:
                gates_by_path.setdefault(path.relative_to(root).as_posix(), gates)
    gates_by_path.setdefault(policy_path, ["G-SCOPE"])
    gates_by_path.setdefault("docs/qualification/evidence-guide.md", ["G-SCOPE"])
    artifacts = []
    for relative, gates in sorted(gates_by_path.items()):
        path = local_file(root, relative)
        is_test = "G-LOCAL" in gates
        if is_test:
            verify_test_report(root, path, rules["configuration"])
            kind, level = "test-report", "simulated"
        elif path.suffix == ".json" and relative != policy_path and load(path).get("is_template") is not True:
            # Machine-readable inventories (SBOM, license inventory, schemas) are data, not prose plans.
            kind, level = "inventory", "software-complete"
        else:
            kind, level = "plan", "documented-plan"
        artifacts.append({"path": relative, "sha256": digest(path), "bytes": path.stat().st_size,
                          "kind": kind, "level": level,
                          "gates": ["G-LOCAL"] if is_test else gates, "configuration": rules["configuration"]})
    result = {"schema_version": 1, "policy_id": rules["policy_id"], "configuration": rules["configuration"],
              "created_at": datetime.now(timezone.utc).isoformat(), "artifacts": artifacts,
              "claims": {g["id"]: "software-checks-passed" if g["id"] == "G-LOCAL" else "blocked" for g in rules["gates"]},
              "release_authorized": False}
    absolute = output.absolute()
    require(".." not in absolute.parts and absolute.is_relative_to(root), "manifest output must stay under repository root without traversal")
    current = root
    for part in absolute.relative_to(root).parts[:-1]:
        current /= part
        require(not current.is_symlink(), "symlink manifest parent not allowed")
    write_new(absolute, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--policy", default=POLICY)
    args = parser.parse_args()
    try:
        result = snapshot(ROOT, args.output, args.policy)
        print(f"Recorded {len(result['artifacts'])} artifact hashes; external gates blocked; release_authorized=false")
        return 0
    except (EvidenceError, OSError) as exc:
        print(f"No manifest written: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
