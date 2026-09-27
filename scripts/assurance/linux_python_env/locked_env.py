"""Stage2: pinned official tools/CPython and wheel-only locked guest environments.

Runs only unprivileged in the marked NEW Stage2 guest. Dependencies may download
while syncing; actual checks run later with offline settings. A missing wheel or
failed lane is recorded explicitly, never replaced with a source build/version.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tomllib

from scripts.assurance.linux_capture_env import guest_prepare as shared
from scripts.assurance.linux_python_env import artifacts, source

LANES = {"api": ("apps/aeolus-api", "3.11.15"), "nereid": ("apps/nereid", "3.12.13"), "firmware": ("firmware/update", "3.11.15")}


def validate_plan(plan: dict) -> dict:
    if set(plan) != {"schema_version", "uv", "python", "locks"} or plan["schema_version"] != "poseidon.linux-python-locked-tools.v1":
        raise ValueError("explicit frozen Stage2 tool/lock plan required")
    if plan["uv"] != artifacts.UV_PIN or plan["python"] != artifacts.PYTHON_PINS:
        raise ValueError("tool/interpreter plan differs from exact official Linux aarch64 pins")
    if type(plan["locks"]) is not dict or set(plan["locks"]) != set(LANES):
        raise ValueError("all three locked lanes must be accounted for")
    for lane, item in plan["locks"].items():
        if set(item) != {"project", "python", "lock_sha256", "pyproject_sha256"} or (item["project"], item["python"]) != LANES[lane]:
            raise ValueError("unexpected project/interpreter in locked lane")
        for field in ("lock_sha256", "pyproject_sha256"):
            if type(item[field]) is not str or len(item[field]) != 64 or any(c not in "0123456789abcdef" for c in item[field]):
                raise ValueError("lane needs exact lock/pyproject SHA256")
    return plan


def environment(workspace: Path) -> dict:
    return {"PATH": "/usr/bin:/bin", "HOME": str(workspace / "home"), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
            "XDG_CONFIG_HOME": str(workspace / "config"), "UV_CACHE_DIR": str(workspace / "uv-cache"),
            "UV_PYTHON_INSTALL_DIR": str(workspace / "python"), "UV_PYTHON_DOWNLOADS": "never",
            "UV_NO_BUILD": "1", "UV_HTTP_RETRIES": "0", "UV_HTTP_TIMEOUT": "30", "UV_NO_PROGRESS": "1",
            "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def check_lock_files(root: Path, plan: dict) -> None:
    for item in plan["locks"].values():
        for name, field in (("uv.lock", "lock_sha256"), ("pyproject.toml", "pyproject_sha256")):
            path = root / item["project"] / name
            if path.resolve() != path or source.sha256(path) != item[field]:
                raise ValueError("lane dependency files changed from frozen source")


def prepare(args) -> dict:
    shared.guard_guest(args.run_id, root=False)
    if source.sha256(args.plan) != args.plan_sha256:
        raise ValueError("Stage2 tool plan differs from parent-frozen hash")
    plan = validate_plan(source.strict_json(args.plan.read_bytes()))
    root = args.source.resolve()
    check_lock_files(root, plan)
    for path, prefix in ((args.workspace, "python-locked-work-"), (args.records, "python-locked-records-")):
        if path != Path("/home/builder") / (prefix + args.run_id):
            raise ValueError("Stage2 workspace/records must be exact new owned guest paths")
        shared.new_directory(path, root=False)
    workspace, records = args.workspace, args.records
    for part in ("home", "config", "python", "tools", "envs"):
        (workspace / part).mkdir(mode=0o700)
    for part in ("downloads", "wheels"):
        (records / part).mkdir(mode=0o700)
    run = shared.Runner(records)
    run.env = environment(workspace)
    result = {"schema_version": "poseidon.linux-python-locked-environments.v1", "run_id": args.run_id,
              "plan_sha256": args.plan_sha256, "uid": os.getuid(), "lanes": {}, "inputs": [],
              "third_party_source_builds_allowed": False, "release_authorized": False,
              "scope": "official pinned CPython distributions selected by explicit paths; no system Python replacement"}
    try:
        archive = records / "downloads/uv.tar.gz"
        result["inputs"].append(artifacts.download(plan["uv"], archive))
        extracted = artifacts.extract(archive, plan["uv"]["sha256"], workspace / "tools/uv-distribution", prefix="uv-aarch64-unknown-linux-gnu")
        uv = Path(extracted["root"]) / "uv"
        observed = run.run([uv, "--version"], timeout=20).strip()
        if not observed.startswith("uv " + artifacts.UV_VERSION + " "):
            raise ValueError("verified uv archive reported an unexpected version")
        result["uv"] = {"path": str(uv), "version_output": observed, "binary_sha256": source.sha256(uv), "archive_sha256": plan["uv"]["sha256"]}
        interpreters = {}
        for version, pin in sorted(plan["python"].items()):
            archive = records / "downloads" / (pin["key"] + ".tar.gz")
            result["inputs"].append(artifacts.download(pin, archive))
            extracted = artifacts.extract(archive, pin["sha256"], workspace / "python" / pin["key"], prefix="python")
            executable = Path(extracted["root"]) / "bin" / ("python" + ".".join(version.split(".")[:2]))
            identity = json.loads(run.run([executable, "-c", "import json,os,platform,sys;print(json.dumps({'python':platform.python_version(),'machine':platform.machine(),'uid':os.getuid(),'executable':sys.executable}))"], timeout=20))
            if identity["python"] != version or identity["machine"] != "aarch64" or identity["uid"] == 0:
                raise ValueError("pinned interpreter identity/architecture/UID differs")
            interpreters[version] = str(executable)
            result.setdefault("interpreters", {})[version] = identity | {"archive_sha256": pin["sha256"], "binary_sha256": source.sha256(executable), "distribution_key": pin["key"]}
        for lane, item in plan["locks"].items():
            check_lock_files(root, plan)
            lane_env = workspace / "envs" / lane
            run.env = environment(workspace) | {"UV_PROJECT_ENVIRONMENT": str(lane_env)}
            argv = [str(uv), "sync", "--locked", "--project", str(root / item["project"]), "--python", interpreters[item["python"]], "--no-build", "--no-python-downloads"]
            run.run(argv, timeout=900, cwd=root, allowed=(0, 1, 2))
            control = shared.load_json(run.logs / f"{run.counter:04d}.json")
            if control["returncode"] != 0:
                # Never rerun this lane or choose a source/version fallback. Keep
                # the exact diagnostics; a parent must classify the open lane.
                result["lanes"][lane] = {"state": "omitted-provisioning-failed", "exit": control["returncode"], "reason": "exact wheel-only locked uv sync did not complete; no retry or source/version fallback", "log": f"logs/{run.counter:04d}.json"}
                continue
            python = lane_env / "bin/python"
            installed = json.loads(run.run([python, "-c", artifacts.INSTALLED_QUERY], timeout=30))
            if installed["python"] != list(map(int, item["python"].split("."))):
                raise ValueError("locked environment uses an unexpected interpreter")
            lock = tomllib.loads((root / item["project"] / "uv.lock").read_text())
            retained = []
            for package in installed["distributions"]:
                wheel = artifacts.lock_wheel(lock, package)
                target = records / "wheels" / wheel["filename"]
                pin = {"url": wheel["url"], "sha256": wheel["hash"].removeprefix("sha256:"), "size": wheel["size"]}
                if target.exists():
                    if target.is_symlink() or source.sha256(target) != pin["sha256"] or target.stat().st_size != pin["size"]:
                        raise ValueError("previously retained wheel does not match this lane's lock")
                    artifact = pin | {"file": str(target), "reused_verified_artifact": True}
                else:
                    artifact = artifacts.download(pin, target)
                payload = artifacts.wheel_payload(target, package)
                retained.append({"name": package["name"], "version": package["version"], "filename": wheel["filename"], "tags": package["tags"], "lock_sha256": item["lock_sha256"], "artifact": artifact, "installed_payload": payload})
            # A second sync is an explicit offline completeness check, not a
            # retry: it occurs only after a successful online sync+wheel proof.
            run.env = environment(workspace) | {"UV_PROJECT_ENVIRONMENT": str(lane_env), "UV_OFFLINE": "1"}
            run.run([*argv, "--offline"], timeout=120, cwd=root)
            result["lanes"][lane] = {"state": "ready-offline", "python": str(python), "python_version": item["python"],
                                     "lock_sha256": item["lock_sha256"], "wheels": retained, "installed": installed,
                                     "third_party_source_builds_allowed": False}
            shared.write_json(records / (lane + "-environment.json"), result["lanes"][lane])
        check_lock_files(root, plan)
        result["state"] = "ready-offline" if all(row["state"] == "ready-offline" for row in result["lanes"].values()) else "incomplete-explicit-lane-omissions"
        shared.write_json(records / "environments.json", result)
        return result
    except BaseException as exc:
        shared.write_json(records / "failure.json", result | {"state": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        shared.artifact_manifest(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()

    def interrupted(signum, _):
        raise InterruptedError(f"Stage2 provisioning interrupted: {signum}")

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        result = prepare(args)
        print(json.dumps({"state": result["state"], "records": str(args.records)}))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Locked guest provisioning refused/failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
