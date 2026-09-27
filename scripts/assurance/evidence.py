"""Offline evidence integrity and conservative release-gate evaluation.

Hashes bind bytes, not truth or reviewer identity. External gates never pass here.
No command from an evidence file is executed and no existing file is overwritten.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
POLICY = "docs/qualification/gate-policy-v1.json"
MANIFEST = "docs/qualification/evidence-manifest-v1.json"
TEST_COMMAND = ["python3", "-m", "unittest", "discover", "-s", "tests/system", "-v"]
SOURCE_DIRS = (
    "apps/trident/src", "apps/acoustic/src", "libs/proto-py/src",
    "tests/system", "scripts/assurance", "contracts/v1",
)
DEPENDENCY_FILES = ("pyproject.toml", "apps/aeolus-api/pyproject.toml", "apps/aeolus-api/uv.lock")
LEVELS = {
    "software-complete", "simulated", "source-verified-vendor-data",
    "independently-reviewed", "physically-tested", "authority-decision", "documented-plan",
}
MAX_BYTES = 8 * 1024 * 1024


class EvidenceError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def exact(value: object, keys: set[str], context: str) -> None:
    require(type(value) is dict and set(value) == keys, f"{context}: incorrect fields")


def text(value: object, context: str) -> None:
    require(type(value) is str and bool(value.strip()), f"{context}: nonempty text required")


def strings(value: object, context: str, *, empty: bool = False) -> None:
    require(type(value) is list, f"{context}: list required")
    for item in value:
        text(item, context)
    require(len(value) == len(set(value)), f"{context}: duplicate values")
    require(empty or bool(value), f"{context}: empty list")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise EvidenceError(f"invalid JSON constant: {value}")


def load(path: Path) -> dict:
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, f"missing/oversized JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise EvidenceError(f"invalid JSON {path}: {exc}") from exc
    require(type(value) is dict, f"JSON object required: {path}")
    return value


def local_file(root: Path, relative: str) -> Path:
    text(relative, "path")
    parts = PurePosixPath(relative)
    require(not parts.is_absolute() and ".." not in parts.parts and "\\" not in relative,
            f"unsafe path: {relative}")
    require(parts.as_posix() == relative and relative != ".", f"noncanonical path: {relative}")
    path = root
    for part in parts.parts:
        path = path / part
        require(not path.is_symlink(), f"symlink evidence not allowed: {relative}")
    require(path.is_file() and path.resolve().is_relative_to(root.resolve()), f"missing file: {relative}")
    require(path.stat().st_size <= MAX_BYTES, f"oversized artifact: {relative}")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: object) -> None:
    text(value, "timestamp")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(date.utcoffset() is not None, "timestamp must include timezone")
        require(date <= datetime.now(timezone.utc), "future evidence timestamp")
    except ValueError as exc:
        raise EvidenceError("invalid timestamp") from exc


def source_hashes(root: Path) -> dict[str, str]:
    result = {}
    for directory in SOURCE_DIRS:
        paths = []
        for path in sorted((root / directory).rglob("*")):
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            require(not path.is_symlink(), f"symlink source input: {path.relative_to(root)}")
            if path.is_file():
                paths.append(path)
        require(bool(paths), f"no source files in {directory}")
        for path in paths:
            relative = path.relative_to(root).as_posix()
            result[relative] = digest(local_file(root, relative))
    for relative in DEPENDENCY_FILES:
        result[relative] = digest(local_file(root, relative))
    return result


def passing_test_ids(log_text: str) -> list[str]:
    counts = re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", log_text, re.M)
    require(len(counts) == 1, "test log needs exactly one run summary")
    require(len(re.findall(r"^OK$", log_text, re.M)) == 1 and log_text.rstrip().endswith("OK"),
            "test log is not one unskipped pass")
    require(re.search(r"^(?:FAILED|ERROR|FAIL|OK \(|UNEXPECTED SUCCESS|EXPECTED FAILURE|SKIPPED)", log_text, re.M) is None,
            "test log contains failure or skipped results")
    results = re.findall(r"^test[^\n]* \.\.\. [^\n]*$", log_text, re.M)
    identities = re.findall(r"^(test\S+ \([^\n]+\)) \.\.\. ok$", log_text, re.M)
    require(len(results) == len(identities) == int(counts[0]) and bool(identities), "test log result/count mismatch")
    require(len(identities) == len(set(identities)), "duplicate test log identities")
    return identities


def policy(root: Path, policy_path: str = POLICY) -> dict:
    result = load(local_file(root, policy_path))
    exact(result, {"schema_version", "policy_id", "configuration", "date", "requirements_source",
                   "roadmap_source", "evidence_levels", "gates"}, "policy")
    require(type(result["schema_version"]) is int and result["schema_version"] == 1, "policy version")
    for key in ("policy_id", "configuration"):
        text(result[key], key)
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", result[key]) is not None, f"invalid policy {key}")
    text(result["date"], "policy date")
    try:
        policy_date = date.fromisoformat(result["date"])
    except ValueError as exc:
        raise EvidenceError("invalid policy date") from exc
    require(policy_date.isoformat() == result["date"] and policy_date <= datetime.now(timezone.utc).date(), "invalid/future policy date")
    strings(result["evidence_levels"], "policy evidence levels")
    require(set(result["evidence_levels"]) == LEVELS, "policy evidence levels differ")
    require(type(result["gates"]) is list and bool(result["gates"]), "empty gate policy")
    requirements = set(re.findall(r"\| (REQ-[A-Z]+-\d+) \|", local_file(root, result["requirements_source"]).read_text()))
    covered, gate_ids, roadmap = set(), set(), set()
    for gate in result["gates"]:
        exact(gate, {"id", "title", "requirements", "roadmap", "owner", "dependencies", "automated",
                     "required_levels", "artifact", "method", "criterion", "status", "missing"}, "gate")
        for key in ("id", "title", "owner", "artifact", "method", "criterion", "status", "missing"):
            text(gate[key], key)
        require(gate["id"] not in gate_ids, "duplicate gate")
        gate_ids.add(gate["id"])
        for key in ("requirements", "roadmap", "required_levels", "dependencies"):
            strings(gate[key], key, empty=key == "dependencies")
        require(set(gate["required_levels"]) <= LEVELS, "unknown required evidence level")
        require(type(gate["automated"]) is bool, "automated must be boolean")
        require(gate["automated"] == (gate["id"] == "G-LOCAL"), "only G-LOCAL may be automated")
        covered.update(gate["requirements"])
        roadmap.update(gate["roadmap"])
    require(covered == requirements and bool(requirements), "requirements coverage missing or unknown")
    require({f"V{i}" for i in range(1, 10)} <= roadmap, "roadmap V1-V9 coverage incomplete")
    require({f"P{i}" for i in range(10)} <= roadmap, "roadmap P0-P9 coverage incomplete")
    by_id = {g["id"]: g for g in result["gates"]}
    def visit(gate_id: str, stack: set[str]) -> None:
        require(gate_id in by_id, f"unknown dependency: {gate_id}")
        require(gate_id not in stack, f"cyclic dependency: {gate_id}")
        for dependency in by_id[gate_id]["dependencies"]:
            visit(dependency, stack | {gate_id})
    for gate_id in gate_ids:
        visit(gate_id, set())
    local_file(root, result["roadmap_source"])
    return result


def verify_test_report(root: Path, path: Path, configuration: str) -> dict:
    report = load(path)
    exact(report, {"schema_version", "configuration", "evidence_level", "provenance", "created_at",
                   "command", "exit_code", "tests_run", "failures", "errors", "skipped", "input_hashes",
                   "test_ids", "log", "log_sha256", "release_authorized"}, "test report")
    require(type(report["schema_version"]) is int and report["schema_version"] == 1, "test report version")
    require(report["configuration"] == configuration, "test configuration mismatch")
    require(report["evidence_level"] == "simulated" and report["provenance"] == "synthetic", "test provenance mismatch")
    timestamp(report["created_at"])
    require(report["command"] == TEST_COMMAND, "unsupported test command")
    for key in ("exit_code", "tests_run", "failures", "errors", "skipped"):
        require(type(report[key]) is int, f"{key}: integer required")
    require(report["exit_code"] == 0 and report["tests_run"] > 0, "test command did not pass")
    require(report["failures"] == report["errors"] == report["skipped"] == 0, "failed/errored/skipped tests")
    strings(report["test_ids"], "test_ids")
    require(len(report["test_ids"]) == report["tests_run"], "test count/identity mismatch")
    require(report["input_hashes"] == source_hashes(root), "test source hashes stale or incomplete")
    require(report["release_authorized"] is False, "test report claims release authorization")
    log = local_file(root, report["log"])
    require(digest(log) == report["log_sha256"], "test log hash mismatch")
    log_text = log.read_text(encoding="utf-8")
    require(passing_test_ids(log_text) == report["test_ids"], "test log identities/count do not match report")
    return report


def validate(root: Path, manifest_path: Path, policy_path: str = POLICY) -> tuple[dict, dict]:
    rules = policy(root, policy_path)
    manifest = load(manifest_path)
    exact(manifest, {"schema_version", "policy_id", "configuration", "created_at", "artifacts",
                     "claims", "release_authorized"}, "manifest")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1, "manifest version")
    require(manifest["policy_id"] == rules["policy_id"], "policy mismatch")
    require(manifest["configuration"] == rules["configuration"], "manifest configuration mismatch")
    timestamp(manifest["created_at"])
    require(manifest["release_authorized"] is False, "manifest claims release authorization")
    require(type(manifest["artifacts"]) is list and bool(manifest["artifacts"]), "empty artifacts")
    gates = {g["id"] for g in rules["gates"]}
    paths, artifacts = set(), {}
    for item in manifest["artifacts"]:
        exact(item, {"path", "sha256", "bytes", "kind", "level", "gates", "configuration"}, "artifact")
        require(item["configuration"] == rules["configuration"], "artifact configuration mismatch")
        path = local_file(root, item["path"])
        require(item["path"] not in paths, "duplicate artifact path")
        paths.add(item["path"])
        require(type(item["sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) is not None,
                "invalid SHA-256")
        require(type(item["bytes"]) is int and item["bytes"] > 0 and path.stat().st_size == item["bytes"], "artifact size mismatch")
        require(digest(path) == item["sha256"], f"artifact hash mismatch: {item['path']}")
        require(type(item["level"]) is str and item["level"] in LEVELS, "unsupported evidence level")
        strings(item["gates"], "artifact gates")
        require(set(item["gates"]) <= gates, "unknown artifact gate")
        if item["kind"] == "test-report":
            require(item["level"] == "simulated" and item["gates"] == ["G-LOCAL"], "software report promoted to external proof")
            verify_test_report(root, path, rules["configuration"])
        elif item["kind"] == "plan":
            require(item["level"] == "documented-plan", "plan promoted to completed evidence")
            content = path.read_text(encoding="utf-8")
            require(len(content.strip()) >= 200 and bool(re.search(r"(?i)blocked|unverified|not.performed|missing|template|provisional|no .*authorized", content)),
                    f"plan lacks substantive content or open-state disclosure: {item['path']}")
        elif item["kind"] == "inventory":
            # Machine-readable dossier data (SBOM, license inventory, schemas): hashed, parsed, never a gate closure.
            require(item["level"] == "software-complete", "inventory promoted to external evidence")
            require(len(load(path)) > 0, f"inventory lacks content: {item['path']}")
        elif item["kind"] == "external-candidate":
            require(item["level"] in LEVELS - {"software-complete", "simulated", "documented-plan"}, "invalid external evidence level")
            external = load(path)
            exact(external, {"schema_version", "is_template", "configuration", "evidence_level", "performed_at",
                             "author", "method", "criterion_revision", "result", "raw_files", "limitations"}, "external candidate")
            require(type(external["schema_version"]) is int and external["schema_version"] == 1, "external candidate version")
            require(external["is_template"] is False and external["configuration"] == rules["configuration"], "template/wrong-configuration external record")
            require(external["evidence_level"] == item["level"], "external level mismatch")
            timestamp(external["performed_at"])
            for key in ("author", "method", "criterion_revision", "result", "limitations"):
                text(external[key], key)
            require(type(external["raw_files"]) is dict and bool(external["raw_files"]), "external raw evidence missing")
            for raw_path, raw_hash in external["raw_files"].items():
                require(digest(local_file(root, raw_path)) == raw_hash, "external raw hash mismatch")
        else:
            raise EvidenceError("unsupported artifact kind")
        artifacts[item["path"]] = item
    for gate in rules["gates"]:
        require(gate["artifact"] in artifacts and gate["id"] in artifacts[gate["artifact"]]["gates"]
                or gate["id"] == "G-SOFTWARE" and gate["artifact"] in artifacts,
                f"required gate artifact missing: {gate['id']}")
    require(type(manifest["claims"]) is dict and set(manifest["claims"]) == gates, "claim coverage mismatch")
    for gate_id, claim in manifest["claims"].items():
        require(type(claim) is str and claim in {"blocked", "software-checks-passed"}, "unsupported completion claim")
        if claim == "software-checks-passed":
            require(gate_id == "G-LOCAL" and any(a["kind"] == "test-report" for a in artifacts.values()), "unsupported software completion")
    return rules, manifest


def evaluate(root: Path, manifest_path: Path, policy_path: str = POLICY) -> dict:
    rules, manifest = validate(root, manifest_path, policy_path)
    results = []
    for gate in rules["gates"]:
        status = "blocked"
        if gate["automated"] and manifest["claims"][gate["id"]] == "software-checks-passed":
            status = "software-checks-passed"
        results.append({"id": gate["id"], "status": status, "owner": gate["owner"],
                        "reason": "Local synthetic software checks only; not release evidence." if status != "blocked"
                        else gate["missing"], "dependencies": gate["dependencies"]})
    return {"schema_version": 1, "policy_id": rules["policy_id"], "configuration": rules["configuration"],
            "integrity_valid": True, "release_authorized": False, "gates": results,
            "limitation": "Integrity is not authenticity, legal approval, physical qualification or efficacy. External evidence requires independent human review; this tool cannot authorize release."}


def write_new(path: Path, value: dict) -> None:
    # Exclusive creation preserves unknown files, including symlinks.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "evaluate"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", default=MANIFEST)
    parser.add_argument("--policy", default=POLICY)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        result = evaluate(root, local_file(root, args.manifest), args.policy)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if args.action == "validate" else 2
    except (EvidenceError, OSError, UnicodeError, TypeError, KeyError, RecursionError) as exc:
        print(json.dumps({"integrity_valid": False, "release_authorized": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
