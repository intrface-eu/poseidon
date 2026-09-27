"""Stage2 offline checks with exact locked-wheel and frozen-source preservation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from scripts.assurance.linux_capture_env import guest_prepare as shared
from scripts.assurance.linux_python_env import artifacts, guest_checks, locked_env, source


def validate_checkset(value: dict) -> dict:
    if set(value) != {"schema_version", "commands", "source_manifest_sha256", "tool_plan_sha256", "omissions"} or value["schema_version"] != "poseidon.linux-python-locked-checkset.v1":
        raise ValueError("frozen executable Stage2 check set required")
    for field in ("source_manifest_sha256", "tool_plan_sha256"):
        if type(value[field]) is not str or not re.fullmatch(r"[0-9a-f]{64}", value[field]):
            raise ValueError("Stage2 source/tool plan hashes are required")
    if type(value["omissions"]) is not list or not value["omissions"]:
        raise ValueError("explicit out-of-scope native/hardware/frontend exclusions required")
    if type(value["commands"]) is not list or not 1 <= len(value["commands"]) <= 300:
        raise ValueError("Stage2 commands must be bounded and nonempty")
    seen = set()
    for row in value["commands"]:
        if type(row) is not dict or set(row) != {"id", "lane", "argv", "timeout_seconds", "environment", "coverage"}:
            raise ValueError("invalid frozen Stage2 command fields")
        if row["lane"] not in locked_env.LANES or type(row["id"]) is not str or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,160}", row["id"]) or row["id"] in seen:
            raise ValueError("invalid lane/duplicate check identity")
        seen.add(row["id"])
        if type(row["timeout_seconds"]) is not int or not 1 <= row["timeout_seconds"] <= 900:
            raise ValueError("bounded Stage2 command deadline required")
        if type(row["environment"]) is not dict or any(k not in {"REEF_SANITIZE", "MONITOR_SANITIZE"} or v != "1" for k, v in row["environment"].items()):
            raise ValueError("unapproved environment mutation")
        argv = row["argv"]
        if type(argv) is not list or any(type(v) is not str or not v or "\x00" in v for v in argv):
            raise ValueError("exact command argv required")
        allowed = (argv[:2] == ["{python}", "scripts/assurance/run_unittest.py"]
                   or argv[:2] == ["{python}", "scripts/assurance/run_pytest.py"]
                   or argv[:4] == ["{python}", "-m", "compileall", "-q"]
                   or argv == ["{python}", "scripts/task_graph.py", "validate", "--tag", "production-v1"]
                   or argv == ["{python}", "scripts/task_graph.py", "generate", "--tag", "production-v1", "--check"]
                   or argv == ["{python}", "scripts/platform/check_ops.py"]
                   or (len(argv) == 4 and argv[0] == "/usr/bin/make" and argv[1] in guest_checks.HARDWARE_TARGETS and argv[2] == "PYTHON={python}" and argv[3] == "VERIFY_ROOT={source}/.local/python-tranche3-{run_id}"))
        if not allowed:
            raise ValueError("Stage2 command is not a reviewed Python/static regression form")
        if type(row["coverage"]) is not list or not row["coverage"]:
            raise ValueError("frozen coverage paths required")
        for name in row["coverage"]:
            source.safe_name(name)
    return value


def guard_summary(argv: list[str], text: str) -> dict | None:
    if "scripts/assurance/run_unittest.py" in argv:
        matches = re.findall(r"Assurance PASS: tests_run=(\d+), failures=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0, required_minimum=(\d+)\.", text)
        if len(matches) != 1 or int(matches[0][0]) < int(matches[0][1]) or int(matches[0][1]) < 1:
            raise ValueError("locked unittest guard did not report one complete zero-skip suite")
        return {"tests_run": int(matches[0][0]), "required_minimum": int(matches[0][1]), "skipped": 0, "failures": 0, "errors": 0}
    if "scripts/assurance/run_pytest.py" in argv:
        matches = re.findall(r"Assurance PASS: collected=(\d+), call_reports=(\d+), pytest_exit=0\.", text)
        # Every collected test yields one call report; pytest subtests add more
        # (run lp3-stage2-003: collected=466, call_reports=662), so fewer reports
        # than collected tests is the only incomplete shape.
        if len(matches) != 1 or min(map(int, matches[0])) < 1 or int(matches[0][1]) < int(matches[0][0]):
            raise ValueError("locked pytest guard did not report complete collected/call coverage")
        return {"collected": int(matches[0][0]), "tests_run": int(matches[0][1]), "skipped": 0, "pytest_exit": 0}
    return None


def verify_lane(root: Path, environments: dict, lane: str) -> None:
    """Re-prove one lane's exact lock, interpreter and wheel identities."""
    row = environments.get("lanes", {}).get(lane)
    if type(row) is not dict or row.get("state") != "ready-offline":
        raise ValueError("cannot execute an omitted/unprepared lane")
    project, version = locked_env.LANES[lane]
    if source.sha256(root / project / "uv.lock") != row.get("lock_sha256") or row.get("python_version") != version:
        raise ValueError("lane lock/interpreter identity changed")
    interpreter = Path(row["python"])
    pin = environments.get("interpreters", {}).get(version)
    if type(pin) is not dict or source.sha256(interpreter) != pin.get("binary_sha256"):
        raise ValueError("lane interpreter binary differs from retained official artifact")
    packages = {artifacts.normalize(p["name"]): p for p in row["installed"]["distributions"]}
    if len(packages) != len(row["wheels"]) or len(packages) != len(row["installed"]["distributions"]):
        raise ValueError("installed distribution and retained wheel identities do not correspond")
    for wheel in row["wheels"]:
        archive = Path(wheel["artifact"]["file"])
        if archive.resolve() != archive or source.sha256(archive) != wheel["artifact"]["sha256"]:
            raise ValueError("retained wheel changed before/after tests")
        installed = packages.get(artifacts.normalize(wheel["name"]))
        if installed is None or installed["version"] != wheel["version"]:
            raise ValueError(f"retained wheel does not match an installed distribution: {wheel['name']}")
        artifacts.wheel_payload(archive, installed)


def run(args) -> dict:
    shared.guard_guest(args.run_id, root=False)
    for path, expected in ((args.source_manifest, args.source_manifest_sha256), (args.checkset, args.checkset_sha256), (args.environments, args.environments_sha256)):
        if path.resolve() != path or source.sha256(path) != expected:
            raise ValueError("Stage2 frozen source/check/environment record changed")
    checkset = validate_checkset(source.strict_json(args.checkset.read_bytes()))
    frozen = source.validate_manifest(source.strict_json(args.source_manifest.read_bytes()))
    environments = source.strict_json(args.environments.read_bytes())
    if checkset["source_manifest_sha256"] != args.source_manifest_sha256 or checkset["tool_plan_sha256"] != environments.get("plan_sha256") or environments.get("run_id") != args.run_id or environments.get("uid") != os.getuid():
        raise ValueError("Stage2 source/environment/run bindings differ")
    if set(environments.get("lanes", {})) != set(locked_env.LANES):
        raise ValueError("all locked lanes must be explicitly ready or omitted")
    root = args.source.resolve()
    if args.output != Path("/home/builder/python-checks-" + args.run_id):
        raise ValueError("exact new owned Stage2 result directory required")
    source.verify(root, frozen)
    shared.new_directory(args.output, root=False)
    for name in ("home", "tmp", "pycache"):
        (args.output / name).mkdir(mode=0o700)
    logs = shared.Runner(args.output)
    result = {"schema_version": "poseidon.linux-python-result.v1", "stage": 2, "run_id": args.run_id,
              "state": "running", "commands": [], "omissions": list(checkset["omissions"]),
              "source_manifest_sha256": args.source_manifest_sha256, "checkset_sha256": args.checkset_sha256,
              "environments_sha256": args.environments_sha256, "release_authorized": False,
              "physical_operations_performed": False, "cleanup_ok": False, "offline_tests": True}
    failed = None
    omitted_commands = []
    try:
        for command in checkset["commands"]:
            lane = command["lane"]
            if environments["lanes"][lane]["state"] != "ready-offline":
                omission = {"command": command["id"], "lane": lane, "reason": environments["lanes"][lane]}
                result["omissions"].append(omission)
                omitted_commands.append(command["id"])
                continue
            source.verify(root, frozen)
            verify_lane(root, environments, lane)
            python = environments["lanes"][lane]["python"]
            argv = [value.replace("{python}", python).replace("{source}", str(root)).replace("{run_id}", args.run_id) for value in command["argv"]]
            logs.env = guest_checks.command_environment(root, args.output) | command["environment"] | {"UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never", "UV_HTTP_RETRIES": "0", "PIP_NO_INDEX": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
            row = {"id": command["id"], "lane": lane, "argv": argv, "exit": None, "timeout_seconds": command["timeout_seconds"]}
            result["commands"].append(row)
            shared.write_json(args.output / (command["id"] + ".started.json"), row)
            started = time.monotonic()
            wrapped = ["/usr/bin/python3", str(root / "scripts/assurance/run_command.py"), "--timeout", str(command["timeout_seconds"]), "--", *argv]
            try:
                output = logs.run(wrapped, timeout=command["timeout_seconds"] + 30, cwd=root)
            finally:
                log = logs.logs / f"{logs.counter:04d}.json"
                if log.is_file():
                    row["exit"] = shared.load_json(log)["returncode"]
                    row["log_record"] = str(log.relative_to(args.output))
            text = output + (logs.logs / f"{logs.counter:04d}.stderr").read_text()
            row["suite"] = guard_summary(argv, text)
            row["elapsed_seconds"] = time.monotonic() - started
            source.verify(root, frozen)
            verify_lane(root, environments, lane)
            shared.write_json(args.output / (command["id"] + ".completed.json"), row)
        result["state"] = "incomplete-explicit-lane-omissions" if omitted_commands else "checks-complete-host-collection-and-vm-stop-required"
    except BaseException as exc:
        failed = exc
        result["state"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            source.verify(root, frozen)
            for lane, row in environments["lanes"].items():
                if row["state"] == "ready-offline":
                    verify_lane(root, environments, lane)
            if source.sha256(args.environments) != args.environments_sha256:
                raise ValueError("environment provenance changed during tests")
            result["source_and_dependency_hashes_preserved"] = True
        except BaseException as exc:
            failed = failed or exc
            result["state"] = "failed"
            result["preservation_error"] = str(exc)
        result["omitted_commands"] = omitted_commands
        result["cleanup_pending"] = "host must collect records and stop/reap the NEW Stage2 VM"
        shared.write_json(args.output / "result.json", result)
        shared.artifact_manifest(args.output)
    if failed is not None:
        raise ValueError(result.get("error", result.get("preservation_error", "Stage2 checks failed")))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "source-manifest", "checkset", "environments", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("run-id", "source-manifest-sha256", "checkset-sha256", "environments-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()

    def interrupted(signum, _):
        raise InterruptedError(f"Stage2 checks interrupted: {signum}")

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        result = run(args)
        print(json.dumps({"state": result["state"], "output": str(args.output)}))
        return 0 if result["state"] == "checks-complete-host-collection-and-vm-stop-required" else 1
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Locked Python checks refused/failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
