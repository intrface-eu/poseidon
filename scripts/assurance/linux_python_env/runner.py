"""New owned Lima sessions for tranche3 Python verification; no Task18 VM reuse.

Requires parent-supplied digests of an explicit go record, source closure,
check set, package plan and normalized frozen handoffs BEFORE constructing a VM
session. The go record is workflow consent/integrity, not HIL authorization.
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
import tempfile
import time

from scripts.assurance.linux_capture_env import runner as shared
from scripts.assurance.linux_python_env import source, provision, locked_env, guest_checks, locked_checks

ROOT = Path(__file__).resolve().parents[3]
OWNER = "poseidon-linux-python-tranche3"
CACHE = ROOT / ".local/linux-capture-env-task18-2026-09-08"
# Exact helper closure the guest must already hold before any VM is constructed.
GUEST_HELPERS = {
    1: ("scripts/assurance/linux_capture_env/guest_prepare.py",
        "scripts/assurance/linux_python_env/__init__.py",
        "scripts/assurance/linux_python_env/guest_checks.py",
        "scripts/assurance/linux_python_env/provision.py",
        "scripts/assurance/linux_python_env/source.py",
        "scripts/assurance/linux_python_env/suite.py",
        "scripts/assurance/run_command.py"),
    2: ("scripts/assurance/linux_capture_env/guest_prepare.py",
        "scripts/assurance/linux_python_env/__init__.py",
        "scripts/assurance/linux_python_env/artifacts.py",
        "scripts/assurance/linux_python_env/guest_checks.py",
        "scripts/assurance/linux_python_env/locked_checks.py",
        "scripts/assurance/linux_python_env/locked_env.py",
        "scripts/assurance/linux_python_env/provision.py",
        "scripts/assurance/linux_python_env/source.py",
        "scripts/assurance/run_command.py",
        "scripts/assurance/run_pytest.py",
        "scripts/assurance/run_unittest.py"),
}
STAGE_DEADLINE_SECONDS = {1: 6 * 3600, 2: 8 * 3600}
MINIMUM_DEADLINE_SECONDS = 300
CLEANUP_RESERVE_SECONDS = 900


def frozen_json(path: Path, expected: str) -> dict:
    if path.resolve() != path or not path.is_file() or path.stat().st_size > 32 * 1024**2 or source.sha256(path) != expected:
        raise ValueError("missing/changed/nonregular parent-frozen manifest")
    return source.strict_json(path.read_bytes())


def validate_stage_checkset(stage: int, value: dict) -> dict:
    """Reject a malformed/stale executable check set on the host, not the guest."""
    return guest_checks.validate_checkset(value) if stage == 1 else locked_checks.validate_checkset(value)


def required_sources(stage: int, checkset: dict) -> set[str]:
    """Every frozen file the stage's own commands and helpers need to execute."""
    names = set(GUEST_HELPERS[stage])
    for command in checkset["commands"]:
        names.update(command["coverage"])
        if stage == 1:
            names.update(guest_checks.stage1_command_paths(command["argv"]))
        else:
            names.update(value for value in command["argv"] if value.startswith("scripts/") and value.endswith(".py"))
            if command["argv"][0] == "/usr/bin/make":
                names.add("Makefile")
    return {source.safe_name(name) for name in names}


def validate_go(args, *, now: float | None = None) -> tuple[dict, dict]:
    go = frozen_json(args.go, args.go_sha256)
    fields = {"schema_version", "stage", "run_id", "output", "source_manifest_sha256", "checkset_sha256", "package_plan_sha256", "tool_plan_sha256", "handoffs_sha256", "expires_unix", "release_authorized", "stage1_result"}
    if set(go) != fields or go["schema_version"] != "poseidon.linux-python-go.v1":
        raise ValueError("explicit parent go record required")
    if type(go["stage"]) is not int or go["stage"] not in (1, 2) or go["stage"] != args.stage or go["release_authorized"] is not False:
        raise ValueError("invalid stage/release scope in parent go")
    if type(go["run_id"]) is not str or not re.fullmatch(r"lp3-[a-zA-Z0-9-]{1,40}", go["run_id"]):
        raise ValueError("new tranche3 run identity required")
    if type(go["expires_unix"]) is not int or not (time.time() if now is None else now) < go["expires_unix"]:
        raise ValueError("parent go is expired")
    if go["output"] != str(args.output) or not args.output.name.startswith("linux-python-env-tranche3-"):
        raise ValueError("go/output is not the exact new tranche3 workspace")
    if getattr(args, "deadline_seconds", None) is None:
        args.deadline_seconds = STAGE_DEADLINE_SECONDS[args.stage]
    if type(args.deadline_seconds) is not int or not MINIMUM_DEADLINE_SECONDS <= args.deadline_seconds <= STAGE_DEADLINE_SECONDS[args.stage]:
        raise ValueError("the whole run needs one bounded aggregate host deadline")
    shared.owned_local_path(ROOT, args.output)
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("output already exists; inspect owned state, never duplicate/resume automatically")
    for field in ("source_manifest", "checkset", "package_plan", "handoffs"):
        expected = getattr(args, field + "_sha256")
        if go[field + "_sha256"] != expected:
            raise ValueError("go does not bind all requested input manifests")
        frozen_json(getattr(args, field), expected)
    selected = source.validate_manifest(frozen_json(args.source_manifest, args.source_manifest_sha256))
    plan = provision.validate_plan(frozen_json(args.package_plan, args.package_plan_sha256))
    # The executable check set is validated here, before any Session/VM exists.
    checkset = validate_stage_checkset(args.stage, frozen_json(args.checkset, args.checkset_sha256))
    if checkset["source_manifest_sha256"] != args.source_manifest_sha256:
        raise ValueError("check set does not bind the frozen source manifest handoff")
    if args.stage == 1 and any(checkset["package_pins"].get(name) != version for name, version in plan["roots"].items()):
        raise ValueError("check set does not verify every pinned provisioned package root")
    required = required_sources(args.stage, checkset)
    missing = sorted(required - set(selected["files"]))
    if missing:
        raise ValueError(f"frozen source closure is missing executable inputs: {missing[:8]}")
    unenforced = sorted(required - set(selected["required_files"]))
    if unenforced:
        raise ValueError(f"executable inputs are not enforced required sources: {unenforced[:8]}")
    handoffs = frozen_json(args.handoffs, args.handoffs_sha256)
    if set(handoffs) != {"schema_version", "lanes"} or handoffs["schema_version"] != "poseidon.linux-python-handoffs.v1" or not {"platform", "acquisition"} <= set(handoffs["lanes"]):
        raise ValueError("platform and acquisition frozen handoffs are required")
    for lane, entry in handoffs["lanes"].items():
        if type(entry) is not dict or set(entry) != {"manifest", "manifest_sha256", "files"} or type(entry["files"]) is not dict or not entry["files"]:
            raise ValueError("invalid normalized source handoff")
        frozen_json(Path(entry["manifest"]), entry["manifest_sha256"])
        for name, digest in entry["files"].items():
            source.safe_name(name)
            if selected["files"].get(name, {}).get("sha256") != digest:
                raise ValueError(f"full-source closure contradicts {lane} freeze: {name}")
    if args.stage == 2:
        if args.tool_plan is None or go["tool_plan_sha256"] != args.tool_plan_sha256:
            raise ValueError("Stage2 requires a frozen official tool/interpreter/lock plan")
        locked_env.validate_plan(frozen_json(args.tool_plan, args.tool_plan_sha256))
        if checkset["tool_plan_sha256"] != args.tool_plan_sha256:
            raise ValueError("Stage2 check set does not bind the frozen tool plan")
        previous = go["stage1_result"]
        if type(previous) is not dict or set(previous) != {"path", "sha256"}:
            raise ValueError("Stage2 requires completed stopped Stage1 evidence")
        path = shared.owned_local_path(ROOT, Path(previous["path"]))
        if not path.parent.name.startswith("linux-python-env-tranche3-"):
            raise ValueError("Stage1 evidence must belong to a new tranche3 run")
        result = frozen_json(path, previous["sha256"])
        if result.get("owner") != OWNER or result.get("stage") != 1 or result.get("state") != "passed-stage1-debian-python" or result.get("cleanup_ok") is not True or result.get("source_manifest_sha256") != args.source_manifest_sha256:
            raise ValueError("Stage1 must pass, retain the same frozen sources and stop/reap before Stage2")
        if result.get("run_id") == go["run_id"] or result.get("output") == str(args.output) or result.get("runtime") == str(args.output):
            raise ValueError("Stage2 needs a new run identity and workspace, never a Stage1/Task18 reuse")
        proof = path.parent / "cleanup-process-proof.json"
        if not proof.is_file() or proof.is_symlink():
            raise ValueError("Stage1 owned-process cleanup proof is missing")
        cleanup = source.strict_json(proof.read_bytes())
        if cleanup.get("runtime") != result.get("runtime") or cleanup.get("remaining_owned_processes") != []:
            raise ValueError("Stage1 owned VM/control processes were not proven stopped and reaped")
        if type(cleanup.get("instances")) is not list or not cleanup["instances"] or any(row.get("status", "").lower() != "stopped" for row in cleanup["instances"]):
            raise ValueError("Stage1 VM is not proven stopped; Stage2 needs a separate new VM")
    elif args.tool_plan is not None or go["tool_plan_sha256"] is not None or go["stage1_result"] is not None:
        raise ValueError("Stage1 must not reuse another VM or run locked tool provisioning")
    source.verify(ROOT, selected, exact=False)
    return go, selected


class Session(shared.Session):
    """Reuse tested Lima control/stop/reap methods, not its Task18 run method."""
    def __init__(self, args, go: dict):
        self.args = args
        self.cache = shared.owned_local_path(ROOT, CACHE)
        self.output = shared.owned_local_path(ROOT, args.output)
        if self.output.exists():
            raise ValueError("only a new owned tranche3 output is allowed")
        self.output.mkdir(mode=0o700, parents=True)
        self.runtime = Path(tempfile.mkdtemp(prefix="pp3-", dir="/tmp")).resolve()
        for part in ("home", "lima", "tmp"):
            (self.runtime / part).mkdir(mode=0o700)
        self.run_id = go["run_id"]
        self.started = time.monotonic()
        self.deadline_seconds = args.deadline_seconds
        self.env = shared.isolated_environment(self.cache, self.runtime)
        self.limactl = self.cache / "tools/bin/limactl"
        self.records = []
        self.pending = None
        self.deferred = 0
        self.may_exist = False
        self.cleanup_ok = False
        self.progress_counter = 0
        self.guest_root = "/home/builder/python-source-" + self.run_id
        self.identity = {"owner": OWNER, "stage": args.stage, "run_id": self.run_id, "runtime": str(self.runtime),
                         "output": str(self.output), "cache": str(self.cache), "instance": shared.VM_NAME,
                         "controller_pid": os.getpid(), "controller_pgid": os.getpgrp(), "guest_source": self.guest_root,
                         "go_sha256": args.go_sha256, "deadline_seconds": self.deadline_seconds}
        shared.write_new(self.runtime / "owner.json", self.identity)
        shared.write_new(self.output / "session.json", self.identity)
        print(json.dumps({"session_created_no_vm_started": self.identity}), flush=True)

    def budget(self, wanted: int, *, reserve: int = CLEANUP_RESERVE_SECONDS) -> int:
        """Clamp one step to what is left of the aggregate deadline.

        The reserve keeps collection, source re-verification and the owned
        stop/reap inside the same bound; a step is refused, never truncated to
        an unusable deadline, once the run has spent its budget.
        """
        remaining = self.deadline_seconds - (time.monotonic() - self.started) - reserve
        if remaining < 30:
            raise shared.EnvironmentError("aggregate host deadline reached before the next bounded step")
        return int(min(wanted, remaining))

    def milestone(self, state: str) -> None:
        self.progress_counter += 1
        record = self.identity | {"state": state, "at": datetime.now(timezone.utc).isoformat(), "control_commands": len(self.records)}
        shared.write_new(self.output / f"progress-{self.progress_counter:03d}.json", record)
        print(json.dumps(record, sort_keys=True), flush=True)

    def preflight_and_boot(self) -> dict:
        self.milestone("verify-cache-and-host-before-any-vm")
        host = shared.host_preflight(ROOT)
        pins = shared.verify_cache(self.cache)
        for target in (self.cache / "downloads" / shared.LIMA_ARCHIVE, self.limactl):
            attrs = subprocess.run(["/usr/bin/xattr", str(target)], env=self.env, capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()
            if "com.apple.quarantine" in attrs:
                raise ValueError("quarantine present; no bypass/removal is supported")
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(self.limactl)], env=self.env, check=True, timeout=20)
        if "2.2.0" not in self.call(["--version"], 20).stdout or self.listing():
            raise ValueError("wrong Lima version or nonempty new owned Lima home")
        config = self.output / "lima.yaml"
        config.write_text(shared.configuration(self.cache / "downloads" / shared.IMAGE_NAME, self.run_id))
        self.call(["validate", str(config)], 30)
        shared.host_preflight(ROOT)  # Recheck >=12GiB immediately before create/start.
        self.milestone("create-and-start-new-owned-vm")
        self.may_exist = True
        self.call(["create", "--tty=false", "--mount-none", "--name=" + shared.VM_NAME, str(config)], self.budget(120))
        self.call(["start", "--tty=false", "--timeout=180s", shared.VM_NAME], self.budget(210))
        state = self.listing()
        shared.write_new(self.output / "running-instance.json", {"instances": state})
        audit = self.check_running(state)
        identity = json.loads(self.guest(["python3", "-c", "import os,platform,json;print(json.dumps({'system':platform.system(),'machine':platform.machine(),'uid':os.getuid(),'kernel':platform.release()}))"], 30).stdout)
        if identity["system"] != "Linux" or identity["machine"] != "aarch64" or identity["uid"] == 0:
            raise ValueError("new guest must be unprivileged Linux aarch64")
        return {"host": host, "pins": pins, "guest": identity, "host_isolation_audit": audit}

    def transfer(self, selected: dict) -> None:
        self.milestone("transfer-exact-frozen-source-closure")
        archive = self.output / "source.tar"
        source.freeze(ROOT, selected, self.output / "frozen-source", archive)
        payloads = {"source-helper.py": self.output / "frozen-source/scripts/assurance/linux_python_env/source.py",
                    "sources.json": self.args.source_manifest, "checks.json": self.args.checkset,
                    "packages.json": self.args.package_plan, "source.tar": archive}
        if self.args.stage == 2:
            payloads["tools.json"] = self.args.tool_plan
        hashes = {}
        for name, path in payloads.items():
            target = "/home/builder/" + self.run_id + "-" + name
            self.call(["copy", "--tty=false", "--backend=scp", str(path), shared.VM_NAME + ":" + target], self.budget(600))
            hashes[self.run_id + "-" + name] = source.sha256(path)
        self.check_guest_sources("/home/builder", hashes)
        self.guest(["python3", "/home/builder/" + self.run_id + "-source-helper.py", "--action", "unpack", "--manifest", self.input("sources"), "--manifest-sha256", self.args.source_manifest_sha256,
                    "--archive", "/home/builder/" + self.run_id + "-source.tar", "--archive-sha256", source.sha256(archive), "--destination", self.guest_root], self.budget(600))
        # New guest source tree becomes read-only. Only its new .local output
        # directory remains builder-writable; no original repository is mounted.
        code = """import os,pathlib,sys
root=pathlib.Path(sys.argv[1]); assert os.getuid()==0 and root.is_dir() and not root.is_symlink()
for directory,dirs,files in os.walk(root,followlinks=False):
 for name in dirs+files: assert not (pathlib.Path(directory)/name).is_symlink()
 for name in files:
  p=pathlib.Path(directory)/name;os.chown(p,0,0);p.chmod(0o444)
 os.chown(directory,0,0);pathlib.Path(directory).chmod(0o555)
local=root/'.local';local.mkdir(mode=0o700);os.chown(local,1000,1000)
"""
        self.guest(["sudo", "-n", "python3", "-c", code, self.guest_root], 120)

    def input(self, name: str) -> str:
        return "/home/builder/" + self.run_id + "-" + name + ".json"

    def clean_guest(self, module: str, arguments: list[str], *, timeout: int, root: bool = False) -> str:
        clean = ["env", "-i", "PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C", "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1", "PYTHONPATH=" + self.guest_root]
        timeout = self.budget(timeout)
        command = [*(["sudo", "-n"] if root else []), *clean, "timeout", "--signal=TERM", "--kill-after=20s", str(timeout) + "s", "python3", "-m", module, *arguments]
        return self.guest(command, timeout + 45).stdout

    def verify_sources(self) -> None:
        self.clean_guest("scripts.assurance.linux_python_env.source", ["--action", "verify", "--source", self.guest_root, "--manifest", self.input("sources"), "--manifest-sha256", self.args.source_manifest_sha256], timeout=300)

    def execute(self, selected: dict) -> dict:
        previous = {sig: signal.signal(sig, self.interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
        result = self.identity | {"source_manifest_sha256": self.args.source_manifest_sha256, "checkset_sha256": self.args.checkset_sha256,
                                  "state": "running", "cleanup_ok": False, "release_authorized": False, "physical_operations_performed": False}
        collect = []
        error = None
        sources_transferred = False
        try:
            result.update(self.preflight_and_boot())
            self.transfer(selected)
            sources_transferred = True
            package_records = "/var/lib/poseidon-python-" + self.run_id
            collect.append((package_records, "guest-packages"))
            self.milestone("provision-pinned-snapshot-packages-guest-root-only")
            self.clean_guest("scripts.assurance.linux_python_env.provision", ["--run-id", self.run_id, "--plan", self.input("packages"), "--plan-sha256", self.args.package_plan_sha256, "--output", package_records], timeout=5400, root=True)
            self.verify_sources()
            check_args = ["--run-id", self.run_id, "--source", self.guest_root, "--source-manifest", self.input("sources"), "--source-manifest-sha256", self.args.source_manifest_sha256,
                          "--checkset", self.input("checks"), "--checkset-sha256", self.args.checkset_sha256]
            if self.args.stage == 2:
                workspace = "/home/builder/python-locked-work-" + self.run_id
                environment_records = "/home/builder/python-locked-records-" + self.run_id
                collect.append((environment_records, "guest-locked-environments"))
                self.milestone("provision-official-pinned-tools-interpreters-and-wheel-only-locks")
                self.clean_guest("scripts.assurance.linux_python_env.locked_env", ["--run-id", self.run_id, "--source", self.guest_root, "--plan", self.input("tools"), "--plan-sha256", self.args.tool_plan_sha256, "--workspace", workspace, "--records", environment_records], timeout=5400)
                self.verify_sources()
                environment_file = environment_records + "/environments.json"
                digest = self.guest(["python3", "-c", "import hashlib,pathlib,sys;print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())", environment_file], 30).stdout.strip()
                check_args += ["--environments", environment_file, "--environments-sha256", digest]
            check_records = "/home/builder/python-checks-" + self.run_id
            collect.append((check_records, "guest-checks"))
            self.milestone("execute-reviewed-python-checks-unprivileged")
            module = "scripts.assurance.linux_python_env.guest_checks" if self.args.stage == 1 else "scripts.assurance.linux_python_env.locked_checks"
            self.clean_guest(module, [*check_args, "--output", check_records], timeout=14400)
            self.verify_sources()
            result["state"] = "checks-finished-collection-cleanup-pending"
        except BaseException as exc:
            error = exc
            result["state"] = "failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if self.pending is None:
                for path, label in collect:
                    try:
                        self.milestone("collect-" + label)
                        self.collect_guest_tree(path, label)
                    except BaseException as exc:
                        error = error or exc
                        result.setdefault("collection_errors", []).append(f"{label}: {exc}")
            elif collect:
                result["uncopied_guest_evidence_retained_in_stopped_owned_disk"] = str(self.runtime / "lima" / shared.VM_NAME / "disk")
            try:
                source.verify(ROOT, selected, exact=False)
                if (self.output / "frozen-source").exists():
                    source.verify(self.output / "frozen-source", selected)
                result["source_hashes_preserved"] = True
            except BaseException as exc:
                error = error or exc
                result["source_preservation_error"] = str(exc)
            try:
                self.milestone("stop-and-reap-only-owned-vm-control-processes")
                self.stop()
            except BaseException as exc:
                if not isinstance(exc, shared.Cancelled) or not self.cleanup_ok:
                    error = error or exc
                    result["cleanup_error"] = str(exc)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            result["cleanup_ok"] = self.cleanup_ok
            result["commands"] = self.records
            result["finished_at"] = datetime.now(timezone.utc).isoformat()
            copied = self.output / "guest-checks/result.json"
            if error is None and self.cleanup_ok and sources_transferred and copied.is_file():
                guest_result = source.strict_json(copied.read_bytes())
                result["guest_check_result"] = guest_result
                if guest_result.get("state") != "checks-complete-host-collection-and-vm-stop-required":
                    error = ValueError("guest did not report a complete reviewed check set")
                else:
                    result["state"] = "passed-stage1-debian-python" if self.args.stage == 1 else "passed-stage2-locked-python"
            else:
                error = error or ValueError("guest records or complete cleanup proof missing")
            if error is not None:
                result["state"] = "failed"
                result.setdefault("error", str(error))
            shared.write_new(self.output / "result.json", result)
        if error is not None:
            raise ValueError(result["error"])
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=int, choices=(1, 2), required=True)
    parser.add_argument("--output", type=Path, required=True)
    for field in ("go", "source-manifest", "checkset", "package-plan", "handoffs"):
        parser.add_argument("--" + field, type=Path, required=True)
        parser.add_argument("--" + field + "-sha256", required=True)
    parser.add_argument("--tool-plan", type=Path)
    parser.add_argument("--tool-plan-sha256")
    parser.add_argument("--deadline-seconds", type=int, help="aggregate host deadline for the whole run")
    args = parser.parse_args()
    try:
        go, selected = validate_go(args)
        session = Session(args, go)
        result = session.execute(selected)
        print(json.dumps({"state": result["state"], "result": str(args.output / "result.json"), "cleanup_ok": result["cleanup_ok"]}))
        return 0
    except (ValueError, OSError, shared.EnvironmentError, subprocess.SubprocessError) as exc:
        print(f"Tranche3 Linux Python verification refused/failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
