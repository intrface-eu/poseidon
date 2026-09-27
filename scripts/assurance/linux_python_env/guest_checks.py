"""Execute a parent-frozen Debian-only Python check set inside a marked guest.

No VM start, dependency installer, capture driver or HIL executor exists here.
The parent must approve the exact check-set/source digests before invoking this
module. Omitted locked suites remain explicit exclusions in the result.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from scripts.assurance.linux_capture_env import guest_prepare as shared
from scripts.assurance.linux_python_env import source

PYTHON_ROOTS = ("libs/proto-py/src", "libs/dsp/src", "apps/acoustic/src", "apps/nereid/src", "apps/siren/src", "apps/trident/src", "apps/aeolus-api/src", "apps/aquilon/src", "firmware/update/src")
HARDWARE_TARGETS = {"check-hardware-reference", "check-hardware-calculations", "check-hardware-candidate"}
TEST_FILE_RE = re.compile(r"test[A-Za-z0-9_]*\.py\Z")
CLASS_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
# The Debian snapshot subset must never appear to qualify the locked lanes; each
# of these stays an explicit omission that only a Stage2 locked environment can
# execute. cryptography 43 evidence is not cryptography 46 qualification.
HIL_COVERAGE = "tests/assurance/test_hil_gate.py"
HIL_LABEL = "HIL guard file-positive path on Linux; not API, update or cryptography 46 qualification"
STAGE2_ONLY_ROOTS = ("tests/api", "tests/nereid", "tests/research/integration", "tests/aquilon/integration", "tests/acoustic/linux_backend_abi")
STAGE2_ONLY_FILES = frozenset({"tests/trident/test_lifecycle.py", "tests/firmware/test_update.py", "tests/firmware/test_platform_manifest.py"})
REQUIRED_OMISSIONS = ("tests/api", "tests/nereid")


def stage2_only(name: str) -> bool:
    return name in STAGE2_ONLY_FILES or any(name == root or name.startswith(root + "/") for root in STAGE2_ONLY_ROOTS)


def _positive(value: str, label: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,5}", value):
        raise ValueError(f"{label} must be a positive bounded integer")
    return int(value)


def stage1_command_paths(argv: list[str]) -> set[str]:
    """Validate one exact Stage1 command form and return required source files."""
    required: set[str] = set()
    suite_prefix = ["/usr/bin/python3", "-m", "scripts.assurance.linux_python_env.suite"]
    if argv[:3] == suite_prefix:
        tail = argv[3:]
        if len(tail) not in (6, 8) or tail[:1] != ["--root"] or tail[2:3] != ["--pattern"] or tail[4:5] != ["--minimum"]:
            raise ValueError("Stage1 suite selector must use exact root/pattern/minimum fields")
        root, pattern = tail[1], tail[3]
        source.safe_name(root)
        if not TEST_FILE_RE.fullmatch(pattern):
            raise ValueError("Stage1 suite pattern must name one exact test module")
        _positive(tail[5], "Stage1 suite minimum")
        if len(tail) == 8 and (tail[6] != "--class-name" or not CLASS_RE.fullmatch(tail[7])):
            raise ValueError("invalid explicit Stage1 class selector")
        required.add(f"{root}/{pattern}")
        required.add("scripts/assurance/linux_python_env/suite.py")
    elif argv[:4] == ["/usr/bin/python3", "-m", "compileall", "-q"]:
        if len(argv) < 5:
            raise ValueError("compileall needs explicit frozen paths")
        for name in argv[4:]:
            source.safe_name(name)
    elif argv in (["/usr/bin/python3", "scripts/task_graph.py", "validate", "--tag", "production-v1"],
                  ["/usr/bin/python3", "scripts/task_graph.py", "generate", "--tag", "production-v1", "--check"]):
        required.add("scripts/task_graph.py")
    elif argv == ["/usr/bin/python3", "scripts/platform/check_ops.py"]:
        required.add("scripts/platform/check_ops.py")
    elif len(argv) == 4 and argv[0] == "/usr/bin/make" and argv[1] in HARDWARE_TARGETS and argv[2] == "PYTHON=/usr/bin/python3" and argv[3] == "VERIFY_ROOT={source}/.local/python-tranche3-{run_id}":
        required.add("Makefile")
    else:
        raise ValueError("command is not an approved Python/static regression form")
    return required


def validate_checkset(value: dict) -> dict:
    if set(value) != {"schema_version", "commands", "omissions", "package_pins", "source_manifest_sha256", "python_version"} or value["schema_version"] != "poseidon.linux-python-checkset.v1":
        raise ValueError("only a frozen executable check-set schema is accepted, not a proposal")
    if value["python_version"] != "3.13.5" or type(value["source_manifest_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", value["source_manifest_sha256"]):
        raise ValueError("check set needs exact Debian Python/source pins")
    omitted: set[str] = set()
    if type(value["omissions"]) is not list or not value["omissions"]:
        raise ValueError("Debian subset must state omitted locked suites")
    for entry in value["omissions"]:
        if type(entry) is not dict or not {"paths", "reason"} <= set(entry) or type(entry["reason"]) is not str or not entry["reason"].strip():
            raise ValueError("each omission needs explicit paths and a stated reason")
        if type(entry["paths"]) is not list or not entry["paths"] or any(type(name) is not str or not name.strip() for name in entry["paths"]):
            raise ValueError("each omission needs explicit nonempty paths")
        omitted.update(entry["paths"])
    if not set(REQUIRED_OMISSIONS) <= omitted:
        raise ValueError("locked cryptography46 lanes must stay explicit Stage1 omissions")
    if type(value["package_pins"]) is not dict or not value["package_pins"]:
        raise ValueError("check set needs exact package pins")
    for name, version in value["package_pins"].items():
        if type(name) is not str or not shared.PACKAGE_RE.fullmatch(name) or type(version) is not str or not shared.VERSION_RE.fullmatch(version):
            raise ValueError("invalid Debian package identity")
    commands = value["commands"]
    if type(commands) is not list or not 1 <= len(commands) <= 300:
        raise ValueError("check set needs bounded nonempty commands")
    seen = set()
    for command in commands:
        if type(command) is not dict or not {"id", "argv", "timeout_seconds", "environment", "coverage"} <= set(command) or set(command) - {"id", "argv", "timeout_seconds", "environment", "coverage", "evidence_label"}:
            raise ValueError("invalid command fields; pending proposal decisions cannot execute")
        name = command["id"]
        if type(name) is not str or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,160}", name) or name in seen:
            raise ValueError("invalid/duplicate command identity")
        seen.add(name)
        if type(command["timeout_seconds"]) is not int or not 1 <= command["timeout_seconds"] <= 900:
            raise ValueError("every check needs a bounded hard deadline")
        env = command["environment"]
        if type(env) is not dict or any(k not in {"REEF_SANITIZE", "MONITOR_SANITIZE"} or v != "1" for k, v in env.items()):
            raise ValueError("only explicit synthetic sanitizer environment switches are allowed")
        argv = command["argv"]
        if type(argv) is not list or not argv or any(type(v) is not str or not v or "\x00" in v for v in argv):
            raise ValueError("command needs exact nonempty argv")
        required_paths = stage1_command_paths(argv)
        if type(command["coverage"]) is not list or not command["coverage"]:
            raise ValueError("each command must identify covered frozen paths")
        for path in command["coverage"]:
            source.safe_name(path)
        selected_tests = {name for name in required_paths if name.startswith(("tests/", "apps/")) and name.endswith(".py")}
        if not selected_tests <= set(command["coverage"]):
            raise ValueError("Stage1 coverage must name every exact selected test module")
        if any(stage2_only(name) for name in set(command["coverage"]) | required_paths):
            raise ValueError("locked-lane suite cannot run in the Debian snapshot subset")
        label = command.get("evidence_label")
        if HIL_COVERAGE in command["coverage"] or HIL_COVERAGE in required_paths:
            if label != HIL_LABEL:
                raise ValueError("the HIL guard check must carry the exact limited HIL evidence label")
        elif label is not None:
            raise ValueError("only the labelled HIL guard check may carry an evidence label")
    return value


def command_environment(root: Path, records: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "HOME": str(records / "home"), "TMPDIR": str(records / "tmp"),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
            "PYTHONPYCACHEPREFIX": str(records / "pycache"),
            "PYTHONPATH": os.pathsep.join([str(root), *(str(root / name) for name in PYTHON_ROOTS)]),
            "REEF_TEST_TMPDIR": str(records / "tmp"), "CXX": "/usr/bin/g++",
            # pytest's tmp_path directories carry symlinks, which the shared evidence
            # manifest refuses (run lp3-stage2-004). A given basetemp inside the records
            # keeps that scratch in one known place, and scripts/assurance/run_pytest.py
            # removes it after the session. unittest commands ignore the variable.
            "PYTEST_ADDOPTS": f"--basetemp={records / 'tmp' / 'pytest-basetemp'}"}


def suite_record(text: str) -> dict:
    matches = [line.removeprefix("POSEIDON_SUITE_RESULT=") for line in text.splitlines() if line.startswith("POSEIDON_SUITE_RESULT=")]
    if len(matches) != 1:
        raise ValueError("suite must emit exactly one machine-readable result")
    result = source.strict_json(matches[0].encode())
    if result.get("accepted") is not True or type(result.get("tests_run")) is not int or result["tests_run"] < result.get("required_minimum", 1):
        raise ValueError("suite is empty, incomplete or failed")
    for key in ("failures", "errors", "skipped", "expected_failures", "unexpected_successes"):
        if type(result.get(key)) is not int or result[key] != 0:
            raise ValueError("suite failure/skip/expected-outcome counters must all be zero")
    if len(result.get("selected_ids", [])) != result["tests_run"]:
        raise ValueError("suite selected/executed count differs")
    return result


def run(args) -> dict:
    shared.guard_guest(args.run_id, root=False)
    if sys.version_info[:3] != (3, 13, 5):
        raise ValueError("only snapshot Python3.13.5 is approved for this subset")
    for path, expected in ((args.checkset, args.checkset_sha256), (args.source_manifest, args.source_manifest_sha256)):
        if source.sha256(path) != expected:
            raise ValueError("input manifest differs from parent-frozen hash")
    checkset = validate_checkset(source.strict_json(args.checkset.read_bytes()))
    frozen = source.validate_manifest(source.strict_json(args.source_manifest.read_bytes()))
    if checkset["source_manifest_sha256"] != args.source_manifest_sha256:
        raise ValueError("check set and source handoff disagree")
    root = args.source.resolve()
    source.verify(root, frozen)
    if args.output.parent.resolve() != args.output.parent or args.output.exists() or args.output.is_symlink():
        raise ValueError("records must use a new directory without symlink parents")
    if not args.output.is_relative_to(Path("/home/builder")) or not root.is_relative_to(Path("/home/builder")):
        raise ValueError("tests/records must remain inside this run's guest builder home")
    args.output.mkdir(mode=0o700)
    for name in ("home", "tmp", "pycache"):
        (args.output / name).mkdir(mode=0o700)
    logs = shared.Runner(args.output)
    logs.env = command_environment(root, args.output)
    result = {"schema_version": "poseidon.linux-python-result.v1", "run_id": args.run_id,
              "started_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), "uid": os.getuid(),
              "scope": "Debian-snapshot-eligible Python subset; not full locked API/codec/update qualification",
              "checkset_sha256": args.checkset_sha256, "source_manifest_sha256": args.source_manifest_sha256,
              "commands": [], "omissions": checkset["omissions"], "release_authorized": False,
              "physical_operations_performed": False, "state": "running", "cleanup_ok": False}
    failure = None
    try:
        installed = shared.installed_packages(logs)
        for name, expected in checkset["package_pins"].items():
            if installed.get(name, {}).get("Version") != expected:
                raise ValueError(f"installed package differs from approved snapshot pin: {name}")
        result["installed_package_pins"] = checkset["package_pins"]
        for command in checkset["commands"]:
            source.verify(root, frozen)
            row = {"id": command["id"], "started_at": datetime.now(timezone.utc).isoformat(), "exit": None}
            result["commands"].append(row)
            shared.write_json(args.output / (command["id"] + ".started.json"), row)
            argv = [value.replace("{source}", str(root)).replace("{run_id}", args.run_id) for value in command["argv"]]
            logs.env = command_environment(root, args.output) | command["environment"]
            # Existing wrapper always stops its exact child group, including on
            # normal exit. Outer guest deadline leaves30s for wrapper cleanup.
            wrapped = ["/usr/bin/python3", str(root / "scripts/assurance/run_command.py"), "--timeout", str(command["timeout_seconds"]), "--", *argv]
            before = time.monotonic()
            output = None
            try:
                output = logs.run(wrapped, timeout=command["timeout_seconds"] + 30, cwd=root)
            finally:
                control_path = logs.logs / f"{logs.counter:04d}.json"
                row.update({"argv": argv, "timeout_seconds": command["timeout_seconds"],
                            "elapsed_seconds": time.monotonic() - before,
                            "log_record": f"logs/{logs.counter:04d}.json"})
                if control_path.is_file():
                    row["exit"] = shared.load_json(control_path)["returncode"]
                if row["exit"] != 0:
                    shared.write_json(args.output / (command["id"] + ".failed.json"), row)
            if output is None:
                raise ValueError("command completed without retained output accounting")
            if argv[:3] == ["/usr/bin/python3", "-m", "scripts.assurance.linux_python_env.suite"]:
                row["suite"] = suite_record(output)
            source.verify(root, frozen)
            shared.write_json(args.output / (command["id"] + ".completed.json"), row)
        result["state"] = "checks-complete-host-collection-and-vm-stop-required"
    except BaseException as exc:
        failure = exc
        result["state"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            source.verify(root, frozen)
            result["source_hashes_preserved"] = True
        except BaseException as exc:
            failure = failure or exc
            result["state"] = "failed"
            result["source_error"] = str(exc)
        # Guest success cannot assert that the host stopped/reaped the VM.
        result["cleanup_ok"] = False
        result["cleanup_pending"] = "host must collect all records and prove owned VM/control processes stopped"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        shared.write_json(args.output / "result.json", result)
        shared.artifact_manifest(args.output)
    if failure is not None:
        raise ValueError(result.get("error", result.get("source_error", "guest checks failed")))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--checkset", type=Path, required=True)
    parser.add_argument("--checkset-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def interrupted(signum, _):
        raise InterruptedError(f"guest Python checks interrupted by signal {signum}")

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        print(json.dumps(run(args), sort_keys=True))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Linux Python checks refused/failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
