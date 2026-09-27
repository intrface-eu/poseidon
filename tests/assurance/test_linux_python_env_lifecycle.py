"""Synthetic host lifecycle tests for the tranche3 Python verification runner.

Every test builds its own frozen workspace in a temporary directory and stubs
the guest-facing steps. Lima is never invoked, no VM is created or reused, no
socket is opened and no owned subprocess is left behind: `subprocess.Popen`,
`subprocess.run` and `urlopen` all raise if a test reaches them.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.assurance.linux_capture_env import runner as shared
from scripts.assurance.linux_python_env import guest_checks, runner as lifecycle, source

GUEST_COMPLETE = "checks-complete-host-collection-and-vm-stop-required"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class Workspace:
    """A frozen synthetic project, manifest, plan, check set and go record."""

    def __init__(self, base: Path, *, stage: int = 1):
        self.stage = stage
        self.base = base
        self.root = base / "project"
        self.inputs = base / "inputs"
        self.inputs.mkdir(parents=True)
        (self.root / ".local").mkdir(parents=True)
        self.files: dict[str, bytes] = {}
        for name in lifecycle.GUEST_HELPERS[stage]:
            self.write(name, f"# SYNTHETIC helper {name}\n".encode())
        self.coverage = "tests/assurance/test_synthetic_stage.py"
        self.write(self.coverage, b"# SYNTHETIC selected test module\n")
        self.write("scripts/task_graph.py", b"# SYNTHETIC task graph helper\n")
        self.manifest = {"schema_version": "poseidon.linux-python-sources.v1",
                         "files": {name: {"sha256": digest(raw), "size": len(raw)} for name, raw in self.files.items()},
                         "required_files": sorted(self.files),
                         "coverage_roots": ["scripts/assurance", "scripts/task_graph.py", "tests/assurance"]}
        self.plan = {"schema_version": "poseidon.linux-python-packages.v1", "snapshot": "20260901T000000Z",
                     "roots": {"make": "4.4.1-2"},
                     "indexes": {name: format(index, "064x") for index, name in enumerate((
                         "snapshot.debian.org_archive_debian_20260901T000000Z_dists_trixie_main_binary-arm64_Packages",
                         "snapshot.debian.org_archive_debian_20260901T000000Z_dists_trixie-updates_main_binary-arm64_Packages",
                         "snapshot.debian.org_archive_debian-security_20260901T000000Z_dists_trixie-security_main_binary-arm64_Packages"), start=1)}}
        self.checkset = self.stage1_checkset() if stage == 1 else self.stage2_checkset()
        self.tool_plan = None if stage == 1 else self.stage2_tool_plan()
        self.handoffs = {"schema_version": "poseidon.linux-python-handoffs.v1", "lanes": {}}
        for lane in ("platform", "acquisition"):
            path = self.freeze(lane + "-freeze.json", {"lane": lane, "state": "SYNTHETIC frozen handoff"})
            self.handoffs["lanes"][lane] = {"manifest": str(path), "manifest_sha256": source.sha256(path),
                                            "files": {self.coverage: self.manifest["files"][self.coverage]["sha256"]}}
        self.paths = {}
        for name in ("manifest", "plan", "checkset", "handoffs", *(("tool_plan",) if stage == 2 else ())):
            self.paths[name] = self.freeze(name + ".json", getattr(self, name))
        self.output = self.root / ".local/linux-python-env-tranche3-synthetic"
        self.go_value = {"schema_version": "poseidon.linux-python-go.v1", "stage": stage, "run_id": "lp3-synthetic-new",
                         "output": str(self.output), "source_manifest_sha256": source.sha256(self.paths["manifest"]),
                         "checkset_sha256": source.sha256(self.paths["checkset"]),
                         "package_plan_sha256": source.sha256(self.paths["plan"]),
                         "tool_plan_sha256": None if stage == 1 else source.sha256(self.paths["tool_plan"]),
                         "handoffs_sha256": source.sha256(self.paths["handoffs"]),
                         "expires_unix": int(time.time()) + 3600, "release_authorized": False, "stage1_result": None}
        if stage == 2:
            self.go_value["stage1_result"] = self.stage1_evidence()
        self.paths["go"] = self.freeze("go.json", self.go_value)

    def write(self, name: str, raw: bytes) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.files[name] = raw

    def freeze(self, name: str, value: dict) -> Path:
        path = self.inputs / name
        path.write_text(json.dumps(value, sort_keys=True))
        return path

    def stage1_checkset(self) -> dict:
        return {"schema_version": "poseidon.linux-python-checkset.v1", "python_version": "3.13.5",
                "source_manifest_sha256": digest(json.dumps(self.manifest, sort_keys=True).encode()),
                "omissions": [{"paths": ["tests/api", "tests/nereid"], "reason": "SYNTHETIC locked lanes stay Stage2"}],
                "package_pins": {"make": "4.4.1-2", "python3": "3.13.5-1"},
                "commands": [{"id": "synthetic-stage1", "timeout_seconds": 60, "environment": {},
                              "argv": ["/usr/bin/python3", "-m", "scripts.assurance.linux_python_env.suite",
                                       "--root", "tests/assurance", "--pattern", "test_synthetic_stage.py", "--minimum", "1"],
                              "coverage": [self.coverage]}]}

    def stage2_checkset(self) -> dict:
        return {"schema_version": "poseidon.linux-python-locked-checkset.v1",
                "source_manifest_sha256": digest(json.dumps(self.manifest, sort_keys=True).encode()),
                "tool_plan_sha256": digest(json.dumps(self.stage2_tool_plan(), sort_keys=True).encode()),
                "omissions": [{"paths": ["tests/acoustic/linux_backend_abi"], "reason": "SYNTHETIC separate native gate"}],
                "commands": [{"id": "synthetic-stage2", "lane": "api", "timeout_seconds": 60, "environment": {},
                              "argv": ["{python}", "scripts/assurance/run_unittest.py", "-s", "tests/assurance", "-p", "test_synthetic_stage.py"],
                              "coverage": [self.coverage]}]}

    def stage2_tool_plan(self) -> dict:
        from scripts.assurance.linux_python_env import artifacts, locked_env
        return {"schema_version": "poseidon.linux-python-locked-tools.v1", "uv": copy.deepcopy(artifacts.UV_PIN),
                "python": copy.deepcopy(artifacts.PYTHON_PINS),
                "locks": {lane: {"project": project, "python": version, "lock_sha256": "a" * 64, "pyproject_sha256": "b" * 64}
                          for lane, (project, version) in locked_env.LANES.items()}}

    def stage1_evidence(self, **changes) -> dict:
        directory = self.root / ".local/linux-python-env-tranche3-stage1"
        directory.mkdir(parents=True, exist_ok=True)
        runtime = str(self.base / "runtime-stage1")
        result = {"owner": lifecycle.OWNER, "stage": 1, "run_id": "lp3-synthetic-stage1", "state": "passed-stage1-debian-python",
                  "cleanup_ok": True, "source_manifest_sha256": source.sha256(self.paths["manifest"]),
                  "runtime": runtime, "output": str(directory)}
        result.update(changes.pop("result", {}))
        proof = {"runtime": runtime, "remaining_owned_processes": [], "instances": [{"name": "abi", "status": "Stopped"}]}
        proof.update(changes.pop("proof", {}))
        (directory / "result.json").write_text(json.dumps(result, sort_keys=True))
        (directory / "cleanup-process-proof.json").write_text(json.dumps(proof, sort_keys=True))
        return {"path": str(directory / "result.json"), "sha256": digest(json.dumps(result, sort_keys=True).encode())}

    def set_output(self, path: Path) -> None:
        self.output = path
        self.go_value["output"] = str(path)
        self.paths["go"] = self.freeze("go.json", self.go_value)

    def refreeze(self, name: str, value: dict) -> None:
        setattr(self, name, value)
        self.paths[name] = self.freeze(name + ".json", value)
        field = {"manifest": "source_manifest_sha256", "plan": "package_plan_sha256", "checkset": "checkset_sha256",
                 "handoffs": "handoffs_sha256", "tool_plan": "tool_plan_sha256"}[name]
        self.go_value[field] = source.sha256(self.paths[name])
        self.paths["go"] = self.freeze("go.json", self.go_value)

    def args(self, **changes) -> argparse.Namespace:
        values = {"stage": self.stage, "output": self.output, "go": self.paths["go"], "go_sha256": source.sha256(self.paths["go"]),
                  "source_manifest": self.paths["manifest"], "source_manifest_sha256": source.sha256(self.paths["manifest"]),
                  "checkset": self.paths["checkset"], "checkset_sha256": source.sha256(self.paths["checkset"]),
                  "package_plan": self.paths["plan"], "package_plan_sha256": source.sha256(self.paths["plan"]),
                  "handoffs": self.paths["handoffs"], "handoffs_sha256": source.sha256(self.paths["handoffs"]),
                  "tool_plan": self.paths.get("tool_plan"), "deadline_seconds": None}
        values["tool_plan_sha256"] = source.sha256(values["tool_plan"]) if values["tool_plan"] else None
        values.update(changes)
        return argparse.Namespace(**values)


class LifecycleTestCase(unittest.TestCase):
    stage = 1

    def setUp(self):
        for module, name in ((subprocess, "run"), (subprocess, "Popen"), (urllib.request, "urlopen")):
            patcher = patch.object(module, name, side_effect=AssertionError("synthetic test must not start Lima or the network"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-synthetic-lifecycle-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.workspace = Workspace(self.base, stage=self.stage)
        self.enter(patch.object(lifecycle, "ROOT", self.workspace.root))
        self.enter(patch.object(lifecycle, "CACHE", self.workspace.root / ".local/synthetic-cache"))
        self.runtimes = []

        def owned_runtime(**_):
            path = self.base / f"runtime-{len(self.runtimes):02d}"
            path.mkdir()
            self.runtimes.append(path)
            return str(path)

        self.enter(patch.object(lifecycle.tempfile, "mkdtemp", side_effect=owned_runtime))

    def enter(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def refresh_checkset(self):
        checkset = dict(self.workspace.checkset)
        checkset["source_manifest_sha256"] = source.sha256(self.workspace.paths["manifest"])
        self.workspace.refreeze("checkset", checkset)

    def valid_args(self, **changes) -> argparse.Namespace:
        self.refresh_checkset()
        return self.workspace.args(**changes)


class GoValidationTests(LifecycleTestCase):
    def test_complete_frozen_inputs_are_accepted(self):
        go, selected = lifecycle.validate_go(self.valid_args())
        self.assertEqual(go["run_id"], "lp3-synthetic-new")
        self.assertEqual(set(selected["files"]), set(self.workspace.manifest["files"]))

    def test_stale_or_unbound_check_set_refuses(self):
        checkset = copy.deepcopy(self.workspace.checkset)
        checkset["source_manifest_sha256"] = "a" * 64
        self.workspace.refreeze("checkset", checkset)
        with self.assertRaisesRegex(ValueError, "bind the frozen source manifest"):
            lifecycle.validate_go(self.workspace.args())

    def test_malformed_check_set_schema_refuses_before_any_session(self):
        self.refresh_checkset()
        proposal = copy.deepcopy(self.workspace.checkset)
        proposal["commands"][0]["expected_exit"] = 0
        self.workspace.refreeze("checkset", proposal)
        with patch.object(lifecycle, "Session", side_effect=AssertionError("no VM session may be constructed")):
            with self.assertRaises(ValueError):
                lifecycle.validate_go(self.workspace.args())
            argv = ["runner", "--stage", "1", "--output", str(self.workspace.output)]
            for field, key in (("go", "go"), ("source-manifest", "manifest"), ("checkset", "checkset"),
                               ("package-plan", "plan"), ("handoffs", "handoffs")):
                path = self.workspace.paths[key]
                argv += ["--" + field, str(path), "--" + field + "-sha256", source.sha256(path)]
            with patch.object(sys, "argv", argv):
                self.assertEqual(lifecycle.main(), 2)
        self.assertFalse(self.workspace.output.exists())

    def test_missing_or_unenforced_helper_closure_refuses(self):
        manifest = copy.deepcopy(self.workspace.manifest)
        del manifest["files"]["scripts/assurance/linux_python_env/suite.py"]
        manifest["required_files"] = sorted(manifest["files"])
        self.workspace.refreeze("manifest", manifest)
        with self.assertRaisesRegex(ValueError, "missing executable inputs"):
            lifecycle.validate_go(self.valid_args())
        manifest = copy.deepcopy(self.workspace.manifest)
        manifest["files"]["scripts/assurance/linux_python_env/suite.py"] = {"sha256": digest(b"# SYNTHETIC helper scripts/assurance/linux_python_env/suite.py\n"), "size": 62}
        manifest["required_files"] = [name for name in sorted(manifest["files"]) if name != "scripts/assurance/run_command.py"]
        self.workspace.refreeze("manifest", manifest)
        with self.assertRaisesRegex(ValueError, "not enforced required sources"):
            lifecycle.validate_go(self.valid_args())

    def test_selected_test_module_must_be_part_of_the_frozen_closure(self):
        checkset = copy.deepcopy(self.workspace.checkset)
        checkset["commands"][0]["argv"][6] = "test_absent_module.py"
        checkset["commands"][0]["coverage"] = ["tests/assurance/test_absent_module.py"]
        checkset["source_manifest_sha256"] = source.sha256(self.workspace.paths["manifest"])
        self.workspace.refreeze("checkset", checkset)
        with self.assertRaisesRegex(ValueError, "missing executable inputs"):
            lifecycle.validate_go(self.workspace.args())

    def test_check_set_must_verify_every_pinned_package_root(self):
        self.refresh_checkset()
        checkset = copy.deepcopy(self.workspace.checkset)
        checkset["package_pins"] = {"python3": "3.13.5-1"}
        self.workspace.refreeze("checkset", checkset)
        with self.assertRaisesRegex(ValueError, "pinned provisioned package root"):
            lifecycle.validate_go(self.workspace.args())
        checkset["package_pins"] = {"make": "9.9.9-1", "python3": "3.13.5-1"}
        self.workspace.refreeze("checkset", checkset)
        with self.assertRaises(ValueError):
            lifecycle.validate_go(self.workspace.args())

    def test_source_hash_drift_and_handoff_contradictions_refuse(self):
        args = self.valid_args()
        (self.workspace.root / self.workspace.coverage).write_bytes(b"# SYNTHETIC changed after the freeze\n")
        with self.assertRaises(source.SourceError):
            lifecycle.validate_go(args)
        (self.workspace.root / self.workspace.coverage).write_bytes(self.workspace.files[self.workspace.coverage])
        handoffs = copy.deepcopy(self.workspace.handoffs)
        handoffs["lanes"]["platform"]["files"][self.workspace.coverage] = "f" * 64
        self.workspace.refreeze("handoffs", handoffs)
        with self.assertRaisesRegex(ValueError, "contradicts platform freeze"):
            lifecycle.validate_go(self.valid_args())

    def test_expired_wrong_stage_or_release_claiming_go_refuses(self):
        for change in ({"expires_unix": int(time.time()) - 1}, {"release_authorized": True}, {"stage": 2},
                       {"run_id": "task18-combined-002"}, {"schema_version": "poseidon.linux-python-go.v2"},
                       {"output": "/tmp/not-an-owned-workspace"}):
            value = dict(self.workspace.go_value) | change
            path = self.workspace.freeze("go-variant.json", value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                lifecycle.validate_go(self.valid_args(go=path, go_sha256=source.sha256(path)))

    def test_go_must_bind_every_supplied_manifest_hash(self):
        args = self.valid_args()
        args.checkset_sha256 = "a" * 64
        with self.assertRaisesRegex(ValueError, "bind all requested input manifests"):
            lifecycle.validate_go(args)

    def test_existing_output_is_never_reused_or_resumed(self):
        self.workspace.output.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "already exists"):
            lifecycle.validate_go(self.valid_args())

    def test_aggregate_deadline_must_be_bounded(self):
        args = self.valid_args()
        lifecycle.validate_go(args)
        self.assertEqual(args.deadline_seconds, lifecycle.STAGE_DEADLINE_SECONDS[1])
        for value in (0, 60, lifecycle.STAGE_DEADLINE_SECONDS[1] + 1, 3600.5, "3600"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "aggregate host deadline"):
                lifecycle.validate_go(self.valid_args(deadline_seconds=value))
        args = self.valid_args(deadline_seconds=1800)
        lifecycle.validate_go(args)
        self.assertEqual(args.deadline_seconds, 1800)

    def test_stage1_may_not_carry_stage2_inputs(self):
        self.refresh_checkset()
        value = dict(self.workspace.go_value) | {"stage1_result": {"path": "/tmp/x", "sha256": "a" * 64}}
        path = self.workspace.freeze("go-reuse.json", value)
        with self.assertRaisesRegex(ValueError, "must not reuse another VM"):
            lifecycle.validate_go(self.workspace.args(go=path, go_sha256=source.sha256(path)))


class Stage2GateTests(LifecycleTestCase):
    stage = 2

    def test_stage2_accepts_a_stopped_reaped_stage1_and_a_new_workspace(self):
        go, _ = lifecycle.validate_go(self.valid_args())
        self.assertEqual(go["stage"], 2)

    def test_stage2_refuses_unfinished_unreaped_or_reused_stage1_evidence(self):
        cases = {
            "failed": {"result": {"state": "failed"}},
            "cleanup": {"result": {"cleanup_ok": False}},
            "other-owner": {"result": {"owner": "poseidon-linux-no-device-task18"}},
            "same-run": {"result": {"run_id": "lp3-synthetic-new"}},
            "different-sources": {"result": {"source_manifest_sha256": "a" * 64}},
            "processes-remain": {"proof": {"remaining_owned_processes": ["12345 limactl start"]}},
            "still-running": {"proof": {"instances": [{"name": "abi", "status": "Running"}]}},
            "foreign-proof": {"proof": {"runtime": "/tmp/other-runtime"}},
        }
        for name, change in cases.items():
            evidence = self.workspace.stage1_evidence(**change)
            value = dict(self.workspace.go_value) | {"stage1_result": evidence}
            path = self.workspace.freeze("go-stage2.json", value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                lifecycle.validate_go(self.valid_args(go=path, go_sha256=source.sha256(path)))
        self.workspace.stage1_evidence()
        missing = self.workspace.root / ".local/linux-python-env-tranche3-stage1/cleanup-process-proof.json"
        missing.unlink()
        with self.assertRaisesRegex(ValueError, "cleanup proof is missing"):
            lifecycle.validate_go(self.valid_args())

    def test_stage2_check_set_must_bind_the_frozen_tool_plan(self):
        self.refresh_checkset()
        self.workspace.stage1_evidence()
        checkset = copy.deepcopy(self.workspace.checkset)
        checkset["tool_plan_sha256"] = "c" * 64
        self.workspace.refreeze("checkset", checkset)
        value = dict(self.workspace.go_value)
        path = self.workspace.freeze("go-stage2-tool.json", value)
        with self.assertRaisesRegex(ValueError, "bind the frozen tool plan"):
            lifecycle.validate_go(self.workspace.args(go=path, go_sha256=source.sha256(path)))

    def test_task18_evidence_is_never_accepted_as_stage1(self):
        directory = self.workspace.root / ".local/linux-capture-env-task18-2026-09-08/combined-002"
        directory.mkdir(parents=True)
        result = {"owner": lifecycle.OWNER, "stage": 1, "run_id": "lc18-accepted", "state": "passed-stage1-debian-python",
                  "cleanup_ok": True, "source_manifest_sha256": source.sha256(self.workspace.paths["manifest"]),
                  "runtime": "/tmp/task18", "output": str(directory)}
        (directory / "result.json").write_text(json.dumps(result, sort_keys=True))
        value = dict(self.workspace.go_value) | {"stage1_result": {"path": str(directory / "result.json"), "sha256": digest(json.dumps(result, sort_keys=True).encode())}}
        path = self.workspace.freeze("go-task18.json", value)
        with self.assertRaisesRegex(ValueError, "new tranche3 run"):
            lifecycle.validate_go(self.valid_args(go=path, go_sha256=source.sha256(path)))


class SessionLifecycleTests(LifecycleTestCase):
    def session(self, output: Path | None = None, **changes):
        if output is not None:
            self.workspace.set_output(output)
        args = self.valid_args(**changes)
        go, selected = lifecycle.validate_go(args)
        session = lifecycle.Session(args, go)
        self.steps = []
        session.preflight_and_boot = lambda: (self.steps.append("preflight"), {"host": {"synthetic": True}})[1]
        session.transfer = lambda selected: self.steps.append("transfer")
        session.verify_sources = lambda: self.steps.append("verify-sources")
        session.clean_guest = lambda module, arguments, *, timeout, root=False: (self.steps.append(module.rsplit(".", 1)[-1]), "")[1]

        def collect(path, label):
            self.steps.append("collect-" + label)
            target = session.output / label
            target.mkdir(exist_ok=True)
            if label == "guest-checks":
                (target / "result.json").write_text(json.dumps({"state": GUEST_COMPLETE, "commands": []}, sort_keys=True))

        session.collect_guest_tree = collect

        def stop():
            self.steps.append("stop")
            session.cleanup_ok = True

        session.stop = stop
        return session, selected

    def result(self, session) -> dict:
        return json.loads((session.output / "result.json").read_text())

    def test_successful_run_requires_guest_records_and_proven_cleanup(self):
        session, selected = self.session()
        result = session.execute(selected)
        self.assertEqual(result["state"], "passed-stage1-debian-python")
        self.assertTrue(result["cleanup_ok"])
        self.assertTrue(result["source_hashes_preserved"])
        self.assertEqual(self.steps, ["preflight", "transfer", "provision", "verify-sources", "guest_checks",
                                      "verify-sources", "collect-guest-packages", "collect-guest-checks", "stop"])
        self.assertEqual(self.result(session)["state"], "passed-stage1-debian-python")
        self.assertTrue((session.output / "session.json").is_file())
        self.assertGreaterEqual(len(list(session.output.glob("progress-*.json"))), 4)

    def test_preflight_failure_stops_before_transfer_and_keeps_evidence(self):
        session, selected = self.session()

        def refuse():
            self.steps.append("preflight")
            raise shared.EnvironmentError("SYNTHETIC preflight refusal: less than12GiB free")

        session.preflight_and_boot = refuse
        with self.assertRaises(ValueError):
            session.execute(selected)
        self.assertEqual(self.steps, ["preflight", "stop"])
        record = self.result(session)
        self.assertEqual(record["state"], "failed")
        self.assertIn("preflight refusal", record["error"])
        self.assertFalse(record["release_authorized"])
        self.assertTrue((session.output / "session.json").is_file())

    def test_transfer_provision_and_check_failures_retain_collected_evidence(self):
        for step, expected_collections in (("transfer", []),
                                           ("provision", ["collect-guest-packages"]),
                                           ("checks", ["collect-guest-packages", "collect-guest-checks"])):
            with self.subTest(step=step):
                session, selected = self.session(output=self.workspace.output.with_name("linux-python-env-tranche3-" + step))
                if step == "transfer":
                    session.transfer = lambda selected: (_ for _ in ()).throw(shared.EnvironmentError("SYNTHETIC transfer failure"))
                else:
                    def guest(module, arguments, *, timeout, root=False, step=step):
                        self.steps.append(module.rsplit(".", 1)[-1])
                        if (step == "provision") == module.endswith("provision"):
                            raise ValueError(f"SYNTHETIC {step} failure")
                        return ""
                    session.clean_guest = guest
                with self.assertRaises(ValueError):
                    session.execute(selected)
                record = self.result(session)
                self.assertEqual(record["state"], "failed")
                self.assertIn("SYNTHETIC", record["error"])
                self.assertEqual([name for name in self.steps if name.startswith("collect-")], expected_collections)
                self.assertEqual(self.steps[-1], "stop")
                for label in expected_collections:
                    self.assertTrue((session.output / label.removeprefix("collect-")).is_dir())

    def test_incomplete_guest_record_is_not_a_pass(self):
        session, selected = self.session()

        def collect(path, label):
            self.steps.append("collect-" + label)
            target = session.output / label
            target.mkdir(exist_ok=True)
            if label == "guest-checks":
                (target / "result.json").write_text(json.dumps({"state": "failed"}, sort_keys=True))

        session.collect_guest_tree = collect
        with self.assertRaises(ValueError):
            session.execute(selected)
        self.assertEqual(self.result(session)["state"], "failed")

    def test_missing_guest_records_prevent_success(self):
        session, selected = self.session()
        session.collect_guest_tree = lambda path, label: self.steps.append("collect-" + label)
        with self.assertRaises(ValueError):
            session.execute(selected)
        record = self.result(session)
        self.assertEqual(record["state"], "failed")
        self.assertIn("guest records or complete cleanup proof missing", record["error"])

    def test_collection_failure_is_recorded_and_prevents_success(self):
        session, selected = self.session()

        def collect(path, label):
            self.steps.append("collect-" + label)
            raise shared.EnvironmentError(f"SYNTHETIC collection failure: {label}")

        session.collect_guest_tree = collect
        with self.assertRaises(ValueError):
            session.execute(selected)
        record = self.result(session)
        self.assertEqual(len(record["collection_errors"]), 2)
        self.assertEqual(record["state"], "failed")

    def test_cleanup_failure_prevents_success(self):
        session, selected = self.session()

        def stop():
            self.steps.append("stop")
            raise shared.EnvironmentError("SYNTHETIC owned VM/control processes remain after stop")

        session.stop = stop
        with self.assertRaises(ValueError):
            session.execute(selected)
        record = self.result(session)
        self.assertEqual(record["state"], "failed")
        self.assertFalse(record["cleanup_ok"])
        self.assertIn("processes remain", record["cleanup_error"])

    def test_incomplete_cleanup_without_error_still_prevents_success(self):
        session, selected = self.session()
        session.stop = lambda: self.steps.append("stop")
        with self.assertRaises(ValueError):
            session.execute(selected)
        record = self.result(session)
        self.assertFalse(record["cleanup_ok"])
        self.assertEqual(record["state"], "failed")

    def test_cancellation_skips_collection_and_retains_guest_evidence_on_the_owned_disk(self):
        session, selected = self.session()

        def guest(module, arguments, *, timeout, root=False):
            self.steps.append(module.rsplit(".", 1)[-1])
            session.interrupt(signal.SIGTERM, None)
            return ""

        session.clean_guest = guest
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with self.assertRaises(ValueError):
            session.execute(selected)
        record = self.result(session)
        self.assertEqual(record["state"], "failed")
        self.assertEqual(session.pending, signal.SIGTERM)
        self.assertNotIn("collection_errors", record)
        self.assertFalse([name for name in self.steps if name.startswith("collect-")])
        self.assertTrue(record["uncopied_guest_evidence_retained_in_stopped_owned_disk"].startswith(str(session.runtime)))
        self.assertEqual(self.steps[-1], "stop")
        self.assertEqual({sig: signal.getsignal(sig) for sig in previous}, previous)

    def test_aggregate_deadline_bounds_every_step_and_reserves_cleanup(self):
        session, selected = self.session(deadline_seconds=1800)
        self.assertEqual(session.deadline_seconds, 1800)
        self.assertEqual(session.budget(600), 600)
        self.assertLessEqual(session.budget(5400), 1800 - lifecycle.CLEANUP_RESERVE_SECONDS)
        session.started = time.monotonic() - 1800
        with self.assertRaisesRegex(shared.EnvironmentError, "aggregate host deadline"):
            session.budget(60)
        session.clean_guest = lifecycle.Session.clean_guest.__get__(session)
        session.guest = lambda command, timeout: (_ for _ in ()).throw(AssertionError("no guest command after the deadline"))
        with self.assertRaises(ValueError):
            session.execute(selected)
        record = self.result(session)
        self.assertEqual(record["state"], "failed")
        self.assertIn("aggregate host deadline", record["error"])

    def test_session_stays_inside_its_owned_runtime_and_reuses_the_reviewed_reap(self):
        session, _ = self.session()
        self.assertIs(lifecycle.Session.stop, shared.Session.stop)
        self.assertIs(lifecycle.Session.interrupt, shared.Session.interrupt)
        self.assertIs(lifecycle.Session.call, shared.Session.call)
        self.assertEqual(session.identity["controller_pid"], os.getpid())
        self.assertEqual(session.identity["controller_pgid"], os.getpgrp())
        self.assertEqual(session.identity["owner"], lifecycle.OWNER)
        self.assertTrue(Path(session.identity["output"]).is_relative_to(self.workspace.root / ".local"))
        self.assertEqual(Path(session.identity["runtime"]), self.runtimes[-1])
        self.assertEqual(session.identity["instance"], shared.VM_NAME)
        self.assertFalse(session.records)
        self.assertFalse(session.cleanup_ok)
        self.assertTrue(session.guest_root.startswith("/home/builder/python-source-lp3-"))

    def test_a_second_session_never_reuses_an_existing_output(self):
        session, _ = self.session()
        args = self.valid_args()
        with self.assertRaisesRegex(ValueError, "new owned tranche3 output"):
            lifecycle.Session(args, self.workspace.go_value)


class GuestCheckBoundaryTests(LifecycleTestCase):
    def test_guest_checks_refuse_to_run_off_a_marked_linux_guest(self):
        args = argparse.Namespace(run_id="lp3-synthetic", source=self.workspace.root,
                                  source_manifest=self.workspace.paths["manifest"],
                                  source_manifest_sha256=source.sha256(self.workspace.paths["manifest"]),
                                  checkset=self.workspace.paths["checkset"],
                                  checkset_sha256=source.sha256(self.workspace.paths["checkset"]),
                                  output=self.base / "records")
        with self.assertRaises(ValueError) as refusal:
            guest_checks.run(args)
        # Off the guest the platform check refuses; inside a real Debian aarch64 guest the
        # shared guard refuses on the marker or privilege check instead. Both are refusals
        # raised before any path is created, which is what this test protects.
        self.assertRegex(str(refusal.exception), r"Linux aarch64 guest|Debian VERSION_ID|root preparation required|must run unprivileged|guest marker")
        self.assertFalse((self.base / "records").exists())

    def test_guest_command_environment_is_bounded_to_the_run_records(self):
        environment = guest_checks.command_environment(self.workspace.root, self.base / "records")
        self.assertEqual(environment["PATH"], "/usr/bin:/bin")
        self.assertTrue(environment["HOME"].startswith(str(self.base / "records")))
        self.assertTrue(environment["TMPDIR"].startswith(str(self.base / "records")))
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertNotIn("SSH_AUTH_SOCK", environment)
        self.assertEqual(environment["PYTEST_ADDOPTS"], f"--basetemp={self.base / 'records' / 'tmp' / 'pytest-basetemp'}")

class PytestRecordsHygieneTests(unittest.TestCase):
    """A real pytest run under the guest command environment, outside the Lima/network
    mocks: the basetemp sits inside the records tree, is removed by run_pytest.py after
    the session, and no symlink (pytest-current or a per-test "...current") remains
    anywhere under the records; the shared evidence manifest refused one in run
    lp3-stage2-004."""

    def test_pytest_under_the_guest_environment_leaves_no_symlink_in_the_records(self):
        try:
            import pytest  # noqa: F401
        except ImportError:
            self.skipTest("pytest is not installed in this interpreter")
        temporary = tempfile.TemporaryDirectory(prefix="poseidon-synthetic-pytest-records-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        records = base / "records"
        (records / "tmp").mkdir(parents=True)
        (records / "home").mkdir()
        suite = base / "synthetic-suite"
        suite.mkdir()
        (suite / "test_synthetic_tmp.py").write_text(
            "def test_uses_tmp_path(tmp_path):\n    (tmp_path / 'synthetic.txt').write_text('synthetic')\n")
        environment = guest_checks.command_environment(base / "synthetic-source", records)
        environment["PATH"] = os.environ.get("PATH", environment["PATH"])
        repo_root = Path(__file__).resolve().parents[2]
        completed = subprocess.run([sys.executable, str(repo_root / "scripts/assurance/run_pytest.py"), str(suite), "-q", "-p", "no:cacheprovider"],
                                   cwd=suite, env=environment, text=True, capture_output=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr[-800:])
        self.assertIn("Assurance PASS: collected=1, call_reports=1, pytest_exit=0.", completed.stderr)
        basetemp = Path(environment["PYTEST_ADDOPTS"].removeprefix("--basetemp="))
        self.assertEqual(basetemp, records / "tmp" / "pytest-basetemp")
        self.assertTrue(basetemp.is_relative_to(records))
        # run_pytest.py removes the session scratch, and with it every per-test
        # "...current" symlink pytest made inside it.
        self.assertFalse(basetemp.exists())
        self.assertTrue((records / "tmp").is_dir())
        self.assertEqual([path for path in records.rglob("*") if path.is_symlink()], [])
        self.assertEqual([path for path in records.rglob("pytest-of-*")], [])


if __name__ == "__main__":
    unittest.main()
